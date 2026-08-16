from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.schema import initialize_schema as initialize_english_schema  # noqa: E402
from app.platform.db import DATA_DIR, get_connection, initialize_database  # noqa: E402


LIST_URL = "https://zhenti.burningvocabulary.cn/kaoyan"
SITE_ORIGIN = "https://zhenti.burningvocabulary.cn"
PUBLIC_SOURCE_LABEL = "英语真题在线公开 PDF"
DEFAULT_YEAR_START = 2020
DEFAULT_YEAR_END = 2026
PDF_DIR = DATA_DIR / "english" / "passages" / "source_pdfs" / "kaoyan"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
EXAM_TYPE_BY_CODE = {"01": "english1", "02": "english2"}
EXAM_LABEL_BY_CODE = {"01": "英语一", "02": "英语二"}


@dataclass(frozen=True)
class Paper:
    year: int
    type_code: str
    page_url: str


@dataclass(frozen=True)
class PaperResource:
    paper: Paper
    title: str
    pdf_url: str
    pdf_path: Path


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_bytes(url: str, *, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _fetch_text(url: str, *, timeout: int = 30) -> str:
    return _fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def discover_public_papers(
    *,
    year_start: int,
    year_end: int,
    exam_types: set[str],
) -> list[Paper]:
    html = _fetch_text(LIST_URL)
    papers: dict[tuple[int, str], Paper] = {}
    for match in re.finditer(r'href=["\'](/kaoyan/(\d{4})/(0[12]))["\']', html):
        relative_url, raw_year, type_code = match.groups()
        year = int(raw_year)
        if year < year_start or year > year_end or type_code not in exam_types:
            continue
        papers[(year, type_code)] = Paper(year=year, type_code=type_code, page_url=f"{SITE_ORIGIN}{relative_url}")
    return [papers[key] for key in sorted(papers)]


def _extract_global_config(html: str) -> dict:
    match = re.search(r"var\s+globalConfig\s*=\s*(\{.*?\})\s*globalConfig\.showed", html, flags=re.S)
    if not match:
        raise ValueError("globalConfig not found")
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"globalConfig is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("globalConfig is not an object")
    return parsed


def resolve_paper_resource(paper: Paper) -> PaperResource:
    html = _fetch_text(paper.page_url)
    config = _extract_global_config(html)
    fn = config.get("fn") if isinstance(config.get("fn"), dict) else {}
    f1 = fn.get("f1") if isinstance(fn.get("f1"), list) else []
    f2 = fn.get("f2") if isinstance(fn.get("f2"), list) else []
    filename = "".join(str(part) for part in reversed(f1 + f2))
    if not filename:
        raise ValueError(f"PDF filename cannot be resolved: {paper.page_url}")
    file_path = str(config.get("filePath") or f"kaoyan/{paper.year}/{paper.type_code}").strip("/")
    pdf_host = str(config.get("pdfHost") or "").rstrip("/")
    if not pdf_host:
        raise ValueError(f"PDF host cannot be resolved: {paper.page_url}")
    version = config.get("fnameVersion")
    version_query = f"?v={version}" if version else ""
    pdf_url = f"{pdf_host}/images/read/{file_path}/{filename}.pdf{version_query}"
    title = str(config.get("title") or f"{paper.year}年考研{EXAM_LABEL_BY_CODE[paper.type_code]}")
    pdf_path = PDF_DIR / str(paper.year) / paper.type_code / f"{filename}.pdf"
    return PaperResource(paper=paper, title=title, pdf_url=pdf_url, pdf_path=pdf_path)


def download_pdf(resource: PaperResource, *, refresh: bool = False) -> bool:
    if resource.pdf_path.exists() and resource.pdf_path.stat().st_size > 0 and not refresh:
        return False
    resource.pdf_path.parent.mkdir(parents=True, exist_ok=True)
    content = _fetch_bytes(resource.pdf_url, timeout=60)
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Downloaded file is not a PDF: {resource.pdf_url}")
    with tempfile.NamedTemporaryFile(delete=False, dir=resource.pdf_path.parent) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(resource.pdf_path)
    return True


def extract_pdf_text(pdf_path: Path) -> str:
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext is required. Install poppler-utils in the backend image.")
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _clean_pdf_lines(raw_text: str) -> list[str]:
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").split("\n")
    cleaned: list[str] = []
    for line in lines:
        if re.match(r"^\s*\d+\s+https://zhenti\.burningvocabulary\.(?:cn|com)\s*$", line):
            continue
        if re.match(r"^\s*https://zhenti\.burningvocabulary\.(?:cn|com)\s*$", line):
            continue
        cleaned.append(line.rstrip())
    return cleaned


def _line_text(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip())


def _find_line(lines: list[str], pattern: str, start: int = 0, end: int | None = None) -> int | None:
    marker = re.compile(pattern, flags=re.I)
    stop = len(lines) if end is None else min(end, len(lines))
    for index in range(max(0, start), stop):
        if marker.match(_line_text(lines[index])):
            return index
    return None


def _first_existing(*values: int | None, default: int) -> int:
    candidates = [value for value in values if value is not None]
    return min(candidates) if candidates else default


def _after_directions(lines: list[str], start: int, end: int) -> int:
    for index in range(start, end):
        text = _line_text(lines[index])
        if re.search(r"\(\s*\d+\s+points?\s*\)", text, flags=re.I) or re.match(r"^points?\)\s*$", text, flags=re.I):
            return index + 1
    # Fallback: skip the "Directions:" line and the following short instruction block.
    for index in range(start, min(start + 12, end)):
        if _line_text(lines[index]).lower().startswith("directions"):
            return min(index + 4, end)
    return start


def _find_marker(lines: list[str], text_index: int) -> int | None:
    marker = re.compile(rf"^\s*Text\s+{text_index}\s*$", flags=re.I)
    for index, line in enumerate(lines):
        if marker.match(line):
            return index
    return None


def _find_article_end(lines: list[str], start: int, text_index: int) -> int:
    question_no = 21 + (text_index - 1) * 5
    question_pattern = re.compile(rf"^\s*{question_no}\.\s+")
    next_marker = re.compile(r"^\s*(Text\s+[1-4]|Part\s+B|Part\s+C|Section\s+III)\s*$", flags=re.I)
    for index in range(start, len(lines)):
        line = lines[index]
        if question_pattern.match(line):
            return index
        if index > start and next_marker.match(line):
            return index
    return len(lines)


def _join_article_lines(lines: list[str]) -> str:
    nonempty_count = sum(1 for line in lines if line.strip())
    blank_count = len(lines) - nonempty_count
    if nonempty_count and blank_count > nonempty_count * 0.6:
        lines = [line for line in lines if line.strip()]

    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        paragraph = " ".join(current)
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        paragraph = re.sub(r"([A-Za-z])-\s+([A-Za-z])", r"\1-\2", paragraph)
        if paragraph:
            paragraphs.append(paragraph)
        current.clear()

    for raw_line in lines:
        if not raw_line.strip():
            flush()
            continue
        stripped = re.sub(r"\s+", " ", raw_line.strip())
        if not stripped:
            continue
        if "→" in stripped and re.search(r"\b4[1-5]\b", stripped):
            flush()
            continue
        leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
        if current and leading_spaces >= 8 and re.match(r"^[A-Za-z“\"'(\[]", stripped):
            flush()
        current.append(stripped)
    flush()
    return "\n\n".join(paragraphs).strip()


def _looks_like_option_line(text: str) -> bool:
    return bool(re.match(r"^[A-H]\.\s+", _line_text(text)))


def _strip_leading_option_block(lines: list[str]) -> list[str]:
    index = 0
    seen_options = 0
    while index < len(lines):
        text = _line_text(lines[index])
        if not text:
            index += 1
            continue
        if _looks_like_option_line(text):
            seen_options += 1
            index += 1
            continue
        if seen_options >= 2:
            return lines[index:]
        return lines
    return lines


def _strip_trailing_option_block(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        if index > 8 and _looks_like_option_line(line):
            return lines[:index]
    return lines


def _part_b_subtype(direction_text: str) -> tuple[str, str]:
    text = direction_text.lower()
    if "wrong order" in text or "reorganize" in text:
        return "paragraph_reorder", "段落排序"
    if "removed" in text or "fit into each of the numbered blanks" in text:
        return "sentence_restore", "句子还原"
    if "left column" in text or "corresponding information" in text:
        return "information_match", "信息匹配"
    if "comments" in text and "statements" in text:
        return "comment_match", "观点匹配"
    if "description" in text:
        return "description_match", "描述匹配"
    if "subheading" in text:
        return "subheading_match", "标题匹配"
    return "reading_b", "新题型"


def _section_markers(lines: list[str]) -> dict[str, int | None]:
    section_i = _find_line(lines, r"^Section\s+I\b")
    section_ii = _find_line(lines, r"^Section\s+II\b")
    section_iii = _find_line(lines, r"^Section\s+III\b", section_ii or 0)
    section_iv = _find_line(lines, r"^Section\s+IV\b", section_iii or 0)
    reading_part_b = _find_line(lines, r"^Part\s+B\b", section_ii or 0, section_iii or len(lines))
    reading_part_c = _find_line(lines, r"^Part\s+C\b", reading_part_b or section_ii or 0, section_iii or len(lines))
    writing = _find_line(lines, r"^Section\s+(III|IV)\b.*Writing\b", section_ii or 0)
    if writing is None:
        writing = section_iv
    return {
        "section_i": section_i,
        "section_ii": section_ii,
        "section_iii": section_iii,
        "section_iv": section_iv,
        "reading_part_b": reading_part_b,
        "reading_part_c": reading_part_c,
        "writing": writing,
    }


def extract_reading_passages(resource: PaperResource, pdf_text: str) -> list[ExtractedPassage]:
    lines = _clean_pdf_lines(pdf_text)
    passages: list[ExtractedPassage] = []
    for text_index in range(1, 5):
        marker_index = _find_marker(lines, text_index)
        if marker_index is None:
            continue
        start = marker_index + 1
        end = _find_article_end(lines, start, text_index)
        body_text = _join_article_lines(lines[start:end])
        if len(body_text) < 500:
            continue
        paper = resource.paper
        exam_label = EXAM_LABEL_BY_CODE[paper.type_code]
        passages.append(
            ExtractedPassage(
                title=f"{paper.year}年考研{exam_label} Text {text_index}",
                source_url=f"{paper.page_url}#text-{text_index}",
                year=paper.year,
                exam_type=EXAM_TYPE_BY_CODE[paper.type_code],
                passage_type="reading_a",
                body_text=body_text,
                text_index=text_index,
                subtype=f"text_{text_index}",
            )
        )
    return passages


def extract_extra_passages(resource: PaperResource, pdf_text: str) -> list[ExtractedPassage]:
    lines = _clean_pdf_lines(pdf_text)
    markers = _section_markers(lines)
    paper = resource.paper
    exam_label = EXAM_LABEL_BY_CODE[paper.type_code]
    exam_type = EXAM_TYPE_BY_CODE[paper.type_code]
    passages: list[ExtractedPassage] = []

    section_i = markers["section_i"]
    section_ii = markers["section_ii"]
    if section_i is not None and section_ii is not None:
        start = _after_directions(lines, section_i + 1, section_ii)
        end = _find_line(lines, r"^1\.\s+A\.", start, section_ii) or section_ii
        body_text = _join_article_lines(lines[start:end])
        if len(body_text) >= 500:
            passages.append(
                ExtractedPassage(
                    title=f"{paper.year}年考研{exam_label} 完形填空",
                    source_url=f"{paper.page_url}#cloze",
                    year=paper.year,
                    exam_type=exam_type,
                    passage_type="cloze",
                    body_text=body_text,
                    text_index=0,
                    subtype="use_of_english",
                )
            )

    part_b = markers["reading_part_b"]
    if part_b is not None:
        end = _first_existing(
            markers["reading_part_c"],
            markers["section_iii"],
            markers["section_iv"],
            default=len(lines),
        )
        start = _after_directions(lines, part_b + 1, end)
        direction_text = " ".join(_line_text(line) for line in lines[part_b:end][:12])
        subtype, subtype_label = _part_b_subtype(direction_text)
        part_lines = lines[start:end]
        if subtype in {"subheading_match", "description_match"}:
            part_lines = _strip_leading_option_block(part_lines)
        if subtype in {"information_match", "comment_match"}:
            part_lines = _strip_trailing_option_block(part_lines)
        body_text = _join_article_lines(part_lines)
        if len(body_text) >= 500:
            passages.append(
                ExtractedPassage(
                    title=f"{paper.year}年考研{exam_label} 新题型（{subtype_label}）",
                    source_url=f"{paper.page_url}#part-b",
                    year=paper.year,
                    exam_type=exam_type,
                    passage_type="reading_b",
                    body_text=body_text,
                    text_index=5,
                    subtype=subtype,
                )
            )

    translation_start = None
    translation_end = None
    if paper.type_code == "01" and markers["reading_part_c"] is not None:
        part_c = markers["reading_part_c"]
        translation_end = _first_existing(markers["writing"], markers["section_iii"], default=len(lines))
        translation_start = _after_directions(lines, part_c + 1, translation_end)
    elif paper.type_code == "02" and markers["section_iii"] is not None:
        section_iii = markers["section_iii"]
        translation_end = _first_existing(markers["section_iv"], markers["writing"], default=len(lines))
        translation_start = _after_directions(lines, section_iii + 1, translation_end)

    if translation_start is not None and translation_end is not None and translation_end > translation_start:
        body_text = _join_article_lines(lines[translation_start:translation_end])
        if len(body_text) >= 500:
            passages.append(
                ExtractedPassage(
                    title=f"{paper.year}年考研{exam_label} 翻译材料",
                    source_url=f"{paper.page_url}#translation",
                    year=paper.year,
                    exam_type=exam_type,
                    passage_type="translation",
                    body_text=body_text,
                    text_index=6,
                    subtype="translation",
                )
            )
    return passages


def _get_user_id(username: str) -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ? LIMIT 1", (username,)).fetchone()
    if not row:
        raise ValueError(f"user not found: {username}")
    return int(row["id"])


def _upsert_passage(
    passage: ExtractedPassage,
    *,
    user_id: int,
    refresh: bool,
    dry_run: bool,
) -> str:
    now = _now()
    intensive_json = json.dumps({"source_subtype": passage.subtype}, ensure_ascii=False)
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, deleted_at, body_text, status, selected_sentence_ids_json
            FROM english_passages
            WHERE user_id = ? AND source_url = ?
            LIMIT 1
            """,
            (user_id, passage.source_url),
        ).fetchone()
        if existing and not refresh:
            return "skipped"
        if dry_run:
            return "would_update" if existing else "would_insert"
        if existing:
            has_user_work = (
                "**" in str(existing["body_text"] or "")
                or str(existing["status"] or "new") != "new"
                or str(existing["selected_sentence_ids_json"] or "[]") not in {"", "[]"}
            )
            conn.execute(
                """
                UPDATE english_passages
                SET title = ?,
                    source_label = ?,
                    year = ?,
                    exam_type = ?,
                    passage_type = ?,
                    body_text = CASE WHEN ? THEN body_text ELSE ? END,
                    intensive_json = CASE
                        WHEN COALESCE(intensive_json, '') IN ('', '{}') THEN ?
                        ELSE intensive_json
                    END,
                    deleted_at = '',
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    passage.title,
                    PUBLIC_SOURCE_LABEL,
                    passage.year,
                    passage.exam_type,
                    passage.passage_type,
                    int(has_user_work),
                    passage.body_text,
                    intensive_json,
                    now,
                    int(existing["id"]),
                    user_id,
                ),
            )
            return "updated"
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


