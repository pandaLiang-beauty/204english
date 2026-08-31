from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from typing import Any

from ..platform.ai_transport import AIProviderError, _chat_completion, configured as ai_configured, selected_text_model
from .translation_quality import translation_result_issues, validate_translation_result


WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
INLINE_CHINESE_ANNOTATION_PATTERN = re.compile(r"\[[^\]]*[\u4e00-\u9fff][^\]]*\]")
ENGLISH_AI_PREFIX = "STUDY_ENGLISH_AI"


def _focused_sentence(sentence: str) -> str:
    matches = [match.group(1) for match in BOLD_PATTERN.finditer(sentence or "")]
    if matches:
        return " ".join(matches)
    return ""


def extract_words(sentence: str) -> list[str]:
    scoped = _focused_sentence(sentence)
    seen = set()
    words: list[str] = []
    for match in WORD_PATTERN.finditer(scoped):
        word = match.group().strip()
        lowered = word.lower()
        if not word or lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)
    return words


def _normalize_words(words: list[str] | None, sentence: str) -> list[str]:
    candidates = words if words is not None else extract_words(sentence)
    seen = set()
    result: list[str] = []
    for raw in candidates:
        # Historical focus markers occasionally include adjacent sentence
        # punctuation (for example ``**bone-showing.**``).  That punctuation
        # is not part of the word the model is asked to return, so retaining it
        # here would make an otherwise correct response fail exact key matching.
        word = str(raw or "").strip().strip(".,;:!?，。；：！？、()[]{}\"“”‘’")
        lowered = word.lower()
        if not word or lowered in seen:
            continue
        seen.add(lowered)
        result.append(word)
    return result[:40]


def _translation_source(sentence: str) -> str:
    """Return the English source that should be sent to translation tasks.

    Focus markers are display metadata, while square brackets containing Chinese
    are author annotations. Neither is part of the English sentence to translate.
    English-only bracketed source content is retained (for example, citations).
    """
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", str(sentence or ""))
    cleaned = INLINE_CHINESE_ANNOTATION_PATTERN.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    fence_match = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|JSON)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def _decode_json_object_from_text(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fence(text)
    decoder = json.JSONDecoder()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        candidate, _ = decoder.raw_decode(cleaned[start:])
    except json.JSONDecodeError:
        return None
    if isinstance(candidate, dict):
        return candidate
    return None


def _extract_json_object(
    text: str,
    *,
    user_message: str = "AI 返回格式异常，请重试。",
    diagnostic_label: str = "AI JSON",
) -> dict[str, Any]:
    parsed = _decode_json_object_from_text(text)
    if parsed is None:
        cleaned = _strip_code_fence(text)
        raise AIProviderError(user_message, f"{diagnostic_label} parse failed: {cleaned[:1000]}")
    return parsed


def _repair_json_object(
    raw: str,
    *,
    user_message: str,
    diagnostic_label: str,
    expected_schema: str,
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是 JSON 修复器。只输出一个合法 JSON object，不输出 Markdown、代码块、解释或额外文字。"
                "不要新增原输出中没有的信息；缺失字段用空字符串、空数组或空对象。"
            ),
        },
        {
            "role": "user",
            "content": (
                "下面是另一个模型返回的非标准内容，请把它转换成合法 JSON object。\n"
                "目标结构：\n"
                f"{expected_schema}\n\n"
                "原始内容：\n"
                f"{str(raw or '').strip()[:6000]}"
            ),
        },
    ]
    options = _english_ai_options()
    fixed = _chat_completion(messages, **options)
    parsed = _decode_json_object_from_text(fixed)
    if parsed is None:
        raise AIProviderError(user_message, f"{diagnostic_label} repair failed: {str(fixed or '')[:1000]}")
    return parsed


def _compose_word_translation(payload: dict[str, Any]) -> str:
    existing = str(payload.get("translation") or "").strip()
    base = str(
        payload.get("base_translation")
        or payload.get("base_meaning")
        or payload.get("literal_meaning")
        or ""
    ).strip()
    context = str(
        payload.get("context_translation")
        or payload.get("context_meaning")
        or payload.get("meaning_in_sentence")
        or ""
    ).strip()
    if base and context:
        return f"本义：{base}；句中：{context}"
    if context:
        return f"句中：{context}"
    if base:
        return f"本义：{base}"
    return existing


