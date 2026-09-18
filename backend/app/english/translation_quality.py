from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


BAD_SENTENCE_MARKERS = ("英文：", "中文：", "👉", "1)", "2)")
BAD_LITERAL_TRANSLATION_SUBSTRINGS = (
    "执行其神奇职责",
    "履行其神奇职责",
    "施展其神奇功能",
    "标价震惊",
    "夜间睡觉地方",
    "睡觉地方的收容所",
    "睡觉的地方的收容所",
    "这些诸多",
    "其正试图",
    "我们宇宙中心",
    "去流利掌握",
    "称号获得城市",
    "再次悲惨地提醒",
    "为了不顾一切地",
    "我们这个宇宙中心",
    "持续、反复且无法控制地追求的",
    "对身体和经济援助",
    "一项可取组成",
    "令人悲痛地提醒",
    "达到流利使用",
    "只有有能够",
    "承诺来得慢",
    "双收入状态的极限",
    "一位年老体弱的父母",
    "被每个人对信息“编码”得有多好",
    "劝阻他们说",
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
# These are not semantic errors in the whole translation, but they make the
# visual ``//`` reader stop in the middle of a function-word unit. Keep the
# list deliberately small: a connector such as ``and so`` can be a useful
# reading beat, while a bare pronoun or ``or`` almost never is.
WEAK_ENGLISH_SEGMENT_EXACTS = frozenset(
    {
        "it",
        "they",
        "he",
        "she",
        "we",
        "you",
        "i",
        "are there",
        "there is",
        "there are",
        "or",
        "and",
        "but",
    }
)
WEAK_TRANSLATION_SEGMENT_EXACTS = frozenset(
    {
        "它",
        "他们",
        "她们",
        "他",
        "她",
        "我们",
        "你们",
        "或者",
        "或",
        "以及",
        "但是",
        "并且",
    }
)
WEAK_ENGLISH_SEGMENT_ENDINGS = frozenset(
    {
        "and",
        "or",
        "but",
        "not",
        "either",
        "neither",
        "both",
        "more",
        "less",
        "to",
        "of",
        "for",
        "with",
        "as",
        "than",
        "by",
        "in",
        "on",
        "at",
        "into",
        "onto",
        "within",
        "a",
        "an",
        "the",
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "such",
        "although",
        "because",
        "if",
        "unless",
        "where",
        "whereas",
        "while",
    }
)
WEAK_TRANSLATION_SEGMENT_ENDINGS = frozenset(
    {
        "以及",
        "或者",
        "或",
        "并且",
        "而",
        "但",
        "不仅",
        "不只",
        "不但",
        "虽然",
        "尽管",
        "那么",
    }
)
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
    # A preposition-governing verb is not a usable stopping point.  In
    # particular, ``... results`` followed by ``in fines`` was a recurring
    # compact-cut error: the complement belongs to the preceding action.
    re.compile(
        r"\b(?:result|results|depend|depends|lead|leads|apply|applies|rely|relies|refer|refers|consist|consists|account|accounts)\s*$",
        re.I,
    ),
    re.compile(r"\b(?:reinforce|reinforces|reinforced)\s*$", re.I),
    re.compile(
        r"\b(?:admit|admits|admitted|concede|concedes|conceded|identify|identifies|identified|"
        r"permit|permits|permitted|reveal|reveals|revealed|say|says|said)\s*$",
        re.I,
    ),
    re.compile(r"\b(?:has|have|had)\s+sided\s*$", re.I),
    re.compile(r"\bin\s+the\s+same\s+way\s*$", re.I),
    re.compile(r"\b(?:mainly|partly|primarily)\s*$", re.I),
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
    "导致",
    "规定",
    "可能导致",
    "否决",
    "认为，",
    "认为。",
)
# Single-character Chinese function words need a boundary check.  A plain
# ``text.endswith("为")`` incorrectly rejects complete words such as ``行为``
# and ``作为``.  Keep the multi-character endings above literal, and only
# treat a standalone/preposition-at-a-punctuation-boundary character as an
# incomplete block.
STANDALONE_TRANSLATION_FUNCTION_WORDS = frozenset({"把", "并", "从", "将", "为", "于", "向", "以"})
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
    "意味着",
    "提到",
    "暗示",
    "证实",
    "起到",
    "一个好处",
    "大幅减少了",
)
# These phrase-level endings are checked only as complete phrases (or after a
# punctuation boundary), so a normal noun such as ``出生证明`` is not treated
# as the verb ``证明`` being cut short.
INCOMPLETE_TRANSLATION_EXACT_SUFFIXES = frozenset(
    {"这个事实", "一个事实", "这样一个事实", "一个信息", "一个好处"}
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
    "like ",
    "that feed ",
    "within ",
)
ALLOWED_STANDALONE_MODIFIER_PREFIXES = (
    "for the fact that ",
)
FACT_THAT_PATTERN = re.compile(r"\bfact\s+that\b", re.I)
WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
BOLD_MARKER_PATTERN = re.compile(r"\*\*(.*?)\*\*", re.DOTALL)
COMPLEX_SUBJECT_START_PATTERN = re.compile(
    r"^(?:the\s+)?(?:thought|idea|prospect|possibility|act|process|problem|challenge|task)\b",
    re.I,
)
EMBEDDED_BACKGROUND_PATTERN = re.compile(r"\b(?:as|when|while)\s+\w+", re.I)
MAIN_PREDICATE_START_PATTERN = re.compile(
    r"^(?:was|were|is|are|seems?|seemed|became|becomes|proved|proves|turned)\b",
    re.I,
)
SENTENCE_FINAL_ATTRIBUTION_PATTERN = re.compile(
    r",\s*(?:(?:said|says?|wrote|writes?|reported|reports?|argued|argues?|noted|notes?|"
    r"added|adds?)\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*|according\s+to\b[^,;:!?]*)[.!?]\s*$",
    re.I,
)
ATTRIBUTION_SEGMENT_PATTERN = re.compile(
    r"^(?:(?:said|says?|wrote|writes?|reported|reports?|argued|argues?|noted|notes?|"
    r"added|adds?)\s+.+|according\s+to\b.+)[.!?]?\s*$",
    re.I,
)
COMPLETE_TRAILING_ATTRIBUTION_PATTERN = re.compile(
    r",\s*(?:(?:he|she|they|we|i)|the\s+[A-Za-z][\w.'-]*(?:\s+[A-Za-z][\w.'-]*){0,4}|"
    r"[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,4})\s+"
    r"(?:said|says?|wrote|writes?|reported|reports?|argued|argues?|noted|notes?|added|adds?)$",
    re.I,
)
TRANSLATION_ATTRIBUTION_PATTERN = re.compile(
    r"(?:说|表示|写道|指出|称|报道|认为|补充道|评论道)(?:[，,。.!！？?]|$)"
)
INTERNAL_SENTENCE_BOUNDARY_PATTERN = re.compile(r"[.!?]\s+(?=[A-Z'])")
DIRECT_QUESTION_START_PATTERN = re.compile(
    r"^(?:(?:how(?:\s+(?:much|many|long|far|often|well))?|when|where|why)\s+"
    r"(?:am|are|is|was|were|do|does|did|can|could|may|might|shall|should|will|would)"
    r"|how\s+(?:much|many)\s+of\b[^,;:!?]{1,100}?\b"
    r"(?:am|are|is|was|were|do|does|did|can|could|may|might|shall|should|will|would)"
    r"|what\s+(?:do|does|did|can|could|may|might|shall|should|will|would)"
    r"|what\s+(?:am|are|is|was|were)\s+(?:a|an|the|this|that|these|those|my|our|your|his|her|its|their)"
    r"|which\s+of\s+the\s+following\b[^,;:!?]{1,140}?\b"
    r"(?:am|are|is|was|were|do|does|did|can|could|may|might|shall|should|will|would))\b",
    re.I,
)
LEADING_DEPENDENT_CLAUSE_PATTERN = re.compile(
    r"^(?:although|as|because|even\s+if|if|since|unless|whatever|when|whenever|whereas|whether|while)\b.*?,",
    re.I,
)
INTERNAL_CLAUSE_LINK_PATTERN = re.compile(
    r",\s*(?:and|but|or|as|because|when|whereas|while|which|with)\b",
    re.I,
)
PAIRED_CLAUSE_PATTERN = re.compile(
    r"\b(?:either\b.*\bor\b|not\s+only\b.*\bbut(?:\s+also)?\b|that\s+is\s*[,;:]|in\s+other\s+words\b)",
    re.I,
)
INTERNAL_WHEREAS_CLAUSE_PATTERN = re.compile(
    r"\bwhereas\b[^,;:!?]{3,180},\s*(?:I|you|he|she|it|we|they|there)\b",
    re.I,
)
COORDINATED_PRONOUN_CLAUSE_PATTERN = re.compile(
    r",\s*(?:(?:the\s+)?(?:idea|argument|theory)\s+(?:goes|runs),\s*)?"
    r"and\s+(?:I|you|he|she|it|we|they|there)\b",
    re.I,
)
PARALLEL_PERFECT_OR_PATTERN = re.compile(
    r"\b(?:has|have|had)\s+(?:\w+\s+){0,2}\w+(?:ed|en)\b"
    r"[^.;:!?]{2,100}?\bor\s+(?:\w+ly\s+)?\w+(?:ed|en)\b",
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


def _strip_trailing_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip(".,;:!?，。；：！？、").strip()


def _normalized_segment_text(text: str) -> str:
    return _strip_trailing_punctuation(text).strip("—–-()[]{}\"'“”‘’ ").casefold()


def _is_weak_english_segment(text: str) -> bool:
    return _normalized_segment_text(text) in WEAK_ENGLISH_SEGMENT_EXACTS


def _is_weak_translation_segment(text: str) -> bool:
    return _normalized_segment_text(text) in WEAK_TRANSLATION_SEGMENT_EXACTS


def _has_weak_english_ending(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text).lower()
    # The tokenizer intentionally ignores numerals, so a phrase ending in a
    # year/amount (``to 1990`` or ``to $5,000``) would otherwise look as if it
    # ended with the preposition ``to``.
    if re.search(r"(?:\d|%)$", stripped):
        return False
    words = WORD_PATTERN.findall(stripped)
    if not words:
        return False
    # ``and so`` is a useful discourse beat in this reader; a bare final
    # conjunction or determiner is not.
    if len(words) >= 2 and words[-2:] == ["and", "so"]:
        return False
    if len(words) >= 2 and words[-2:] == ["as", "such"]:
        return False
    if len(words) >= 3 and words[-3:] == ["for", "a", "while"]:
        return False
    if words[-1] == "more" and len(words) >= 2 and words[-2] == "any":
        return False
    return words[-1] in WEAK_ENGLISH_SEGMENT_ENDINGS


def _has_internal_sentence_boundary(text: str) -> bool:
    """Ignore dots inside common abbreviations and quoted material.

    ``U. S.``, ``Dr. Worm`` and ``"I have no idea."`` previously looked like
    multiple source sentences and triggered pointless segmentation retries.
    """
    protected = str(text or "")
    protected = re.sub(
        r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs)\.",
        lambda match: match.group(0).replace(".", "∯"),
        protected,
        flags=re.I,
    )
    protected = re.sub(
        r"\b(?:[A-Z]\.\s*){2,}",
        lambda match: match.group(0).replace(".", "∯"),
        protected,
    )
    protected = re.sub(
        r"\b[A-Z]\.",
        lambda match: match.group(0).replace(".", "∯"),
        protected,
    )
    protected = re.sub(
        r'(["“])([^"”]*?)["”]',
        lambda match: match.group(0).replace(".", "∯").replace("?", "∯").replace("!", "∯"),
        protected,
    )
    return bool(INTERNAL_SENTENCE_BOUNDARY_PATTERN.search(protected))


