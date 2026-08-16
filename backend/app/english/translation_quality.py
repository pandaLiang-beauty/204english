from __future__ import annotations

import json
import re
from typing import Any


BAD_SENTENCE_MARKERS = ("英文：", "中文：", "👉", "1)", "2)")
BAD_LITERAL_TRANSLATION_SUBSTRINGS = (
    "执行其神奇职责",
    "履行其神奇职责",
    "施展其神奇功能",
    "标价震惊",
)
BAD_TIP_MARKERS = (
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
BAD_SEGMENT_PREFIXES = (",", "，", ";", "；", ":", "：")
INCOMPLETE_ENGLISH_SEGMENT_SUFFIXES = (
    " that",
    " whether",
)
INCOMPLETE_ENGLISH_SEGMENT_EXACTS = (
    "is cited",
    "are cited",
    "was cited",
    "were cited",
    "is quoted",
    "are quoted",
    "was quoted",
    "were quoted",
)
INCOMPLETE_ENGLISH_SEGMENT_PATTERNS = (
    re.compile(r"\b(?:show|shows|showed|shown|indicate|indicates|indicated|suggest|suggests|suggested)\s+that$", re.I),
    re.compile(r"\b(?:argue|argues|argued|claim|claims|claimed|believe|believes|believed|think|thinks|thought)\s+that$", re.I),
    re.compile(r"\b(?:testify|testifies|testified|demonstrate|demonstrates|demonstrated)\s+that$", re.I),
    re.compile(r"\b(?:find|finds|found|note|notes|noted|point(?:s|ed)?\s+out)\s+that$", re.I),
    re.compile(r"\ballud(?:e|es|ed|ing)\s+to\s+the\s+fact\s+that$", re.I),
)
THAT_CLAUSE_EXPECTING_PREVIOUS_PATTERNS = (
    re.compile(r"\b(?:reveal|reveals|revealed)$", re.I),
    re.compile(r"\b(?:testify|testifies|testified)$", re.I),
    re.compile(r"\b(?:demonstrate|demonstrates|demonstrated|prove|proves|proved)$", re.I),
    re.compile(r"\b(?:show|shows|showed|shown|indicate|indicates|indicated)$", re.I),
    re.compile(r"\b(?:suggest|suggests|suggested)(?:\s+to\b.*)?$", re.I),
    re.compile(r"\b(?:argue|argues|argued|claim|claims|claimed|believe|believes|believed|think|thinks|thought)$", re.I),
    re.compile(r"\b(?:find|finds|found|note|notes|noted|imply|implies|implied)$", re.I),
    re.compile(r"\bpoint(?:s|ed)?\s+out$", re.I),
)
BAD_TRANSLATION_SEGMENT_SUFFIXES = (
    "把",
    "并",
    "从",
    "导致",
    "规定",
    "将",
    "可能导致",
    "否决",
    "认为，",
    "认为。",
    "于",
    "为",
    "向",
)
BAD_MULTI_TRANSLATION_SEGMENT_SUFFIXES = (
    "选定的",
    "选定的。",
    "选定的，",
    "健康的",
    "健康的。",
    "健康的，",
    "之间。",
    "之间，",
    "地区。",
    "地区，",
    "势力的。",
    "势力的，",
)
INCOMPLETE_TRANSLATION_SEGMENT_SUFFIXES = (
    "表明",
    "说明",
    "显示",
    "指出",
    "认为",
    "声称",
    "发现",
    "意味着",
    "提到",
    "暗示",
    "证明",
    "证实",
    "这个事实",
    "一个事实",
    "这样一个事实",
    "一个信息",
    "信息",
)
BAD_TRANSLATION_SEGMENT_SUBSTRINGS = (
    "因担心而",
    "因忧虑而",
)
BAD_MULTI_SEGMENT_TRANSLATION_PREFIXES = (
    "如何",
)
REVERSED_JUDGMENT_PREFIXES = (
    "这一点",
    "这点",
)
REVERSED_JUDGMENT_FOLLOWUPS = (
    "如何",
)
REVERSED_IF_RESULT_PREFIXES = (
    "就",
)
REVERSED_IF_CONDITION_PREFIXES = (
    "如果",
)
STANDALONE_MODIFIER_PREFIXES = (
    "among ",
    "for ",
    "from ",
    "in ",
    "in the areas ",
    "that feed ",
    "within ",
)
ALLOWED_STANDALONE_MODIFIER_PREFIXES = (
    "for the fact that ",
)
BORN_MODIFIER_PREFIXES = (
    "born in ",
    "born into ",
    "born of ",
)
FACT_THAT_PATTERN = re.compile(r"\bfact\s+that\b", re.I)
WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
COMPLEX_SUBJECT_START_PATTERN = re.compile(
    r"^(?:the\s+)?(?:thought|idea|prospect|possibility|act|process|problem|challenge|task)\b",
    re.I,
)
EMBEDDED_BACKGROUND_PATTERN = re.compile(r"\b(?:as|when|while)\s+\w+", re.I)
MAIN_PREDICATE_START_PATTERN = re.compile(
    r"^(?:was|were|is|are|seems?|seemed|became|becomes|proved|proves|turned)\b",
    re.I,
)


def _json_loads_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_loads_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _is_standalone_born_modifier(text: str) -> bool:
    stripped = str(text or "").strip()
    return stripped.endswith(",") and stripped.lower().startswith(BORN_MODIFIER_PREFIXES)


def _strip_trailing_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip(".,;:!?，。；：！？、").strip()


def _has_incomplete_english_suffix(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text)
    lowered = f" {stripped.lower()}"
    if stripped.lower() in INCOMPLETE_ENGLISH_SEGMENT_EXACTS:
        return True
    if any(lowered.endswith(suffix) for suffix in INCOMPLETE_ENGLISH_SEGMENT_SUFFIXES):
        return True
    return any(pattern.search(stripped) for pattern in INCOMPLETE_ENGLISH_SEGMENT_PATTERNS)


def _has_incomplete_translation_suffix(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text)
    return any(stripped.endswith(suffix) for suffix in INCOMPLETE_TRANSLATION_SEGMENT_SUFFIXES)


def _previous_segment_expects_that_clause(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text)
    return any(pattern.search(stripped) for pattern in THAT_CLAUSE_EXPECTING_PREVIOUS_PATTERNS)


def _is_undersegmented_subject_background(segment: str, next_segment: str) -> bool:
    stripped = _strip_trailing_punctuation(segment)
    if len(WORD_PATTERN.findall(stripped)) < 9:
        return False
    return (
        bool(COMPLEX_SUBJECT_START_PATTERN.search(stripped))
        and bool(EMBEDDED_BACKGROUND_PATTERN.search(stripped))
        and bool(MAIN_PREDICATE_START_PATTERN.search(_strip_trailing_punctuation(next_segment)))
    )


def translation_result_issues(result: dict[str, Any], words: list[str], *, source_text: str = "") -> list[str]:
    issues: list[str] = []
    sentence = str(result.get("sentence_translation") or "").strip()
    if not sentence:
        issues.append("empty_sentence_translation")
    if any(marker in sentence for marker in BAD_SENTENCE_MARKERS):
        issues.append("segmented_sentence_translation")
    for marker in BAD_LITERAL_TRANSLATION_SUBSTRINGS:
        if marker in sentence:
            issues.append(f"literal_translation:{marker}")

    sentence_segments = result.get("sentence_segments") if isinstance(result.get("sentence_segments"), list) else []
    translation_segments = result.get("translation_segments") if isinstance(result.get("translation_segments"), list) else []
    if not sentence_segments or not translation_segments:
        issues.append("missing_segments")
    elif len(sentence_segments) != len(translation_segments):
        issues.append("segment_count_mismatch")
    if source_text and sentence_segments:
        source_words = [word.casefold() for word in WORD_PATTERN.findall(source_text)]
        segmented_words = [
            word.casefold()
            for word in WORD_PATTERN.findall(" ".join(str(item or "") for item in sentence_segments))
        ]
        if source_words != segmented_words:
            issues.append("source_segment_coverage_mismatch")

    if len(sentence_segments) == 1:
        only_segment = str(sentence_segments[0] or "")
        word_count = len(WORD_PATTERN.findall(only_segment))
        if word_count >= 14 and FACT_THAT_PATTERN.search(only_segment) and "," in only_segment:
            issues.append("undersegmented_fact_that_sentence")

    for index, segment in enumerate(sentence_segments):
        text = str(segment or "").strip()
        if not text:
            issues.append("empty_sentence_segment")
            continue
        if text.startswith(BAD_SEGMENT_PREFIXES):
            issues.append(f"bad_sentence_segment_prefix:{text[:20]}")
        elif "/" in text and "/" not in source_text:
            issues.append(f"bad_sentence_segment_slash:{text[:20]}")
        elif "**" in text:
            issues.append(f"bad_sentence_segment_marker:{text[:20]}")
        if index < len(sentence_segments) - 1 and _has_incomplete_english_suffix(text):
            issues.append(f"incomplete_sentence_segment_suffix:{text[:30]}")
        if index < len(sentence_segments) - 1 and _is_undersegmented_subject_background(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"undersegmented_subject_background:{text[:30]}")
        lowered = text.lower()
        previous_ended_sentence = index > 0 and str(sentence_segments[index - 1] or "").strip().endswith((".", "?", "!"))
        allowed_modifier = any(lowered.startswith(prefix) for prefix in ALLOWED_STANDALONE_MODIFIER_PREFIXES)
        if (
            index > 0
            and not previous_ended_sentence
            and not allowed_modifier
            and any(lowered.startswith(prefix) for prefix in STANDALONE_MODIFIER_PREFIXES)
        ):
            issues.append(f"standalone_modifier_segment:{text[:30]}")
        elif _is_standalone_born_modifier(text):
            issues.append(f"standalone_born_modifier:{text[:30]}")
        elif (
            index > 0
            and lowered.startswith("that ")
            and _previous_segment_expects_that_clause(str(sentence_segments[index - 1] or ""))
        ):
            issues.append(f"standalone_that_clause:{text[:30]}")
        elif index > 0 and lowered.startswith("if "):
            issues.append(f"standalone_if_clause:{text[:30]}")

    reversed_judgment_first = False
    for index, segment in enumerate(translation_segments):
        text = str(segment or "").strip()
        if not text:
            issues.append("empty_translation_segment")
            continue
        if "/" in text:
            issues.append(f"bad_translation_segment_slash:{text[:20]}")
        elif text.endswith(BAD_TRANSLATION_SEGMENT_SUFFIXES):
            issues.append(f"bad_translation_segment_suffix:{text[:20]}")
        elif len(translation_segments) > 1 and text.endswith(BAD_MULTI_TRANSLATION_SEGMENT_SUFFIXES):
            issues.append(f"bad_translation_segment_suffix:{text[:20]}")
        elif any(item in text for item in BAD_TRANSLATION_SEGMENT_SUBSTRINGS):
            issues.append(f"bad_translation_segment_text:{text[:20]}")
        elif len(translation_segments) > 1 and text.startswith(BAD_MULTI_SEGMENT_TRANSLATION_PREFIXES):
            issues.append(f"bad_translation_segment_prefix:{text[:20]}")
        if index < len(translation_segments) - 1 and _has_incomplete_translation_suffix(text):
            issues.append(f"incomplete_translation_segment_suffix:{text[:20]}")
        if index == 0 and text.startswith(REVERSED_JUDGMENT_PREFIXES):
            reversed_judgment_first = True

    if reversed_judgment_first and any(
        str(segment or "").strip().startswith(REVERSED_JUDGMENT_FOLLOWUPS)
        for segment in translation_segments[1:]
    ):
        issues.append("bad_translation_segment_order")
    if translation_segments and str(translation_segments[0] or "").strip().startswith(REVERSED_IF_RESULT_PREFIXES) and any(
        str(segment or "").strip().startswith(REVERSED_IF_CONDITION_PREFIXES)
        for segment in translation_segments[1:]
    ):
        issues.append("bad_translation_segment_if_order")

    translations = result.get("word_translations") if isinstance(result.get("word_translations"), dict) else {}
    for word in words:
        text = str(translations.get(word) or "").strip()
        if not text:
            issues.append(f"missing_word_translation:{word}")
        elif "本义：" not in text or "句中：" not in text:
            issues.append(f"bad_word_translation_format:{word}")

    tips = result.get("word_tips") if isinstance(result.get("word_tips"), dict) else {}
    for word, tip in tips.items():
        if any(marker in str(tip or "") for marker in BAD_TIP_MARKERS):
            issues.append(f"bad_tip:{word}")
    return issues


def validate_translation_result(result: dict[str, Any], words: list[str], *, source_text: str = "") -> tuple[bool, str]:
    issues = translation_result_issues(result, words, source_text=source_text)
    return (not issues, issues[0] if issues else "")


def stored_translation_issues(row: dict[str, Any], words: list[str]) -> list[str]:
    result = {
        "sentence_translation": row.get("sentence_translation") or "",
        "sentence_segments": _json_loads_list(row.get("sentence_segments_json")),
        "translation_segments": _json_loads_list(row.get("translation_segments_json")),
        "word_translations": _json_loads_dict(row.get("word_translations_json")),
        "word_tips": _json_loads_dict(row.get("word_tips_json")),
    }
    return translation_result_issues(result, words, source_text=str(row.get("text") or ""))


def row_has_bad_translation(row: dict[str, Any], words: list[str]) -> bool:
    return bool(stored_translation_issues(row, words))