def _clean_tip(word: str, tip: str) -> str:
    cleaned = str(tip or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(rf"^{re.escape(word)}\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned or len(cleaned) > 40:
        return ""
    banned = (
        "重音",
        "音标",
        "音节",
        "拼读",
        "拉丁",
        "来自",
        "源自",
        "词源",
        "单音节",
        "双音节",
        "三音节",
        "四音节",
    )
    if any(item in cleaned for item in banned):
        return ""
    if re.search(r"[读发]\s*/", cleaned):
        return ""
    return cleaned


def _normalize_segment_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in re.split(r"\s*/\s*", value) if item.strip()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    segments: list[str] = []
    for item in raw_items:
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", str(item or "").strip())
        text = text.replace("**", "")
        text = re.sub(r"\s+", " ", text)
        if text:
            segments.append(text)
    return segments[:40]


def _normalize_translation_payload(payload: dict[str, Any], words: list[str]) -> dict:
    sentence_translation = str(
        payload.get("sentence_translation")
        or payload.get("natural_translation")
        or payload.get("translation")
        or ""
    ).strip()
    sentence_segments = _normalize_segment_list(
        payload.get("sentence_segments")
        or payload.get("english_segments")
        or payload.get("source_segments")
    )
    translation_segments = _normalize_segment_list(
        payload.get("translation_segments")
        or payload.get("chinese_segments")
        or payload.get("target_segments")
    )
    pairs = payload.get("segments") or payload.get("segment_pairs") or []
    if isinstance(pairs, list) and (not sentence_segments or not translation_segments):
        pair_sentence_segments: list[str] = []
        pair_translation_segments: list[str] = []
        for item in pairs:
            if not isinstance(item, dict):
                continue
            source = str(item.get("english") or item.get("source") or item.get("text") or "").strip()
            target = str(item.get("chinese") or item.get("translation") or item.get("target") or "").strip()
            if source:
                pair_sentence_segments.append(source)
            if target:
                pair_translation_segments.append(target)
        if not sentence_segments:
            sentence_segments = _normalize_segment_list(pair_sentence_segments)
        if not translation_segments:
            translation_segments = _normalize_segment_list(pair_translation_segments)
    word_items = payload.get("words") or payload.get("items") or payload.get("word_translations") or []
    if isinstance(word_items, dict):
        word_items = [{"word": key, "translation": value} for key, value in word_items.items()]
    if not isinstance(word_items, list):
        word_items = []

    by_lower: dict[str, dict[str, Any]] = {}
    for item in word_items:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "").strip()
        if word:
            by_lower[word.lower()] = item

    ordered = OrderedDict()
    tips: dict[str, str] = {}
    for word in words:
        item = by_lower.get(word.lower(), {})
        translation = _compose_word_translation(item) if item else ""
        if not translation:
            translation = str(item.get("meaning") or item.get("context_translation") or "").strip()
        ordered[word] = translation
        tip = _clean_tip(word, str(item.get("tip") or item.get("spelling_tip") or "").strip())
        if tip:
            tips[word] = tip

    items = [
        {"word": word, "translation": translation, **({"tip": tips[word]} if word in tips else {})}
        for word, translation in ordered.items()
    ]
    return {
        "items": items,
        "word_translations": dict(ordered),
        "word_tips": tips,
        "sentence_translation": sentence_translation,
        "sentence_segments": sentence_segments,
        "translation_segments": translation_segments,
    }


def translation_configured() -> bool:
    base_url = os.getenv(f"{ENGLISH_AI_PREFIX}_BASE_URL", "").strip()
    api_key = os.getenv(f"{ENGLISH_AI_PREFIX}_API_KEY", "").strip()
    if base_url or api_key:
        return bool(base_url and api_key)
    return ai_configured()


def _english_bool_env(name: str) -> bool | None:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return None
    return value in {"1", "true", "yes", "on"}


def _english_number_env(name: str, parser, *, user_label: str) -> Any | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise AIProviderError(
            f"英语翻译 AI 配置无效，请检查{user_label}。",
            f"English AI {name} is invalid: {exc}",
        ) from exc


def _english_ai_options() -> dict[str, Any]:
    base_url = os.getenv(f"{ENGLISH_AI_PREFIX}_BASE_URL", "").strip()
    api_key = os.getenv(f"{ENGLISH_AI_PREFIX}_API_KEY", "").strip()
    if base_url or api_key:
        if not base_url or not api_key:
            raise AIProviderError("英语翻译 AI 服务未完整配置")
        default_model = os.getenv(f"{ENGLISH_AI_PREFIX}_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
        options: dict[str, Any] = {
            "base_url": base_url,
            "api_key": api_key,
            "model": selected_text_model(default=default_model),
        }
    else:
        options = {}
        model = os.getenv(f"{ENGLISH_AI_PREFIX}_MODEL", "").strip()
        selected_model = selected_text_model(default=model or None)
        if selected_model:
            options["model"] = selected_model

    temperature = _english_number_env(
        f"{ENGLISH_AI_PREFIX}_TEMPERATURE",
        float,
        user_label="温度参数",
    )
    if temperature is not None:
        options["temperature"] = temperature

    timeout = _english_number_env(
        f"{ENGLISH_AI_PREFIX}_TIMEOUT_SECONDS",
        float,
        user_label="超时参数",
    )
    if timeout is not None:
        options["timeout_seconds"] = timeout

    disable_thinking = _english_bool_env(f"{ENGLISH_AI_PREFIX}_DISABLE_THINKING")
    if disable_thinking is not None:
        options["disable_thinking"] = disable_thinking

    reasoning_effort = os.getenv(f"{ENGLISH_AI_PREFIX}_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        options["reasoning_effort"] = reasoning_effort

    return options


def _json_from_chat(
    messages: list[dict[str, str]],
    *,
    user_message: str,
    diagnostic_label: str,
    expected_schema: str,
) -> dict[str, Any]:
    raw = _chat_completion(messages, **_english_ai_options())
    if not raw:
        raise AIProviderError(user_message)
    try:
        return _extract_json_object(
            raw,
            user_message=user_message,
            diagnostic_label=diagnostic_label,
        )
    except AIProviderError:
        return _repair_json_object(
            raw,
            user_message=user_message,
            diagnostic_label=diagnostic_label,
            expected_schema=expected_schema,
        )


def _translate_sentence_only(sentence: str, *, feedback: str = "") -> str:
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次结果被质量审查拒绝，原因是："
        f"{retry_feedback}。\n"
        "这次只修正整句中文译文，不要解释。\n\n"
        if retry_feedback
        else ""
    )
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英语句子复习系统里的英汉翻译助手。"
                    "你的任务只有一个：把英文句子翻译成自然、准确、完整的中文。"
                    "不要精读、不要讲解、不要分点、不要保留普通英文词。只输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回 JSON：{\"sentence_translation\":\"自然完整中文译文\"}\n"
                    "要求：\n"
                    "1. 中文必须自然、准确、完整，适合复习时快速理解。\n"
                    "2. 先按中文表达习惯翻译，不要为了后续分块牺牲中文自然度。\n"
                    "3. 遇到英文习语、隐喻、搭配或拟人表达，要译成自然中文，不要生硬直译。例如 perform its duties 不要机械译成“执行其职责”，as the camera performed its magical duties 不要译成“相机执行/履行/施展其神奇职责/功能”，应按上下文译成“相机发挥神奇作用时”等自然说法。\n"
                    "4. 普通英文词不能残留在中文里；只允许保留人名、机构名、品牌、考试名、技术缩写或题目明确要求保留的英文短语。\n"
                    "5. 忽略 **加粗** 标记本身。\n\n"
                    f"{feedback_note}"
                    f"英文句子：{sentence}"
                ),
            },
        ],
        user_message="AI 翻译返回格式异常，请重试。",
        diagnostic_label="sentence translation JSON",
        expected_schema='{"sentence_translation": "自然完整中文译文"}',
    )
    translation = str(
        payload.get("sentence_translation")
        or payload.get("natural_translation")
        or payload.get("translation")
        or ""
    ).strip()
    if not translation:
        raise AIProviderError("AI 翻译返回了空译文")
    return translation