def _has_weak_translation_ending(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text)
    if not stripped or stripped.endswith(("然而", "从而")):
        return False
    return any(stripped.endswith(item) for item in WEAK_TRANSLATION_SEGMENT_ENDINGS)


def _clear_split_reason(text: str) -> str:
    """Return a conservative reason why a long reading block deserves one retry.

    This deliberately remains advisory. English/Chinese word-order inversion
    can make a single large block the only natural representation, so failure
    to split must never invalidate an otherwise accurate translation.
    """
    stripped = str(text or "").strip()
    word_count = len(WORD_PATTERN.findall(stripped))
    if SENTENCE_FINAL_ATTRIBUTION_PATTERN.search(stripped):
        return "attribution"
    if _has_internal_sentence_boundary(stripped):
        return "multiple_sentences"
    if word_count >= 14 and FACT_THAT_PATTERN.search(stripped) and "," in stripped:
        return "fact_that_sentence"
    # A colon/semicolon normally separates a lead-in from its result or
    # explanation.  Even a 16-word sentence can benefit from that beat.
    if word_count >= 16:
        punctuation_positions = [stripped.rfind(mark) for mark in (":", ";")]
        last_explanation_mark = max(punctuation_positions)
        if last_explanation_mark >= 0 and WORD_PATTERN.search(stripped[last_explanation_mark + 1 :]):
            return "colon_or_semicolon"
    if word_count >= 14 and re.search(
        r"[—–]\s*(?:in\s+part|partly|because|namely|that\s+is)\b",
        stripped,
        re.I,
    ):
        return "dash_explanation"
    # A short source-initial time/place frame normally remains initial in
    # Chinese too, so it is a particularly safe reading beat.  Restrict this
    # to explicit temporal/location forms rather than discourse markers such
    # as ``In all,`` or ``However,``.
    if word_count >= 22 and re.match(
        r"^(?:(?:last|next|this)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
        r"week|month|year)|on\s+[^,]{1,50}|during\s+[^,]{1,70}|from\s+[^,]{1,70}|"
        r"in\s+(?:the\s+)?(?:early|late|mid-|\d{3,4})[^,]{0,60}),",
        stripped,
        re.I,
    ):
        return "opening_context"
    # Paired dashes enclosing a parenthetical inside a long sentence expose
    # at least two reliable layers; a single giant block hides both of them.
    if word_count >= 20 and len(re.findall(r"[—–]", stripped)) >= 2:
        return "dash_parenthetical"
    dependent_match = LEADING_DEPENDENT_CLAUSE_PATTERN.search(stripped)
    if (
        dependent_match
        and word_count >= 16
        and len(WORD_PATTERN.findall(stripped[dependent_match.end() :])) >= 3
    ):
        return "dependent_then_main"
    if PAIRED_CLAUSE_PATTERN.search(stripped) and word_count >= 16:
        return "paired_clause"
    if word_count >= 20 and INTERNAL_WHEREAS_CLAUSE_PATTERN.search(stripped):
        return "contrast_clause"
    if word_count >= 20 and COORDINATED_PRONOUN_CLAUSE_PATTERN.search(stripped):
        return "coordinated_clause"
    if word_count >= 24 and re.search(r"\b(?:more|less)\s+than\b", stripped, re.I) and re.search(
        r"\b(?:and|or)\b",
        stripped,
        re.I,
    ):
        return "comparison_chain"
    if word_count >= 20 and re.search(
        r"\bto\s+(?:change|create|develop|ensure|help|make|provide|reduce|support)\b.*\b(?:that|which|who)\b",
        stripped,
        re.I,
    ):
        return "purpose_relative_chain"
    # A generic ``or`` usually joins nouns, adjectives or alternatives inside
    # one clause.  Only flag the measured finite-predicate shape (for example
    # ``has thrived ... or financed ...``); broad matching caused many false
    # retries for ``U.S. users`` and ``well or very well``.
    if word_count >= 14 and PARALLEL_PERFECT_OR_PATTERN.search(stripped):
        return "parallel_or"
    if word_count < 18:
        return ""
    if word_count >= 28 and len(INTERNAL_CLAUSE_LINK_PATTERN.findall(stripped)) >= 2:
        return "clause_chain"
    return ""