def _parse_exam_types(raw_value: str) -> set[str]:
    aliases = {
        "01": "01",
        "1": "01",
        "english1": "01",
        "英一": "01",
        "英语一": "01",
        "02": "02",
        "2": "02",
        "english2": "02",
        "英二": "02",
        "英语二": "02",
    }
    result = set()
    for part in re.split(r"[,，\s]+", raw_value.strip()):
        if not part:
            continue
        normalized = aliases.get(part.lower(), aliases.get(part))
        if not normalized:
            raise ValueError(f"unsupported exam type: {part}")
        result.add(normalized)
    return result or {"01", "02"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import public kaoyan English passages from zhenti.burningvocabulary.cn PDFs."
    )
    parser.add_argument("--username", default="admin", help="target user for english_passages")
    parser.add_argument("--year-start", type=int, default=DEFAULT_YEAR_START)
    parser.add_argument("--year-end", type=int, default=DEFAULT_YEAR_END)
    parser.add_argument("--exam-types", default="01,02", help="01/02, english1/english2, 英一/英二")
    parser.add_argument("--limit-papers", type=int, default=0)
    parser.add_argument("--limit-passages", type=int, default=0)
    parser.add_argument(
        "--include",
        default="reading_a,cloze,reading_b,translation",
        help="comma-separated passage types: reading_a, cloze, reading_b, translation",
    )
    parser.add_argument("--refresh", action="store_true", help="redownload PDFs and update existing passages")
    parser.add_argument("--dry-run", action="store_true", help="fetch and extract but do not write DB rows")
    args = parser.parse_args()

    initialize_database()
    initialize_english_schema()
    user_id = _get_user_id(args.username)
    exam_types = _parse_exam_types(args.exam_types)
    include_types = {
        part.strip().lower().replace("-", "_")
        for part in re.split(r"[,，\s]+", str(args.include or ""))
        if part.strip()
    } or {"reading_a", "cloze", "reading_b", "translation"}
    papers = discover_public_papers(
        year_start=args.year_start,
        year_end=args.year_end,
        exam_types=exam_types,
    )
    if args.limit_papers > 0:
        papers = papers[: args.limit_papers]

    summary: dict[str, Any] = {
        "papers_discovered": len(papers),
        "papers_processed": 0,
        "pdf_downloaded": 0,
        "passages_extracted": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "would_insert": 0,
        "would_update": 0,
        "by_type": {},
        "errors": [],
    }

    for paper in papers:
        if args.limit_passages > 0 and summary["passages_extracted"] >= args.limit_passages:
            break
        try:
            resource = resolve_paper_resource(paper)
            if download_pdf(resource, refresh=args.refresh):
                summary["pdf_downloaded"] += 1
            pdf_text = extract_pdf_text(resource.pdf_path)
            passages: list[ExtractedPassage] = []
            if "reading_a" in include_types:
                passages.extend(extract_reading_passages(resource, pdf_text))
            if {"cloze", "reading_b", "translation"} & include_types:
                passages.extend(
                    passage
                    for passage in extract_extra_passages(resource, pdf_text)
                    if passage.passage_type in include_types
                )
            summary["papers_processed"] += 1
            for passage in passages:
                if args.limit_passages > 0 and summary["passages_extracted"] >= args.limit_passages:
                    break
                outcome = _upsert_passage(
                    passage,
                    user_id=user_id,
                    refresh=args.refresh,
                    dry_run=args.dry_run,
                )
                summary["passages_extracted"] += 1
                by_type = summary.setdefault("by_type", {})
                by_type[passage.passage_type] = int(by_type.get(passage.passage_type, 0)) + 1
                summary[outcome] = int(summary.get(outcome, 0)) + 1
        except (OSError, RuntimeError, ValueError, urllib.error.URLError, subprocess.CalledProcessError) as exc:
            summary["errors"].append({"paper": paper.page_url, "error": str(exc)})

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