def _review_sentence_only(sentence: str, translation: str, *, feedback: str = "") -> str:
    """Review a sentence translation without mixing in blocks or word cards."""
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次结果被本地检查拒绝，原因是："
        f"{retry_feedback}。只修正与该问题有关的中文译文。\n\n"
        if retry_feedback
        else ""
    )
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英汉翻译终审编辑。只核对英文原句与一条中文译文是否语义准确、自然、完整。"
                    "不要做分块、重点词释义、讲解或格式设计。只输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回 JSON：{\"sentence_translation\":\"终审后的中文译文\"}\n"
                    "规则：\n"
                    "1. 先逐项核对主谓宾、否定、比较、条件、转折、因果、指代、时态和范围。\n"
                    "2. 遇到习语、隐喻和搭配，保留原句逻辑关系并译成自然中文；不能把“陷入某种状态”改成“消失”等不同含义。\n"
                    "3. 草稿已经正确时，原样返回，不要为了文风而随意改写。\n"
                    "4. 不保留普通英文词；不输出解释、评分、Markdown 或额外字段。\n\n"
                    f"{feedback_note}"
                    f"英文原句：{sentence}\n"
                    f"中文草稿：{translation}"
                ),
            },
        ],
        user_message="AI 翻译终审返回格式异常，请重试。",
        diagnostic_label="sentence review JSON",
        expected_schema='{"sentence_translation": "自然完整中文译文"}',
    )
    reviewed = str(
        payload.get("sentence_translation")
        or payload.get("natural_translation")
        or payload.get("translation")
        or ""
    ).strip()
    if not reviewed:
        raise AIProviderError("AI 翻译终审返回了空译文")
    return reviewed


def _translate_words_only(sentence: str, words: list[str], *, feedback: str = "") -> dict:
    if not words:
        return {"items": [], "word_translations": {}, "word_tips": {}}
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次词义结果被质量审查拒绝，原因是："
        f"{retry_feedback}。\n"
        "这次必须修正词义格式或内容。\n\n"
        if retry_feedback
        else ""
    )
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英语句子复习系统里的重点词语境释义助手。"
                    "你只根据完整句子给指定单词做词义，不做句子精读，不输出额外文字。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回 JSON：\n"
                    '{"words":[{"word":"原词","base_translation":"本义","context_translation":"句中义","translation":"本义：...；句中：...","tip":""}]}\n'
                    "要求：\n"
                    "1. words 的顺序必须和给定单词列表一致，不要增删。\n"
                    "2. translation 必须区分本义和句中含义，适合直接展示。\n"
                    "3. context_translation 只写句中义本身，不要写“在句中指”。\n"
                    "4. tip 只有非常确定、有用时才写，20 字以内；只允许词缀、复合结构、易错字母或固定字母组合。\n"
                    "5. tip 不许写音标、重音、音节、泛泛拼读、词源故事；不许出现“来自”“拉丁”“词源”。不确定就返回空字符串。\n"
                    "6. 如果上一次质量反馈包含 bad_tip:某词，则该词 tip 必须返回空字符串。\n\n"
                    f"{feedback_note}"
                    f"英文句子：{sentence}\n"
                    f"单词列表：{', '.join(words)}"
                ),
            },
        ],
        user_message="AI 词义返回格式异常，请重试。",
        diagnostic_label="word translation JSON",
        expected_schema='{"words":[{"word":"原词","base_translation":"本义","context_translation":"句中义","translation":"展示释义","tip":""}]}',
    )
    return _normalize_translation_payload(payload, words)