def _source_words_for_coverage(text: str) -> list[str]:
    """Tokenize source text after removing display-only focus markers.

    Markers can appear inside a hyphenated word (``non-**committal**``), where
    tokenizing the raw display string incorrectly turns one source word into two.
    """
    normalized = BOLD_MARKER_PATTERN.sub(r"\1", str(text or ""))
    return [word.casefold() for word in WORD_PATTERN.findall(normalized)]


def _has_incomplete_english_suffix(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text)
    # ``..., he said.`` is a complete sentence-final attribution.  The same
    # final verb without a preceding speaker (``..., wrote / Chief Justice``)
    # remains incomplete and is handled below/by the boundary-pair check.
    if COMPLETE_TRAILING_ATTRIBUTION_PATTERN.search(stripped):
        return False
    lowered = f" {stripped.lower()}"
    if stripped.lower() in INCOMPLETE_ENGLISH_SEGMENT_EXACTS:
        return True
    if any(lowered.endswith(suffix) for suffix in INCOMPLETE_ENGLISH_SEGMENT_SUFFIXES):
        return True
    return any(pattern.search(stripped) for pattern in INCOMPLETE_ENGLISH_SEGMENT_PATTERNS)


def _has_incomplete_translation_suffix(text: str) -> bool:
    stripped = _strip_trailing_punctuation(text)
    if stripped in INCOMPLETE_TRANSLATION_EXACT_SUFFIXES:
        return True
    # A phrase immediately following a colon/comma is often intentionally
    # split as a lead-in (for example ``这个事实：``), while the same noun at
    # the end of a complete phrase should remain valid.
    if any(
        re.search(rf"(?:^|[，,；;：:]){re.escape(suffix)}$", stripped)
        for suffix in INCOMPLETE_TRANSLATION_EXACT_SUFFIXES
    ):
        return True
    return any(stripped.endswith(suffix) for suffix in INCOMPLETE_TRANSLATION_SEGMENT_SUFFIXES)


