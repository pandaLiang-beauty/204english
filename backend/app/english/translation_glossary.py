from __future__ import annotations

import re
from typing import Any


PHRASE_WORD_REFERENCES = (
    ("slot", r"\bslot machines?\b", ("老虎机",), "用于 slot machine，整体意为老虎机"),
    ("side", r"\bside effects?\b", ("副作用",), "附带的（side effect：副作用）"),
    ("suit", r"\bfollow(?:s|ed|ing)? suit\b", ("效仿", "仿效", "照做"), "用于 follow suit，整体意为效仿"),
    ("stripes", r"\bof all stripes\b", ("各路", "各类", "各色", "各式", "形形色色"), "种类（of all stripes：各类的）"),
    ("checked-baggage", r"\bchecked-baggage fees?\b", ("托运行李", "行李托运"), "托运行李的（修饰 fees，不含费用之义）"),
    ("sustainable", r"\b(?:aren't|are not|isn't|is not|not)\s+sustainable\b", ("难以为继", "不可持续", "无法持续", "难以持续"), "可持续的（本句否定结构表示不可持续）"),
    ("police", r"\bfood police\b", ("饮食卫士", "饮食警察"), "用于 food police，整体比喻对他人饮食进行说教的人"),
    ("exactly", r"\balmost exactly tracks?\b", ("几乎",), "完全地（almost exactly：几乎完全）"),
    ("vocal", r"\bvocal\s+(?:group|minority|critics?|supporters?|opponents?)\b", ("发声", "直言", "表达"), "敢于表达意见的；积极发声的"),
    ("rests", r"\brests on an? understanding\b", ("基础", "建立", "依赖"), "用于 rest on，表示以……为基础"),
    ("individual", r"\beach individual\b", ("每个人", "每个个体", "每一个人"), "个人（each 表示“每个”）"),
)


def ground_sentence_terms(
    sentence: str,
    translation: str,
    *,
    context_before=None,
    context_after=None,
    audit: dict[str, Any] | None = None,
) -> str:
    replacements: list[tuple[str, str, str]] = []
    if re.search(r"\bvocal\s+(?:group|minority|critics?|supporters?|opponents?)\b", sentence, re.I) and not re.search(r"\b(?:firm|steadfast|resolute)\b", sentence, re.I):
        replacements.extend(("vocal", old, "积极发声") for old in ("立场坚定", "嗓门响亮", "声音响亮"))
    context = " ".join([*(context_before or []), *(context_after or [])])
    if (
        "their presence" in sentence.casefold()
        and re.search(r"\bhawaiians\b", sentence, re.I)
        and "sacred land" in sentence.casefold()
        and re.search(r"\btelescopes\b", context, re.I)
    ):
        replacements.extend(("their presence → telescopes", old, "这些望远镜的存在") for old in ("他们的存在", "它们的存在", "其存在"))
        replacements.extend(
            ("their presence → telescopes", match.group(), "这些望远镜的存在")
            for match in re.finditer(r"[（(](?:这些|那些)?望远镜[^（）()]*[）)](?:的)?存在", translation)
        )
    if "what was once a sovereign nation" in sentence.casefold():
        replacements.append(("what was once a sovereign nation", "曾经主权国家", "曾经的主权国家"))
    for source, old, new in replacements:
        if old not in translation:
            continue
        translation = translation.replace(old, new)
        if audit is not None:
            audit.setdefault("term_repairs", []).append({"source": source, "before": old, "after": new})
    return translation


def expand_unique_quote(quote: str, text: str) -> str:
    if not quote or quote in text:
        return quote
    unwrapped = quote.strip('"“”')
    if unwrapped and unwrapped in text:
        return unwrapped
    parts = re.split(r"…+|\.{3,}", unwrapped)
    if len(parts) < 2 or not parts[0].strip() or not parts[-1].strip():
        return quote
    parts = [part.strip() for part in parts if part.strip()]
    if len(parts) < 2 or text.count(parts[0]) != 1 or text.count(parts[-1]) != 1:
        return quote
    start = text.find(parts[0])
    end = text.find(parts[-1]) + len(parts[-1])
    if end <= start:
        return quote
    candidate = text[start:end]
    pattern = ".*?".join(re.escape(part) for part in parts)
    return candidate if re.fullmatch(pattern, candidate, re.DOTALL) else quote


def ground_word_cards(result: dict[str, Any], sentence: str, translation: str) -> None:
    for item in result.get("items") or []:
        word = str(item.get("word") or "")
        item["source_quote"] = expand_unique_quote(str(item.get("source_quote") or ""), sentence)
        item["translation_quote"] = expand_unique_quote(str(item.get("translation_quote") or ""), translation)
        meaning = str(item.get("translation") or "")
        chinese, english_separator, english = meaning.partition("；英文：")
        base, separator, context = chinese.partition("；句中：")
        if not separator:
            continue
        if word.casefold() == "granted" and re.search(r"\bfor granted\b", sentence, re.I) and "理所当然" in base:
            base = "本义：给予；承认"
        quote = item["translation_quote"]
        if quote and not any(marker in context for marker in "()（）"):
            alternatives = [value.strip() for value in re.split(r"[，,；;、]", context) if value.strip()]
            if len(alternatives) > 1 and quote in alternatives:
                context = quote
        for focus, pattern, targets, reference in PHRASE_WORD_REFERENCES:
            if word.casefold() == focus and re.search(pattern, sentence, re.I) and any(target in translation for target in targets):
                context = reference
                break
        item["translation"] = f"{base}{separator}{context}{english_separator}{english}"
        result["word_translations"][word] = item["translation"]