def _review_translation_result(sentence: str, result: dict[str, Any], words: list[str]) -> list[str]:
    payload = _json_from_chat(
        [
            {
                "role": "system",
                "content": (
                    "你是英语复习材料的质量审查器。"
                    "你只判断材料是否适合阅读复习，不做精读讲解。只输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请审查下面的翻译和阅读块。返回 JSON：{\"ok\":true,\"issues\":[]} 或 {\"ok\":false,\"issues\":[\"具体问题\"]}。\n"
                    "审查标准：\n"
                    "1. 整句中文译文必须准确、自然、完整。\n"
                    "2. 中文不能有生硬直译、英文腔或不合中文习惯的搭配。\n"
                    "3. / 分块是阅读停顿，不是按长度切，也不是语法树切片。\n"
                    "4. 块不能停在还没说完的位置：英文块不能以 that/whether 或 to show that 这类引导结构收尾，也不能把 testify/suggest/believe 等谓语和后面的 that 从句拆开；中文块不能以“表明/说明/指出/证实/提到/事实：/信息：”这类需要后文补足的表达收尾。\n"
                    "5. 每个块应尽量只承载一个阅读动作：话题/主语铺垫、动作或状态、时间/条件背景、主句评价、转折/结果连接、结果本身等。\n"
                    "6. 如果复杂主语块里夹着 as/when/while 背景从句，后面才进入 was/is 等主句评价，通常应判为切得太粗，要求把背景从句单独切出。\n"
                    "7. 如果一个块同时混合“复杂铺垫 + 主句评价/结果”，导致读者必须一口气处理完整长从句，应判为切得太粗。\n"
                    "8. 每个英文块必须是连续原文片段；每个中文块必须是自然中文片段。\n"
                    "9. 英中块表达同一意义单位；如果英中语序不同，应在块内重排，不要硬拆。\n"
                    "10. 切得太碎、切得太粗、孤立后置修饰、中文块不自然，都应指出。\n"
                    "11. 不要因为句子长就要求多切；只有阅读动作混杂或停顿明显缺失时才判粗。\n"
                    "12. 重点词必须有清楚的本义和句中义。\n\n"
                    f"英文原句：{sentence}\n"
                    f"整句中文：{result.get('sentence_translation')}\n"
                    f"英文块：{json.dumps(result.get('sentence_segments') or [], ensure_ascii=False)}\n"
                    f"中文块：{json.dumps(result.get('translation_segments') or [], ensure_ascii=False)}\n"
                    f"重点词：{', '.join(words)}\n"
                    f"词义：{json.dumps(result.get('word_translations') or {}, ensure_ascii=False)}"
                ),
            },
        ],
        user_message="AI 质量审查返回格式异常，请重试。",
        diagnostic_label="translation review JSON",
        expected_schema='{"ok": true, "issues": []}',
    )
    ok = payload.get("ok")
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    if ok is True:
        return []
    return [str(item).strip() for item in issues if str(item).strip()] or ["quality_review_failed"]


def _translate_combined(sentence: str, words: list[str], *, feedback: str = "") -> dict:
    retry_feedback = str(feedback or "").strip()
    feedback_note = (
        "上一次结果未通过本地校验，原因是："
        f"{retry_feedback}。请修正这个问题。\n\n"
        if retry_feedback
        else ""
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是英语句子复习系统的英汉翻译助手。一次完成整句翻译、英中阅读分块和重点词释义。"
                "只输出一个合法 JSON object，不输出 Markdown、解释、代码块或额外文字。"
            ),
        },
        {
            "role": "user",
            "content": (
                "严格返回以下结构：\n"
                "{\n"
                '  "sentence_translation": "自然、准确、完整的中文译文",\n'
                '  "sentence_segments": ["英文阅读块1", "英文阅读块2"],\n'
                '  "translation_segments": ["对应中文块1", "对应中文块2"],\n'
                '  "words": [{"word":"原词","base_translation":"本义","context_translation":"句中义","tip":""}]\n'
                "}\n\n"
                "整句翻译要求：\n"
                "1. 中文自然、准确、完整，按中文表达习惯翻译；普通英文词不能残留。\n"
                "2. 习语、隐喻和搭配按语境意译，避免生硬逐词直译。\n"
                "3. 忽略英文中的 ** 加粗标记。\n\n"
                "分块要求：\n"
                "1. 两个分块数组必须等长、一一对应；英文块按原文顺序完整覆盖原句，只删除 ** 标记。\n"
                "2. 中文块按数组顺序拼接后仍是自然完整的中文；英中语序差异大时使用更大的块，不要硬拆。\n"
                "3. 每个数组元素就是一个阅读块；只通过增加数组元素表示停顿，不按长度或标点机械切分。短句可以只分一块。\n"
                "4. 不要让英文块停在 that、whether、show that、believe that 等未说完的位置；不要孤立句尾修饰语或 if 从句。\n"
                "5. 不要让中文块停在“把、将、从、向、为、认为、表明、说明、导致、规定”等需要后文补足的位置。\n"
                "6. 复杂主语中夹有 as、when、while 背景从句时，可把背景单独成块，再进入主句评价。\n\n"
                "7. 数组元素内部绝对不能出现斜杠；不要在字符串里二次分块。\n\n"
                "重点词要求：\n"
                "1. words 必须与给定重点词列表顺序一致，不增删；没有重点词时返回空数组。\n"
                "2. base_translation 写本义，context_translation 写该句中的具体含义，两项都不能为空。\n"
                "3. tip 仅在非常确定且有助记忆时填写，20 字以内；只写词缀、复合结构、易错字母或固定字母组合。\n"
                "4. tip 禁止出现“来自、词源、拉丁、音标、重音、音节、拼读”等内容；不确定就返回空字符串。\n\n"
                f"{feedback_note}"
                f"英文原句：{sentence}\n"
                f"重点词列表：{json.dumps(words, ensure_ascii=False)}"
            ),
        },
    ]
    raw = _chat_completion(messages, **_english_ai_options())
    payload = _extract_json_object(
        raw,
        user_message="AI 翻译返回格式异常，请重试。",
        diagnostic_label="combined translation JSON",
    )
    return _normalize_translation_payload(payload, words)