def _has_bad_translation_segment_suffix(text: str) -> bool:
    """Detect a Chinese block ending before its required complement.

    Multi-character endings are safe to match literally.  For one-character
    prepositions, require either an exact one-word block or a punctuation
    boundary before the character; otherwise complete words like ``行为`` would
    be treated as if they ended with the preposition ``为``.
    """
    stripped = _strip_trailing_punctuation(text)
    if any(stripped.endswith(suffix) for suffix in BAD_TRANSLATION_SEGMENT_SUFFIXES):
        return True
    if stripped in STANDALONE_TRANSLATION_FUNCTION_WORDS:
        return True
    return bool(re.search(r"(?:^|[，,；;：:])(?:把|并|从|将|为|于|向|以)$", stripped))


def _has_bad_short_modifier_segment_suffix(text: str) -> bool:
    """Reject only genuinely isolated Chinese modifier fragments.

    Historical examples such as ``在他解放的地区。`` are short dangling
    modifiers.  Matching every sentence that happens to end in ``地区`` also
    rejects complete clauses such as ``适用于亚洲其他地区`` and forces the
    pipeline back to one block.
    """
    stripped = _strip_trailing_punctuation(text)
    compact = re.sub(r"\s+", "", stripped)
    if len(compact) > 16:
        return False
    endings = tuple(_strip_trailing_punctuation(item) for item in BAD_MULTI_TRANSLATION_SEGMENT_SUFFIXES)
    return any(stripped.endswith(item) for item in endings)


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


def _splits_dependent_subject_from_predicate(segment: str, next_segment: str) -> bool:
    """Catch cuts such as ``before the casino / sent him ...``.

    The first block has opened a dependent clause and supplied only its
    subject; the following finite verb is required before the reader has a
    usable pause.
    """
    left = _strip_trailing_punctuation(segment)
    right = _strip_trailing_punctuation(next_segment)
    if not re.search(
        r"\b(?:after|although|because|before|if|since|unless|when|while|with)\s+"
        r"(?:(?:a|an|the|this|that|these|those|his|her|their|our|your|my)\s+)?"
        r"(?:[A-Za-z][\w'-]*\s+){0,5}[A-Za-z][\w'-]*$",
        left,
        flags=re.I,
    ):
        return False
    first = (WORD_PATTERN.findall(right) or [""])[0].lower()
    finite_starts = {
        "am", "are", "became", "began", "brought", "came", "can", "could", "did", "does",
        "fell", "found", "got", "grew", "had", "has", "have", "is", "left", "made", "may",
        "might", "must", "occur", "occurs", "rise", "rises", "rose", "said", "sent", "should",
        "spread", "spreads", "take", "takes", "took", "was", "were", "will", "would", "went",
    }
    # A bare ``-ing`` form cannot be the finite predicate required after this
    # subject. Treating it as one caused false positives for complete clauses
    # followed by ``including``/``according`` and for parallel gerunds.
    return first in finite_starts or first.endswith("ed")


def _splits_numbered_pair_or_range(segment: str, next_segment: str) -> bool:
    left = _strip_trailing_punctuation(segment)
    right = _strip_trailing_punctuation(next_segment)
    if re.search(r"\b(?:paragraphs?|chapters?|sections?|figures?|tables?)\s+\d+$", left, re.I):
        return bool(re.match(r"^(?:and|or|to)\s+\d+\b", right, re.I))
    if re.search(r"\b(?:from|between)\s+\d+$", left, re.I):
        return bool(re.match(r"^(?:and|to)\s+\d+\b", right, re.I))
    return False


