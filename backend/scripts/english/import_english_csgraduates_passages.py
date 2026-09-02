from __future__ import annotations

"""Import public kaoyan English passages published as HTML pages.

The source pages contain the original paper, answer widgets, and detailed
explanations in one document.  This importer reads only the original-paper
blocks, stopping before the first question widget and ignoring all answer and
explanation containers.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.schema import initialize_schema as initialize_english_schema  # noqa: E402
from app.platform.db import get_connection, initialize_database  # noqa: E402


SITE_ORIGIN = "https://www.csgraduates.com"
PUBLIC_SOURCE_LABEL = "计算机考研杂货铺公开真题网页"
DEFAULT_YEAR_START = 2010
DEFAULT_YEAR_END = 2019
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
EXAM_TYPES = {
    "english1": ("english1", "英语一"),
    "english2": ("english2", "英语二"),
}


@dataclass(frozen=True)
class ExtractedPassage:
    title: str
    source_url: str
    year: int
    exam_type: str
    passage_type: str
    body_text: str
    text_index: int
    subtype: str = ""


@dataclass(frozen=True)
class HtmlBlock:
    tag: str
    text: str


class PaperPageParser(HTMLParser):
    """Capture visible heading and paragraph blocks from the page's main area."""

    _BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "p"}
    _EXCLUDED_CLASSES = {"choice-container", "answer-container", "solution-detail"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[HtmlBlock] = []
        self._in_main = False
        self._ignored_div_depth = 0
        self._current: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "main":
            self._in_main = True
            return
        if not self._in_main:
            return
        if self._ignored_div_depth:
            if tag == "div":
                self._ignored_div_depth += 1
            return
        if tag == "div":
            classes = set(str(attr_map.get("class") or "").split())
            if classes & self._EXCLUDED_CLASSES:
                self._ignored_div_depth = 1
                return
        if tag in self._BLOCK_TAGS:
            self._current.append((tag, []))
        elif tag == "br" and self._current:
            self._current[-1][1].append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_main and not self._ignored_div_depth and tag == "br" and self._current:
            self._current[-1][1].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "main":
            self._in_main = False
            self._ignored_div_depth = 0
            return
        if not self._in_main:
            return
        if self._ignored_div_depth:
            if tag == "div":
                self._ignored_div_depth -= 1
            return
        if tag in self._BLOCK_TAGS and self._current:
            current_tag, content = self._current[-1]
            if current_tag != tag:
                return
            self._current.pop()
            text = _clean_text("".join(content))
            if text:
                self.blocks.append(HtmlBlock(tag=tag, text=text))

    def handle_data(self, data: str) -> None:
        if self._in_main and not self._ignored_div_depth and self._current:
            self._current[-1][1].append(data)


def _clean_text(value: str) -> str:
    text = str(value or "").replace("\u200b", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fetch_text(url: str, *, timeout: int = 30) -> str:
    # These are public pages; ignore environment proxy configuration so the
    # importer has one predictable direct-fetch path.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _page_url(exam_type: str, year: int) -> str:
    return f"{SITE_ORIGIN}/study_methods/english/{exam_type}/{year}/"


def _heading_index(blocks: list[HtmlBlock], pattern: str, start: int = 0) -> int | None:
    matcher = re.compile(pattern, flags=re.IGNORECASE)
    for index in range(start, len(blocks)):
        if blocks[index].tag in {"h2", "h3", "h4", "h5"} and matcher.fullmatch(blocks[index].text.strip()):
            return index
    return None


def _first_index(
    blocks: list[HtmlBlock],
    predicates: list,
    *,
    start: int,
    default: int | None = None,
) -> int:
    for index in range(start, len(blocks)):
        if any(predicate(blocks[index]) for predicate in predicates):
            return index
    return len(blocks) if default is None else default


def _paragraphs(blocks: list[HtmlBlock], start: int, end: int) -> str:
    paragraphs = [block.text for block in blocks[start:end] if block.tag == "p" and block.text]
    return "\n\n".join(paragraphs).strip()


def _after_question_heading(blocks: list[HtmlBlock], start: int, end: int) -> int:
    """Skip directions and begin at the question-number heading when present."""
    for index in range(start, end):
        block = blocks[index]
        if block.tag == "h5" and re.fullmatch(r"\d+(?:-\d+)?", block.text):
            return index + 1
    return start


def _reading_b_subtype(body_text: str) -> tuple[str, str]:
    normalized = body_text.lower()
    if "wrong order" in normalized or "reorganize" in normalized:
        return "paragraph_reorder", "段落排序"
    if "removed" in normalized or "fit into each of the numbered blanks" in normalized:
        return "sentence_restore", "句子还原"
    if "left column" in normalized or "corresponding information" in normalized:
        return "information_match", "信息匹配"
    if "true or false" in normalized:
        return "true_false", "正误判断"
    if "subheading" in normalized:
        return "subheading_match", "标题匹配"
    return "reading_b", "新题型"


def _valid_body(body_text: str) -> bool:
    if len(body_text) < 250:
        return False
    forbidden = ("正确答案", "查看答案与解析", "精解", "难点解析")
    return not any(marker in body_text for marker in forbidden)


def extract_passages(*, html: str, year: int, exam_type: str, page_url: str) -> list[ExtractedPassage]:
    parser = PaperPageParser()
    parser.feed(html)
    parser.close()
    blocks = parser.blocks
    _, exam_label = EXAM_TYPES[exam_type]
    passages: list[ExtractedPassage] = []

    def add(
        passage_type: str,
        body_text: str,
        text_index: int,
        source_anchor: str,
        title: str,
        subtype: str = "",
    ) -> None:
        if not _valid_body(body_text):
            return
        passages.append(
            ExtractedPassage(
                title=title,
                source_url=f"{page_url}#{source_anchor}",
                year=year,
                exam_type=exam_type,
                passage_type=passage_type,
                body_text=body_text,
                text_index=text_index,
                subtype=subtype,
            )
        )

    cloze_heading = _heading_index(blocks, r"完形填空")
    if cloze_heading is not None:
        cloze_text_heading = _heading_index(blocks, r"Text", cloze_heading + 1)
        if cloze_text_heading is not None:
            cloze_end = _first_index(
                blocks,
                [
                    lambda block: block.tag == "h5" and re.fullmatch(r"\d+", block.text),
                    lambda block: block.tag in {"h2", "h3"} and block.text == "阅读理解",
                ],
                start=cloze_text_heading + 1,
            )
            add(
                "cloze",
                _paragraphs(blocks, cloze_text_heading + 1, cloze_end),
                0,
                "cloze",
                f"{year}年考研{exam_label} 完形填空",
                "use_of_english",
            )

    reading_heading = _heading_index(blocks, r"阅读理解")
    if reading_heading is not None:
        for text_index in range(1, 5):
            text_heading = _heading_index(blocks, rf"Text\s*{text_index}", reading_heading + 1)
            if text_heading is None:
                continue
            text_end = _first_index(
                blocks,
                [
                    lambda block: block.tag == "h5" and re.fullmatch(r"\d+(?:-\d+)?", block.text),
                    lambda block: block.tag == "h4" and bool(re.fullmatch(r"Text\s*[1-4]", block.text, flags=re.I)),
                    lambda block: block.tag == "h4" and re.fullmatch(r"Part\s+B", block.text, flags=re.I) is not None,
                ],
                start=text_heading + 1,
            )
            add(
                "reading_a",
                _paragraphs(blocks, text_heading + 1, text_end),
                text_index,
                f"text-{text_index}",
                f"{year}年考研{exam_label} Text {text_index}",
                f"text_{text_index}",
            )

        part_b = _heading_index(blocks, r"Part\s+B", reading_heading + 1)
        if part_b is not None:
            part_b_end = _first_index(
                blocks,
                [
                    lambda block: block.tag == "h4" and re.fullmatch(r"Part\s+C", block.text, flags=re.I) is not None,
                    lambda block: block.tag in {"h2", "h3"} and block.text == "写作",
                ],
                start=part_b + 1,
            )
            body_start = _after_question_heading(blocks, part_b + 1, part_b_end)
            body_text = _paragraphs(blocks, body_start, part_b_end)
            subtype, subtype_label = _reading_b_subtype(_paragraphs(blocks, part_b + 1, part_b_end))
            add(
                "reading_b",
                body_text,
                5,
                "part-b",
                f"{year}年考研{exam_label} 新题型（{subtype_label}）",
                subtype,
            )

        part_c = _heading_index(blocks, r"Part\s+C", reading_heading + 1)
        if part_c is not None:
            translation_end = _first_index(
                blocks,
                [lambda block: block.tag in {"h2", "h3"} and block.text == "写作"],
                start=part_c + 1,
            )
            add(
                "translation",
                _paragraphs(
                    blocks,
                    _after_question_heading(blocks, part_c + 1, translation_end),
                    translation_end,
                ),
                6,
                "translation",
                f"{year}年考研{exam_label} 翻译材料",
                "translation",
            )
    return passages


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_user_id(username: str) -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ? LIMIT 1", (username,)).fetchone()
    if not row:
        raise ValueError(f"user not found: {username}")
    return int(row["id"])


def _upsert_passage(passage: ExtractedPassage, *, user_id: int, dry_run: bool) -> str:
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id FROM english_passages
            WHERE user_id = ? AND source_url = ?
            LIMIT 1
            """,
            (user_id, passage.source_url),
        ).fetchone()
        if existing:
            return "skipped"
        if dry_run:
            return "would_insert"
        now = _now()
        intensive_json = json.dumps({"source_subtype": passage.subtype}, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO english_passages(
                user_id, title, source_label, source_url, year, exam_type,
                passage_type, body_text, status, intensive_json, selected_sentence_ids_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, '[]', ?, ?)
            """,
            (
                user_id,
                passage.title,
                PUBLIC_SOURCE_LABEL,
                passage.source_url,
                passage.year,
                passage.exam_type,
                passage.passage_type,
                passage.body_text,
                intensive_json,
                now,
                now,
            ),
        )
    return "inserted"


def _parse_exam_types(raw_value: str) -> list[str]:
    aliases = {
        "1": "english1",
        "01": "english1",
        "english1": "english1",
        "英一": "english1",
        "英语一": "english1",
        "2": "english2",
        "02": "english2",
        "english2": "english2",
        "英二": "english2",
        "英语二": "english2",
    }
    result: list[str] = []
    for part in re.split(r"[,，\s]+", raw_value.strip()):
        if not part:
            continue
        exam_type = aliases.get(part.lower(), aliases.get(part))
        if not exam_type:
            raise ValueError(f"unsupported exam type: {part}")
        if exam_type not in result:
            result.append(exam_type)
    return result or ["english1", "english2"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import kaoyan English passages from csgraduates.com HTML pages."
    )
    parser.add_argument("--username", default="admin", help="target user for english_passages")
    parser.add_argument("--year-start", type=int, default=DEFAULT_YEAR_START)
    parser.add_argument("--year-end", type=int, default=DEFAULT_YEAR_END)
    parser.add_argument("--exam-types", default="english1,english2", help="english1/english2, 英一/英二")
    parser.add_argument("--dry-run", action="store_true", help="fetch and extract but do not write passage rows")
    parser.add_argument("--limit-papers", type=int, default=0)
    parser.add_argument("--print-samples", action="store_true", help="include a short sample for every extracted passage")
    args = parser.parse_args()

    if args.year_start > args.year_end:
        parser.error("--year-start must not exceed --year-end")

    initialize_database()
    initialize_english_schema()
    user_id = _get_user_id(args.username)
    exam_types = _parse_exam_types(args.exam_types)
    targets = [(year, exam_type) for year in range(args.year_start, args.year_end + 1) for exam_type in exam_types]
    if args.limit_papers > 0:
        targets = targets[: args.limit_papers]

    summary: dict[str, Any] = {
        "papers_requested": len(targets),
        "papers_processed": 0,
        "passages_extracted": 0,
        "inserted": 0,
        "skipped": 0,
        "would_insert": 0,
        "by_type": {},
        "errors": [],
    }
    samples: list[dict[str, Any]] = []
    for year, exam_type in targets:
        page_url = _page_url(exam_type, year)
        try:
            passages = extract_passages(
                html=_fetch_text(page_url), year=year, exam_type=exam_type, page_url=page_url
            )
            expected_types = {"cloze", "reading_a", "reading_b", "translation"}
            found_types = {passage.passage_type for passage in passages}
            missing_types = expected_types - found_types
            if len([passage for passage in passages if passage.passage_type == "reading_a"]) != 4:
                missing_types.add("reading_a_texts")
            if missing_types:
                raise ValueError(f"incomplete extraction: missing {', '.join(sorted(missing_types))}")
            summary["papers_processed"] += 1
            for passage in passages:
                outcome = _upsert_passage(passage, user_id=user_id, dry_run=args.dry_run)
                summary["passages_extracted"] += 1
                summary[outcome] = int(summary.get(outcome, 0)) + 1
                by_type = summary["by_type"]
                by_type[passage.passage_type] = int(by_type.get(passage.passage_type, 0)) + 1
                if args.print_samples:
                    samples.append(
                        {
                            "title": passage.title,
                            "type": passage.passage_type,
                            "characters": len(passage.body_text),
                            "sample": passage.body_text[:180],
                        }
                    )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            summary["errors"].append({"page": page_url, "error": str(exc)})
    if args.print_samples:
        summary["samples"] = samples
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