def _review_and_repair_combined(
    sentence: str,
    words: list[str],
    candidate: dict[str, Any],
    local_issues: list[str],
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "你是英语复习材料的独立终审编辑。候选结果只是草稿，可能存在漏译、误译、词义偏差或分块错误。"
                "你必须直接返回审核后的完整修正版 JSON，不要只给意见，不要输出 Markdown、解释或额外文字。"
            ),
        },
        {
            "role": "user",
            "content": (
                "严格返回以下完整结构：\n"
                "{\n"
                '  "sentence_translation": "审核后的完整中文译文",\n'
                '  "sentence_segments": ["英文阅读块1", "英文阅读块2"],\n'
                '  "translation_segments": ["对应中文块1", "对应中文块2"],\n'
                '  "words": [{"word":"原词","base_translation":"本义","context_translation":"句中义","tip":""}]\n'
                "}\n\n"
                "终审要求：\n"
                "1. 独立核对英文原句，修正候选中的漏译、误译、生硬直译和逻辑关系错误；不要因为候选已有答案就默认它正确。\n"
                "2. 特别检查否定、条件、转折、not only...but、much of anything、otherwise、习语和后置修饰。\n"
                "3. sentence_translation 必须自然、准确、完整，不残留普通英文词。\n"
                "4. 两个分块数组必须等长并一一对应；英文块按原文顺序完整覆盖原句，只删除 ** 标记。\n"
                "5. 中文块按数组顺序拼接后必须自然；不能把 if 条件放在结果之后，不能停在需要宾语或后文补足的位置。\n"
                "6. 分块困难时宁可整句只保留一块，也不要生成语义未完成或英中错位的块。数组元素内部禁止斜杠。\n"
                "7. words 必须与重点词列表顺序一致，不增删；本义和句中义都不能为空。\n"
                "8. tip 不确定就留空；禁止词源故事以及“来自、源自、词源、拉丁、音标、重音、音节、拼读”等内容。\n\n"
                f"英文原句：{sentence}\n"
                f"重点词列表：{json.dumps(words, ensure_ascii=False)}\n"
                f"本地检查提示：{json.dumps(local_issues, ensure_ascii=False)}\n"
                f"候选草稿：{json.dumps(candidate, ensure_ascii=False)}"
            ),
        },
    ]
    raw = _chat_completion(messages, **_english_ai_options())
    payload = _extract_json_object(
        raw,
        user_message="AI 翻译终审返回格式异常，请重试。",
        diagnostic_label="reviewed translation JSON",
    )
    return _normalize_translation_payload(payload, words)


