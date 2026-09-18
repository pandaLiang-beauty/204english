from __future__ import annotations

import re


# Keep in sync with frontend/src/english/splitEnglishSentences.js; both run the
# same passage fixtures so preview selection and backend synchronization agree.
_TITLES = set("mr mrs ms dr prof sr st mt gen gov sen rep capt lt col rev hon".split())
_ABBREVIATIONS = set("jr vs etc e.g i.e a.m p.m ph.d no fig vol pp inc ltd co dept approx est jan feb mar apr jun jul aug sep sept oct nov dec".split())
_SENTENCE_STARTS = set("The This That These Those It He She They We I You However But Yet Meanwhile Next Then A An In On At After Before When While Why How What Where Who Which There Here As For To By Our Their Its His Her All Some Many Most Not No Both Each Such".split())
_TERMINAL = set(".!?。！？")
_CLOSERS = set("\"'’”）)]}»")


def _internal_period(text: str, index: int) -> bool:
    before = text[:index].replace("**", "")
    after = text[index + 1:].replace("**", "")
    if re.match(r"[0-9]", after):
        return True
    if re.search(r"[A-Za-z0-9]$", before) and re.match(r"[A-Za-z0-9]", after):
        return True
    token_match = re.search(r"[A-Za-z][A-Za-z.]*$", before)
    token = token_match.group(0) if token_match else ""
    next_match = re.match(r"[A-Za-z0-9]+", after.lstrip(" \t\n\"'’”）)]}»"))
    if not next_match:
        return False
    next_word = next_match.group(0)
    if token.lower() in _TITLES:
        return True
    abbreviated = token.lower() in _ABBREVIATIONS or bool(re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", token))
    initial = bool(re.fullmatch(r"[A-Z]", token) and re.match(r"[A-Z]", next_word))
    return (abbreviated or initial) and next_word not in _SENTENCE_STARTS


def split_marked_passage_sentences(value: str) -> list[str]:
    source = re.sub(r"\r\n?", "\n", str(value or "")).strip()
    chunks = []
    for paragraph in re.split(r"\n\s*\n", source):
        text = re.sub(r"\s+", " ", paragraph).strip()
        start = index = 0
        bold = False
        while index < len(text):
            if text[index:index + 2] == "**":
                bold = not bold
                index += 2
                continue
            if text[index] not in _TERMINAL or (text[index] == "." and _internal_period(text, index)):
                index += 1
                continue
            end = index + 1
            while end < len(text) and text[end] in _TERMINAL:
                end += 1
            closes_quote = closes_bold = False
            while end < len(text):
                if text[end] in _CLOSERS:
                    closes_quote = True
                    end += 1
                elif bold and not closes_bold and text[end:end + 2] == "**":
                    closes_bold = True
                    end += 2
                else:
                    break
            continuation = re.sub(r"^\*\*", "", text[end:].lstrip())
            ellipsis = text[index:end].startswith("..")
            if bold and not closes_bold:
                index += 1
                continue
            if (closes_quote or ellipsis) and re.match(r"[a-z]", continuation):
                if closes_bold:
                    bold = False
                index = end
                continue
            sentence = text[start:end].strip()
            if sentence:
                chunks.append(sentence)
            if closes_bold:
                bold = False
            start = index = end
        remainder = text[start:].strip()
        if remainder:
            chunks.append(remainder)
    return chunks