def _splits_short_subject_from_predicate(segment: str, next_segment: str) -> bool:
    """Reject a small noun/pronoun subject stranded before its finite verb.

    Long completed subjects are useful study beats (notably the corpus's
    ``either A or B / results ...`` sentence), so this is intentionally capped
    rather than treating every subject/predicate boundary as invalid.
    """
    left = _strip_trailing_punctuation(segment)
    right_words = WORD_PATTERN.findall(_strip_trailing_punctuation(next_segment))
    left_words = WORD_PATTERN.findall(left)
    if not left_words or not right_words:
        return False
    # ``29 / have casinos`` is a numeric subject followed by its predicate;
    # WORD_PATTERN intentionally omits that number, so inspect the raw block.
    if re.match(r"^[\d$£€]", _strip_trailing_punctuation(next_segment)):
        return False
    first = right_words[0].casefold()
    predicate_starts = {
        "am", "are", "aren't", "became", "becomes", "began", "begins", "can", "cannot", "can't",
        "could", "did", "does", "doesn't", "had", "has", "have", "is", "isn't", "may", "might",
        "must", "should", "was", "wasn't", "were", "weren't", "will", "would",
        "acknowledges", "admitted", "consolidated", "indicates", "means", "rely", "relies",
        "rests", "suggests", "remain", "remains", "remained",
    }
    if first not in predicate_starts:
        return False
    # Up to eight words is still a short/simple subject for this reader.  A
    # genuinely useful subject-only beat is a longer or structurally complex
    # phrase (for example the full ``either A or B`` subject).
    # An opening/background clause may make the whole left block look long
    # while still stranding a tiny main-clause subject at its end:
    # ``whatever ..., those differences / are`` or ``Pushed by ..., society / is``.
    leading_background = re.match(
        r"^(?:although|as|because|before|despite|even\s+if|given|if|known|named|pushed|"
        r"since|unless|whatever|when|whenever|whereas|while)\b",
        left,
        re.I,
    )
    if leading_background and "," in left:
        tail_words = WORD_PATTERN.findall(left.rsplit(",", 1)[-1])
        if 0 < len(tail_words) <= 8:
            return True

    # The same problem occurs inside a that-clause, as in ``the text suggests
    # that immigrants now in the U.S. / are ...``.  Do not classify a tail
    # that already contains an auxiliary/finite verb as a stranded subject.
    that_match = re.search(
        r"\b(?:argues?|claims?|fears?|finds?|indicates?|notes?|reports?|reveals?|says?|shows?|suggests?|"
        r"the\s+(?:assumption|fact))\s+that\s+(.+)$",
        left,
        re.I,
    )
    if that_match:
        tail_words = WORD_PATTERN.findall(that_match.group(1))
        finite_inside = {
            "am", "are", "became", "can", "could", "did", "does", "had", "has", "have",
            "is", "may", "might", "must", "should", "was", "were", "will", "would",
        }
        if (
            0 < len(tail_words) <= 10
            and not any(
                word.casefold() in finite_inside
                or (word.casefold().endswith("ed") and not word[0].isupper())
                for word in tail_words
            )
        ):
            return True

    # Inversion still needs its finite verb in the same reading action.
    if re.match(r"^at\s+issue\b", left, re.I):
        return True
    if left.count(",") >= 2:
        return False
    if re.match(r"^[A-Za-z][\w'-]*ing\b", left, re.I) and re.search(r"\bby\b", left, re.I):
        return False
    if "(" in left and ")" in left:
        return False
    return len(left_words) <= 8


def _splits_required_cross_boundary_phrase(segment: str, next_segment: str) -> bool:
    left = _strip_trailing_punctuation(segment)
    right = _strip_trailing_punctuation(next_segment)
    pairs = (
        (r"\bapproval$", r"^to\b"),
        (r"\banswer$", r"^(?:a|an|the|these|those|questions?|queries?)\b"),
        (r"\bit(?:'s|\s+is)\s+not\s+obvious$", r"^(?:how|whether|why|that)\b"),
        (r"\b(?:assumption|alternative|doubt)$", r"^(?:that|of)\b"),
        (r"\bmiddle\s+class$", r"^famil(?:y|ies)\b"),
        (r"\b(?:a|the|this|that)\s+fact$", r"^that\b"),
        (r"\bacceleration$", r"^of\b"),
        (r"\btoo\s+(?:[A-Za-z][\w'-]*ly\s+)?[A-Za-z][\w'-]*$", r"^to\b"),
        (r"\bstruck$", r"^(?:a|an|the|fear|terror)\b"),
        (r"\bneed\s+for\b[^.;:!?]{1,100}$", r"^to\b"),
        (r"\bend$", r"^(?:a|an|any|all|the|this|that|these|those)\b"),
        (r"\bought$", r"^(?:not\b|to\b)"),
        (r"\bat\s+a\s+time$", r"^when\b"),
        (r"\bfirst$", r"^by\b"),
        (r"\bin\s+the\s+same\s+way$", r"^(?:that|as)\b"),
        (r"\bpartly$", r"^because\b"),
    )
    return any(re.search(left_pattern, left, re.I) and re.search(right_pattern, right, re.I) for left_pattern, right_pattern in pairs)


def _splits_copula_or_auxiliary_from_complement(segment: str, next_segment: str) -> bool:
    """Reject ``is / a matter`` and ``were / captured`` style cuts.

    A form of *be* at the right edge normally still needs its predicative
    complement or participle.  ``That is, / ...`` is a discourse marker, and
    a completed sentence followed by a new one is not such a split.
    """
    raw_left = str(segment or "").strip()
    if re.search(r"[.!?]\s*[\"'”’)]?$", raw_left):
        return False
    left = _strip_trailing_punctuation(raw_left)
    right = _strip_trailing_punctuation(next_segment)
    if re.fullmatch(r"that\s+is(?:\s+to\s+say)?", left, re.I):
        return False
    left_words = WORD_PATTERN.findall(left)
    if not left_words or left_words[-1].casefold() not in {
        "am", "are", "is", "was", "were", "be", "been", "being",
        "can", "could", "may", "might", "must", "shall", "should", "will", "would", "do", "does", "did",
    }:
        return False
    if re.match(r"^(?:and|but|or|nor|so|yet)\b", right, re.I):
        return False
    return bool(WORD_PATTERN.search(right))


def _splits_short_direct_quote(segment: str, next_segment: str) -> bool:
    left = str(segment or "").strip()
    right = str(next_segment or "").strip()
    if not re.search(r"\b(?:say|says|said|saying|write|writes|wrote|writing)\s*[:：]?\s*[\"“]$", left, re.I):
        return False
    return len(WORD_PATTERN.findall(right)) <= 16 and bool(re.search(r"[\"”]", right))