def _single_segment_fallback(sentence: str, result: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(result)
    translation = str(result.get("sentence_translation") or "").strip()
    fallback["sentence_segments"] = _normalize_segment_list([sentence])
    fallback["translation_segments"] = [translation] if translation else []
    return fallback


def _valid_translation_candidate(sentence: str, words: list[str], result: dict[str, Any]) -> tuple[bool, str]:
    return validate_translation_result(result, words, source_text=sentence)


def translate_text(text: str, *, words: list[str] | None = None, feedback: str = "") -> dict:
    source_sentence = _translation_source(text)
    if not source_sentence:
        raise AIProviderError("句子不能为空")
    selected_words = _normalize_words(words, str(text or ""))

    # V2 keeps semantic work separate from presentation work. The Chinese
    # sentence is locked before either word cards or reading blocks are made.
    try:
        final_translation = _translate_sentence_only(source_sentence, feedback=feedback)
    except AIProviderError:
        raise
    try:
        final_translation = _review_sentence_only(source_sentence, final_translation)
    except AIProviderError:
        # Keep a successful focused draft when the non-essential reviewer is
        # temporarily unavailable; remaining deterministic checks still apply.
        pass

    word_payload = _translate_words_only(source_sentence, selected_words)
    segment_payload = segment_translation(source_sentence, final_translation)

    def build_result() -> dict:
        return {
            "items": word_payload.get("items") or [],
            "word_translations": word_payload.get("word_translations") or {},
            "word_tips": word_payload.get("word_tips") or {},
            "sentence_translation": final_translation,
            "sentence_segments": segment_payload.get("sentence_segments") or [],
            "translation_segments": segment_payload.get("translation_segments") or [],
        }

    result = build_result()
    issues = translation_result_issues(result, selected_words, source_text=source_sentence)
    if issues:
        issue_feedback = "; ".join(issues[:6])
        if any(issue.startswith(("missing_word_translation:", "bad_word_translation_format:", "bad_tip:")) for issue in issues):
            word_payload = _translate_words_only(source_sentence, selected_words, feedback=issue_feedback)
        if any(
            not issue.startswith((
                "empty_sentence_translation",
                "segmented_sentence_translation",
                "literal_translation:",
                "missing_word_translation:",
                "bad_word_translation_format:",
                "bad_tip:",
            ))
            for issue in issues
        ):
            segment_payload = segment_translation(source_sentence, final_translation, feedback=issue_feedback)
        if any(issue.startswith(("empty_sentence_translation", "segmented_sentence_translation", "literal_translation:")) for issue in issues):
            final_translation = _review_sentence_only(source_sentence, final_translation, feedback=issue_feedback)
        result = build_result()

    ok, reason = _valid_translation_candidate(source_sentence, selected_words, result)
    if ok:
        return result
    sentence_or_word_issue = any(
        issue.startswith((
            "empty_sentence_translation",
            "segmented_sentence_translation",
            "literal_translation:",
            "missing_word_translation:",
            "bad_word_translation_format:",
            "bad_tip:",
        ))
        for issue in translation_result_issues(result, selected_words, source_text=source_sentence)
    )
    if not sentence_or_word_issue:
        # Reading blocks are supplementary presentation data. If a focused
        # segmentation request cannot satisfy the strict block rules, preserve
        # the independently validated translation and word cards as one block.
        fallback = _single_segment_fallback(source_sentence, result)
        fallback_ok, _ = _valid_translation_candidate(source_sentence, selected_words, fallback)
        if fallback_ok:
            return fallback
    raise AIProviderError(
        "AI 翻译结果未通过本地校验，请重试。",
        f"split translation validation failed: {reason or 'unknown'}",
    )


def segment_translation(text: str, sentence_translation: str, *, feedback: str = "") -> dict:
    sentence = str(text or "").strip()
    translation = str(sentence_translation or "").strip()
    retry_feedback = str(feedback or "").strip()
    if not sentence:
        raise AIProviderError("句子不能为空")
    if not translation:
        raise AIProviderError("整句翻译不能为空")
    feedback_note = (
        "上一次输出被质量闸门拒绝，原因是："
        f"{retry_feedback}。\n"
        "这次必须先修正该原因；如果原因是 undersegmented_subject_background，必须把复杂主语中的 as/when/while 背景从句单独切出。\n"
        "如果无法在保持中文自然的前提下细分，就整句只切 1 块。\n\n"
        if retry_feedback
        else ""
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是英语句子复习系统里的分块对照助手。"
                "你只输出 JSON，不输出 Markdown、解释、代码块或额外文字。"
                "你的任务不是重新翻译，而是在保留既有中文译文含义的前提下，把英文原句和中文译文切成对应阅读块。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请把英文原句和既有中文译文切成一一对应的阅读块。\n"
                "返回 JSON 对象，格式严格如下：\n"
                "{\n"
                '  "sentence_segments": ["英文阅读块1", "英文阅读块2"],\n'
                '  "translation_segments": ["对应中文块1", "对应中文块2"]\n'
                "}\n"
                "要求：\n"
                "1. 不要重新翻译整句，不要改变既有中文译文的核心含义；但允许为了让块自然，对中文块做局部语序调整或轻微改写。\n"
                "2. sentence_segments 与 translation_segments 必须一一对应。\n"
                "3. 分块的最高优先级是中文自然：每个中文块单独看也必须是自然片段，不能出现“领导层之间。”、“在他解放的地区。”、“保守势力的。”这类孤立后置片段。\n"
                "4. 先按既有中文译文的自然表达切块，再选择覆盖这些含义的英文连续片段；不要为了英文语法细分而破坏中文语序。\n"
                "5. 最终展示时会按数组顺序显示中文块；这些中文块顺序拼起来必须仍然是自然中文，不能变成英文语序的中文。\n"
                "6. 如果英文和中文语序差异很大，分块会导致中文顺序别扭，就必须合并成更大的块，在块内完成语序重排。\n"
                "7. / 是阅读停顿：只有当一个停顿能帮助读者逐步理解句子时才切；不要按长度、逗号或语法名词机械切。\n"
                "8. 每个块应尽量只承载一个阅读动作：话题/主语铺垫、动作或状态、时间/条件背景、主句评价、转折/结果连接、结果本身等。\n"
                "9. 不要把可自然分开的复杂铺垫和主句评价合进同一块；例如“某个想法/行为内容/令人难以接受”通常应拆成可逐步阅读的块。\n"
                "10. 如果一个复杂主语块里夹着 as/when/while 背景从句，后面才进入 was/is 等主句评价，通常要把背景从句单独切出来；不要把“想法/行为内容/背景时间”全部塞进一个块。\n"
                "11. 明显的并列、转折、结果、主干推进处通常是候选停顿，但仍必须服从中文自然和英中意义对应。\n"
                "12. 块不能停在还没说完的位置：英文块不能以 that/whether 或 to show that 这类引导结构收尾，也不能把 testify/suggest/believe 等谓语和后面的 that 从句拆开；is cited/is quoted 不能脱离主语单独成块；中文块不能以“表明/说明/指出/证实/提到/事实：/信息：”这类需要后文补足的表达收尾。\n"
                "13. 中文块不能停在需要宾语或后续内容的词上，例如“将”“把”“从”“向”“为”“于”“并”“认为”“否决”“规定”“导致”“可能导致”“依赖于”“适用于”；遇到这类情况必须和后面的内容合并。\n"
                "14. 不要拆开会在中文里倒装的整体，例如 inhabitants of these nations 应作为一个英文块，对应“这些国家的居民”。\n"
                "15. 前置分词/介词结构如果中文需要和主语合在一起才自然，就把它和主语放在同一个块里。\n"
                "16. 句尾介词短语或定语从句如果中文要提前，如 among the leadership、for the conservative forces、in the areas he liberated、her parents have chosen、in a few months、in their retirement income、within 15 years、from legislative halls to Wal-Mart workers、that feed the World Cup，不要单独拆成最后一块。\n"
                "17. It is not obvious how... 这类英文前置判断、中文后置“这一点并不明显”的结构，不要按英文顺序拆；整句合并成 1 块。\n"
                "18. 任何句首 Born in... / Born into... / Born of... 不能单独作为英文块；它必须并入后面的主语块，做不到就整句 1 块。\n"
                "19. 英文主句在前、if 条件从句在句尾，而中文需要“如果...就...”时，不要拆成“就... / 如果...”；整句合并成 1 块。\n"
                "20. fears that、concern that、worry that 这类“担心/忧虑 + that 从句”必须和 that 从句合并成自然中文块，不要切成“因担心而...”和一个孤立从句。\n"
                "21. 英文分块必须保持原文词序，不能改写、补词或丢词；不要让分块以逗号、分号、冒号开头。\n"
                "22. 不要机械逐词硬译介词短语；例如 for the conservative forces 应合并译成“保守势力的战斗口号”，不要译成“对于保守势力而言”。\n"
                "23. 分块只保留原文/译文本身，不要加入斜杠、编号、括号标签或说明。\n"
                "24. 如果英文里有 **加粗** 标记，分块时忽略标记本身。\n\n"
                "坏例子与修正：\n"
                "bad: [\"became\", \"a rallying cry\", \"for the conservative forces.\"] -> [\"成了\", \"战斗口号\", \"保守势力的。\"]\n"
                "good: [\"became a rallying cry for the conservative forces.\"] -> [\"成了保守势力的战斗口号。\"]\n"
                "bad: [\"to abolish slavery\", \"in the areas he liberated.\"] -> [\"废除奴隶制\", \"在他解放的地区。\"]\n"
                "good: [\"to abolish slavery in the areas he liberated.\"] -> [\"在他解放的地区废除奴隶制。\"]\n\n"
                "bad: [\"were often tempered by fears\", \"that the mass was unprepared\"] -> [\"常常因担心而有所缓和\", \"大众尚未准备好\"]\n"
                "good: [\"were often tempered by fears that the mass was unprepared\"] -> [\"常常因担心大众尚未准备好而有所缓和\"]\n\n"
                "bad: [\"Born in the crisis...,\", \"many of the leaders\", \"shared...\"] -> [\"出生于危机之中，\", \"许多领导人\", \"共同怀有...\"]\n"
                "good: [\"Born in the crisis..., many of the leaders\", \"shared...\"] -> [\"许多领导人出生于危机之中，\", \"共同怀有...\"]\n\n"
                "bad: [\"It's not obvious\", \"how the capacity...\", \"suits one...\"] -> [\"这一点并不明显\", \"如何...的能力\", \"适合...\"]\n"
                "good: [\"It's not obvious how the capacity... suits one...\"] -> [\"如何...的能力适合...，这一点并不明显。\"]\n\n"
                "bad: [\"he would have more opportunity...\", \"if he switched to psychology\"] -> [\"就会有更多机会...\", \"如果他转学心理学\"]\n"
                "good: [\"he would have more opportunity... if he switched to psychology\"] -> [\"如果他转学心理学，就会有更多机会...\"]\n\n"
                "bad: [\"can reduce a family...\", \"in a few months\"] -> [\"能将一个家庭变成新穷人\", \"在几个月内\"]\n"
                "good: [\"can reduce a family... in a few months\"] -> [\"能在几个月内将一个家庭变成新穷人\"]\n"
                "bad: [\"is reduced on average by 80%\", \"within 15 years\"] -> [\"平均减少了80%\", \"在15年内\"]\n"
                "good: [\"is reduced on average by 80% within 15 years\"] -> [\"在15年内平均减少了80%\"]\n"
                "bad: [\"are spreading\", \"from legislative halls to Wal-Mart workers\"] -> [\"正从\", \"立法大厅扩展到沃尔玛员工\"]\n"
                "good: [\"are spreading from legislative halls to Wal-Mart workers\"] -> [\"正从立法大厅扩展到沃尔玛员工\"]\n\n"
                "bad: [\"could result in\", \"a fine and prison\"] -> [\"可能导致\", \"罚款和监禁\"]\n"
                "good: [\"could result in a fine and prison\"] -> [\"可能导致罚款和监禁\"]\n"
                "bad: [\"would make it a crime\", \"to employ models\"] -> [\"规定\", \"雇佣模特属于犯罪\"]\n"
                "good: [\"would make it a crime to employ models\"] -> [\"规定雇佣模特属于犯罪\"]\n\n"
                "bad: [\"relies on\", \"a method\"] -> [\"依赖于\", \"一种方法\"]\n"
                "good: [\"relies on a method\"] -> [\"依赖于一种方法\"]\n\n"
                "bad: [\"may transfer\", \"to other parts of Asia\"] -> [\"可能也适用于\", \"亚洲其他地区\"]\n"
                "good: [\"may transfer to other parts of Asia\"] -> [\"可能也适用于亚洲其他地区\"]\n\n"
                "bad: [\"They believe\", \"the data support an idea\"] -> [\"他们认为\", \"这些数据支持一种观点\"]\n"
                "good: [\"They believe the data support an idea\"] -> [\"他们认为这些数据支持一种观点\"]\n\n"
                "bad: [\"The thought of holding a fixed grin as the camera performed its magical duties\", \"was too much to contemplate,\"] -> [\"一想到要在相机发挥神奇作用时保持固定的咧嘴笑，\", \"就让人难以忍受，\"]\n"
                "good: [\"The thought of holding a fixed grin\", \"as the camera performed its magical duties\", \"was too much to contemplate,\"] -> [\"一想到要保持固定的咧嘴笑\", \"在相机发挥神奇作用时\", \"就让人难以忍受，\"]\n\n"
                "bad: [\"will testify\", \"that test-taking skill also matters\"] -> [\"都会证实\", \"应试技巧也很重要\"]\n"
                "good: [\"will testify that test-taking skill also matters\"] -> [\"都会证实应试技巧也很重要\"]\n\n"
                "bad: [\"would suggest to women\", \"that they should not...\"] -> [\"将向女性传达一个信息：\", \"她们不应...\"]\n"
                "good: [\"would suggest to women that they should not...\"] -> [\"将向女性传达她们不应...\"]\n\n"
                "bad: [\"is cited to show that\", \"cattle raising has been...\"] -> [\"被引用来表明，\", \"养牛一直是...\"]\n"
                "good: [\"The study ... is cited\", \"to show that cattle raising has been...\"] -> [\"这项研究被引用，\", \"旨在说明养牛一直是...\"]\n\n"
                "bad: [\"The study based on an area in Mexico\", \"is cited\", \"to show that...\"] -> [\"这项基于墨西哥某地区的研究\", \"被引用，\", \"旨在表明...\"]\n"
                "good: [\"The study based on an area in Mexico is cited\", \"to show that...\"] -> [\"这项基于墨西哥某地区的研究被引用，\", \"旨在表明...\"]\n\n"
                "bad: [\"alluding to the fact that\", \"before the birth...\"] -> [\"提到这样一个事实：\", \"在...之前\"]\n"
                "good: [\"alluding to the fact that before the birth...\", \"mouths were often...\"] -> [\"提到这样一个事实：在...之前，\", \"人们的口腔往往...\"]\n\n"
                "bad: [\"the spouse\", \"her parents have chosen\"] -> [\"配偶\", \"父母为她选定的\"]\n"
                "good: [\"the spouse her parents have chosen\"] -> [\"父母为她选定的配偶\"]\n\n"
                "分块示例：\n"
                "英文：The thought of holding a fixed grin as the camera performed its magical duties was too much to contemplate, and so a non-committal blank stare became the norm.\n"
                "中文：一想到要保持固定的咧嘴笑，在相机发挥神奇作用时，就让人难以忍受，于是一种不置可否的茫然凝视成了常态。\n"
                "sentence_segments: [\"The thought of holding a fixed grin\", \"as the camera performed its magical duties\", \"was too much to contemplate,\", \"and so\", \"a non-committal blank stare\", \"became the norm.\"]\n"
                "translation_segments: [\"一想到要保持固定的咧嘴笑\", \"在相机发挥神奇作用时\", \"就让人难以忍受，\", \"于是\", \"一种不置可否的茫然凝视\", \"成了常态。\"]\n\n"
                f"{feedback_note}"
                f"英文原句：{sentence}\n"
                f"既有中文译文：{translation}"
            ),
        },
    ]
    raw = _chat_completion(messages, **_english_ai_options())
    if not raw:
        raise AIProviderError("AI 分块返回了空结果")
    try:
        payload = _extract_json_object(
            raw,
            user_message="AI 分块返回格式异常，请重试。",
            diagnostic_label="segment JSON",
        )
    except AIProviderError:
        payload = _repair_json_object(
            raw,
            user_message="AI 分块返回格式异常，请重试。",
            diagnostic_label="segment JSON",
            expected_schema='{"sentence_segments": ["英文阅读块"], "translation_segments": ["对应中文块"]}',
        )
    normalized = _normalize_translation_payload(payload, [])
    normalized["sentence_translation"] = translation
    return normalized