def _splits_attribution_verb_from_speaker(segment: str, next_segment: str) -> bool:
    left = _strip_trailing_punctuation(segment)
    right = _strip_trailing_punctuation(next_segment)
    if COMPLETE_TRAILING_ATTRIBUTION_PATTERN.search(left):
        return False
    return bool(
        re.search(
            r"\b(?:said|says?|wrote|writes?|reported|reports?|argued|argues?|noted|notes?)$",
            left,
            re.I,
        )
        and re.match(r"^(?:Mr|Mrs|Ms|Dr|Chief|Judge|Professor|[A-Z][\w.'-]+)\b", right)
    )


def _bad_trailing_modifier_pair(source_segment: str, translation_segment: str) -> bool:
    source = _strip_trailing_punctuation(source_segment)
    target = str(translation_segment or "").strip()
    if not re.match(r"^(?:after|before|during)\b", source, re.I):
        return False
    return bool(re.match(r"^(?:在|经过|于|当)", target) and re.search(r"[。.!！？?]\s*[”\"]?$", target))


def _translation_content_counter(text: str) -> Counter[str]:
    content = "".join(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", str(text or ""))).casefold()
    return Counter(content)


TEMPORAL_ALIGNMENT_MARKERS = (
    (re.compile(r"\bfor\s+a\s+year\b", re.I), ("一年", "一年中", "一年内")),
    (re.compile(r"\bover\s+nearly\s+two\s+decades\b", re.I), ("近二十年", "将近二十年")),
)


def _temporal_meaning_moved_to_earlier_block(
    sentence_segments: list[Any],
    translation_segments: list[Any],
) -> bool:
    if len(sentence_segments) != len(translation_segments):
        return False
    for index, source_segment in enumerate(sentence_segments):
        if index == 0:
            continue
        source = str(source_segment or "")
        for pattern, markers in TEMPORAL_ALIGNMENT_MARKERS:
            if not pattern.search(source):
                continue
            current = str(translation_segments[index] or "")
            if any(marker in current for marker in markers):
                continue
            earlier = "".join(str(item or "") for item in translation_segments[:index])
            if any(marker in earlier for marker in markers):
                return True
    return False


def segmentation_advisory_issues(result: dict[str, Any], *, source_text: str = "") -> list[str]:
    """Report likely over-compressed reading blocks without rejecting them.

    The model gets one retry when a clear semantic progression is hidden in a
    long block.  These are intentionally *soft* signals: a fragment or a
    Chinese word-order inversion may quite legitimately need one block.
    """
    sentence_segments = result.get("sentence_segments") if isinstance(result.get("sentence_segments"), list) else []
    translation_segments = result.get("translation_segments") if isinstance(result.get("translation_segments"), list) else []
    if not sentence_segments or len(sentence_segments) != len(translation_segments):
        return []
    issues: list[str] = []
    for index, segment in enumerate(sentence_segments):
        reason = _clear_split_reason(str(segment or ""))
        # Once a paired either/or or not-only/but subject has already been
        # separated from its shared predicate, splitting its two alternatives
        # again usually makes both chunks worse.
        if reason and not (
            reason in {"paired_clause", "comparison_chain"}
            and len(sentence_segments) > 1
        ) and not (
            reason == "dependent_then_main"
            and index < len(sentence_segments) - 1
        ):
            issues.append(f"undersegmented_{reason}:{str(segment or '')[:40]}")
        if index < len(sentence_segments) - 1 and _is_undersegmented_subject_background(
            str(segment or ""),
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"undersegmented_subject_background:{str(segment or '')[:40]}")
    return issues


def translation_result_issues(result: dict[str, Any], words: list[str], *, source_text: str = "") -> list[str]:
    issues: list[str] = []
    sentence = str(result.get("sentence_translation") or "").strip()
    source_lower = str(source_text or "").casefold()
    if not sentence:
        issues.append("empty_sentence_translation")
    if any(marker in sentence for marker in BAD_SENTENCE_MARKERS):
        issues.append("segmented_sentence_translation")
    if "/" in sentence and "/" not in str(source_text or ""):
        issues.append("sentence_translation_slash")
    for marker in BAD_LITERAL_TRANSLATION_SUBSTRINGS:
        if marker in sentence:
            issues.append(f"literal_translation:{marker}")
    if re.match(r"^而是\s*[，,]", sentence):
        issues.append("literal_translation:sentence_initial_而是")
    if re.search(r"例如.+时[。.!！？?]?$", sentence):
        issues.append("literal_translation:dangling_例如_when")
    if re.search(r"(?:应对|回应)(?:一项)?[“\"]?重要[”\"]?的?政策利益", sentence):
        issues.append("literal_translation:address_policy_interest")
    if re.search(r"降低.{0,30}风险上升", sentence):
        issues.append("literal_translation:lower_risk_increase")
    if re.search(r"\bless of an?\b", source_lower) and re.search(r"(?:不太|更不|不大|较不)(?:可能|会|容易)(?:成为|是|算是)", sentence):
        issues.append("literal_translation:degree_changed_to_probability")
    if "mystery" in source_lower and "surprise to any" in source_lower and re.search(r"(?:任何|所有)[^，。]{0,18}都[^，。]{0,12}(?:惊讶|吃惊|惊奇|意外|诧异)", sentence):
        issues.append("literal_translation:any_under_modal任一老板感到意外就令人不解，不是所有老板都如此")
    if "幸福已婚" in sentence:
        issues.append("literal_translation:marital_modifier_scope")
    if "doing the rounds" in source_lower and "审议" in sentence and not re.search(r"\b(?:debate|deliberation|review|reading)\b", source_lower):
        issues.append("literal_translation:doing_the_rounds仅指流传或传阅，不能增加正式审议程序")
    if re.search(r"\bready for\b", source_lower) and "心理和实际" in sentence and not re.search(r"\b(?:mental|psychological|practical)\b", source_lower):
        issues.append("literal_translation:ready_for保留概括的做好准备，不增加准备种类")
    if re.search(r"\bcould not confide\b", source_lower) and "不愿" in sentence:
        issues.append("literal_translation:could_not_confide表示不能吐露，不是主观不愿")
    if re.search(r"\bfrankly\s+(?:dislike|hate|resent|prefer|love)\b", source_lower) and re.search(r"表示|声称|宣称", sentence) and not re.search(r"\b(?:said|says|stated|declared|expressed)\b", source_lower):
        issues.append("literal_translation:frankly_attitude保留毫不掩饰的态度，不增加发表言论")
    if "cascade" in source_lower and "接连不同" in sentence:
        issues.append("literal_translation:cascade中文需要一连串的等完整数量结构")
    if "painful reminder" in source_lower and "痛苦地提醒" in sentence:
        issues.append("literal_translation:painful_reminder是引起痛苦回忆的提醒，不是某主体以痛苦的方式提醒")
    if "what was once a sovereign nation" in source_lower and re.search(r"(?:他们|她们|人们|居民)曾(?:经)?(?:为|是)(?:一个)?主权国家", sentence):
        issues.append("literal_translation:sovereign_nation指政治或地域实体，不能让人群成为国家")
    if "most recent measures" in source_lower and "最新的大多数" in sentence:
        issues.append("literal_translation:most_recent_scope")
    if re.search(r"\bprais(?:e|ed|es|ing)\s+the\s+uk\s+for\s+its\s+gdp\b", source_lower) and re.search(
        r"赞扬(?:了)?英国的\s*GDP",
        sentence,
        re.I,
    ):
        issues.append("literal_translation:praise_object_scope")
    if (
        "a basis for planning to meet the possibilities" in source_lower
        and re.search(r"环境所带来的(?:各种)?可能性", sentence)
    ):
        issues.append("literal_translation:basis_possibility_scope")

    sentence_segments = result.get("sentence_segments") if isinstance(result.get("sentence_segments"), list) else []
    translation_segments = result.get("translation_segments") if isinstance(result.get("translation_segments"), list) else []
    if not sentence_segments or not translation_segments:
        issues.append("missing_segments")
    elif len(sentence_segments) != len(translation_segments):
        issues.append("segment_count_mismatch")
    if source_text and sentence_segments:
        source_words = _source_words_for_coverage(source_text)
        segmented_words = [
            word.casefold()
            for word in WORD_PATTERN.findall(" ".join(str(item or "") for item in sentence_segments))
        ]
        if source_words != segmented_words:
            issues.append("source_segment_coverage_mismatch")

    # Segmentation is presentation-only: outside the deliberate reordering of
    # a sentence-final attribution, it must not silently paraphrase the locked
    # whole-sentence translation. Character counts ignore punctuation and word
    # order, allowing boundaries to move while still catching added/deleted or
    # synonym-substituted content.
    if (
        sentence
        and len(translation_segments) > 1
        and not SENTENCE_FINAL_ATTRIBUTION_PATTERN.search(str(source_text or "").strip())
        and _translation_content_counter(sentence)
        != _translation_content_counter("".join(str(item or "") for item in translation_segments))
    ):
        issues.append("translation_segment_content_mismatch")
    if _temporal_meaning_moved_to_earlier_block(sentence_segments, translation_segments):
        issues.append("temporal_meaning_moved_to_earlier_translation_segment")

    # Chinese commonly moves a sentence-final ``..., said X`` attribution to
    # the front.  That is fine for the whole translation, but the paired
    # reading blocks must move it back to the final Chinese block so each pair
    # still represents the same source span.
    if (
        source_text
        and len(sentence_segments) > 1
        and len(sentence_segments) == len(translation_segments)
        and SENTENCE_FINAL_ATTRIBUTION_PATTERN.search(str(source_text).strip())
        and (
            ATTRIBUTION_SEGMENT_PATTERN.search(str(sentence_segments[-1]).strip())
            or SENTENCE_FINAL_ATTRIBUTION_PATTERN.search(str(sentence_segments[-1]).strip())
        )
        and not TRANSLATION_ATTRIBUTION_PATTERN.search(str(translation_segments[-1]).strip())
    ):
        issues.append("sentence_final_attribution_missing_from_last_translation_segment")

    # A question mark is part of the meaning, not just typography.  This
    # catches the common failure where an exam-style choice question is
    # silently rewritten as a statement (for example, ``or ... ?``).
    source_stripped = str(source_text or "").strip()
    source_is_question = bool(
        re.search(r"[?？]\s*$", source_stripped)
        or DIRECT_QUESTION_START_PATTERN.search(source_stripped)
    )
    if source_is_question and not re.search(
        r"[?？]\s*$", sentence
    ):
        issues.append("question_translation_missing")

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
        if index < len(sentence_segments) - 1 and _is_weak_english_segment(text):
            issues.append(f"weak_sentence_segment:{text[:30]}")
        if index < len(sentence_segments) - 1 and _has_weak_english_ending(text):
            issues.append(f"weak_sentence_segment_ending:{text[:30]}")
        if index < len(sentence_segments) - 1 and re.search(r"[:;]\s+[A-Za-z].*$", text):
            issues.append(f"cut_after_partial_colon_explanation:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_dependent_subject_from_predicate(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"dependent_subject_split_before_predicate:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_numbered_pair_or_range(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"numbered_pair_split:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_short_subject_from_predicate(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"short_subject_split_before_predicate:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_required_cross_boundary_phrase(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"required_phrase_split:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_copula_or_auxiliary_from_complement(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"copula_or_auxiliary_split:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_short_direct_quote(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"short_direct_quote_split:{text[:30]}")
        if index < len(sentence_segments) - 1 and _splits_attribution_verb_from_speaker(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"attribution_verb_speaker_split:{text[:30]}")
        if index < len(sentence_segments) - 1 and _is_undersegmented_subject_background(
            text,
            str(sentence_segments[index + 1] or ""),
        ):
            issues.append(f"undersegmented_subject_background:{text[:30]}")
        lowered = text.lower()
        previous_ended_sentence = index > 0 and str(sentence_segments[index - 1] or "").strip().endswith((".", "?", "!"))
        allowed_like_comparison = bool(
            lowered.startswith("like ")
            and re.search(
                r",\s*(?:I|you|he|she|it|we|they|there)\s+"
                r"(?:am|are|is|was|were|can|could|may|might|must|shall|should|will|would|do|does|did|has|have|had)\b",
                text,
                re.I,
            )
        )
        allowed_modifier = allowed_like_comparison or any(
            lowered.startswith(prefix) for prefix in ALLOWED_STANDALONE_MODIFIER_PREFIXES
        )
        if (
            index > 0
            and not previous_ended_sentence
            and not allowed_modifier
            and any(lowered.startswith(prefix) for prefix in STANDALONE_MODIFIER_PREFIXES)
        ):
            issues.append(f"standalone_modifier_segment:{text[:30]}")
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
        elif index < len(translation_segments) - 1 and _has_bad_translation_segment_suffix(text):
            issues.append(f"bad_translation_segment_suffix:{text[:20]}")
        elif len(translation_segments) > 1 and _has_bad_short_modifier_segment_suffix(text):
            issues.append(f"bad_translation_segment_suffix:{text[:20]}")
        elif any(item in text for item in BAD_TRANSLATION_SEGMENT_SUBSTRINGS):
            issues.append(f"bad_translation_segment_text:{text[:20]}")
        elif len(translation_segments) > 1 and text.startswith(BAD_MULTI_SEGMENT_TRANSLATION_PREFIXES):
            issues.append(f"bad_translation_segment_prefix:{text[:20]}")
        if index < len(translation_segments) - 1 and _is_weak_translation_segment(text):
            issues.append(f"weak_translation_segment:{text[:20]}")
        if index < len(translation_segments) - 1 and _has_weak_translation_ending(text):
            issues.append(f"weak_translation_segment_ending:{text[:20]}")
        if index < len(translation_segments) - 1 and re.search(r"[。！？!?]\s*$", text):
            corresponding_source = str(sentence_segments[index] or "").strip()
            if not re.search(r"[.!?]\s*$", corresponding_source):
                issues.append(f"translation_segment_ends_sentence_early:{text[:20]}")
        if index < len(translation_segments) - 1 and _has_incomplete_translation_suffix(text):
            issues.append(f"incomplete_translation_segment_suffix:{text[:20]}")
        if index == 0 and text.startswith(REVERSED_JUDGMENT_PREFIXES):
            reversed_judgment_first = True
        if (
            index == len(translation_segments) - 1
            and index > 0
            and index < len(sentence_segments)
            and _bad_trailing_modifier_pair(str(sentence_segments[index] or ""), text)
        ):
            issues.append(f"trailing_modifier_translation_segment:{text[:20]}")

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

    issues.extend(word_translation_issues(result, words, source_text=source_text, sentence_translation=sentence))
    return issues


def word_translation_issues(
    result: dict[str, Any],
    words: list[str],
    *,
    source_text: str = "",
    sentence_translation: str = "",
    require_english_definition: bool = False,
) -> list[str]:
    issues: list[str] = []
    translations = result.get("word_translations") if isinstance(result.get("word_translations"), dict) else {}
    items = {
        str(item.get("word") or ""): item
        for item in (result.get("items") or [])
        if isinstance(item, dict)
    }
    normalized_source = re.sub(r"\[[^\]]*[\u4e00-\u9fff][^\]]*\]", "", source_text)
    normalized_source = re.sub(r"\s+", " ", re.sub(r"\*\*(.*?)\*\*", r"\1", normalized_source)).casefold()
    for word in words:
        text = str(translations.get(word) or "").strip()
        chinese, english_separator, english = text.partition("；英文：")
        if not text:
            issues.append(f"missing_word_translation:{word}")
        elif chinese.count("本义：") != 1 or chinese.count("句中：") != 1:
            issues.append(f"bad_word_translation_format:{word}")
        elif re.search(r"本义：\s*[；;]?\s*句中：|句中：\s*$", chinese):
            issues.append(f"bad_word_translation_format:{word}")
        if require_english_definition and not english_separator:
            issues.append(f"missing_word_english_definition:{word}:请补充简明英文释义")
        if english_separator and (
            len(re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", english)) < 2
            or re.search(r"[\u4e00-\u9fff\r\n]", english)
            or english.strip().strip(".!?").casefold() == word.casefold()
        ):
            issues.append(f"bad_word_english_definition:{word}:请用简单英文解释本句词义，不重复原词或夹带中文")
        if result.get("word_evidence_required"):
            item = items.get(word, {})
            source_quote = re.sub(r"\s+", " ", str(item.get("source_quote") or "")).strip().casefold()
            translation_quote = str(item.get("translation_quote") or "").strip()
            if source_text and (
                not source_quote
                or source_quote not in normalized_source
                or not re.search(r"(?<![a-z])" + re.escape(word.casefold()) + r"(?![a-z])", source_quote)
            ):
                issues.append(f"bad_word_evidence:{word}:source_quote")
            if sentence_translation and (not translation_quote or translation_quote not in sentence_translation):
                issues.append(f"bad_word_evidence:{word}:translation_quote:{translation_quote!r}不是中文定稿的连续原文；请逐字复制，必要时扩大到完整从句")

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
