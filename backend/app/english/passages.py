from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..platform.db import get_connection, rows_to_dicts


PASSAGE_STATUSES = {"new", "reading", "done"}
PASSAGE_TYPES = {"reading_a", "cloze", "reading_b", "translation", "custom"}
PASSAGE_TYPE_RANK = {"reading_a": 0, "cloze": 1, "reading_b": 2, "translation": 3, "custom": 4}
PASSAGE_STATUS_RANK = {"reading": 0, "new": 1, "done": 2}
PASSAGE_EXAM_RANK = {"english1": 0, "english2": 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed if parsed is not None else fallback


def _clean_passage_status(value: str) -> str:
    status = str(value or "").strip().lower()
    return status if status in PASSAGE_STATUSES else "new"


def _clean_exam_type(value: str) -> str:
    exam_type = str(value or "").strip().lower()
    aliases = {
        "1": "english1",
        "一": "english1",
        "英语一": "english1",
        "english-1": "english1",
        "english_1": "english1",
        "2": "english2",
        "二": "english2",
        "英语二": "english2",
        "english-2": "english2",
        "english_2": "english2",
    }
    return aliases.get(exam_type, exam_type[:40])


def _clean_passage_type(value: str) -> str:
    passage_type = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "reading": "reading_a",
        "part_a": "reading_a",
        "text": "reading_a",
        "阅读": "reading_a",
        "阅读理解": "reading_a",
        "完形": "cloze",
        "完形填空": "cloze",
        "use_of_english": "cloze",
        "reading_b": "reading_b",
        "part_b": "reading_b",
        "new_type": "reading_b",
        "新题型": "reading_b",
        "翻译": "translation",
        "translation_text": "translation",
        "自建": "custom",
        "manual": "custom",
    }
    normalized = aliases.get(passage_type, passage_type)
    return normalized if normalized in PASSAGE_TYPES else "custom"


def _clean_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2200 else None


def _clean_body_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^\s*\d+\s+https://zhenti\.burningvocabulary\.(?:cn|com)\s*$", "", text)
    text = re.sub(r"(?m)^\s*https://zhenti\.burningvocabulary\.(?:cn|com)\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def serialize_passage(row: dict) -> dict:
    selected_sentence_ids = _json_loads(row.get("selected_sentence_ids_json"), [])
    if not isinstance(selected_sentence_ids, list):
        selected_sentence_ids = []
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "title": row.get("title") or "",
        "source_label": row.get("source_label") or "",
        "source_url": row.get("source_url") or "",
        "year": _clean_year(row.get("year")),
        "exam_type": row.get("exam_type") or "",
        "passage_type": _clean_passage_type(row.get("passage_type") or "reading_a"),
        "body_text": row.get("body_text") or "",
        "status": _clean_passage_status(row.get("status") or "new"),
        "selected_sentence_ids": [int(item) for item in selected_sentence_ids if str(item).isdigit()],
        "completed_at": row.get("completed_at") or "",
        "deleted_at": row.get("deleted_at") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


def _passage_text_index(row: dict) -> int:
    passage_type = _clean_passage_type(row.get("passage_type") or "reading_a")
    if passage_type == "cloze":
        return 0
    if passage_type == "reading_b":
        return 5
    if passage_type == "translation":
        return 6
    source_url = str(row.get("source_url") or "")
    title = str(row.get("title") or "")
    match = re.search(r"#text-(\d+)", source_url, flags=re.I) or re.search(r"\bText\s+(\d+)\b", title, flags=re.I)
    if match:
        try:
            return max(1, min(int(match.group(1)), 4))
        except (TypeError, ValueError):
            return 9
    return 9


def _passage_training_sort_key(row: dict) -> tuple:
    passage_type = _clean_passage_type(row.get("passage_type") or "reading_a")
    status = _clean_passage_status(row.get("status") or "new")
    exam_type = _clean_exam_type(row.get("exam_type") or "")
    year = _clean_year(row.get("year")) or 9999
    return (
        1 if status == "done" else 0,
        PASSAGE_TYPE_RANK.get(passage_type, 9),
        year,
        _passage_text_index(row),
        PASSAGE_EXAM_RANK.get(exam_type, 9),
        PASSAGE_STATUS_RANK.get(status, 9),
        int(row.get("id") or 0),
    )


def _is_completed_today(row: dict) -> bool:
    completed_at = str(row.get("completed_at") or "").strip()
    if not completed_at:
        return False
    return completed_at[:10] == datetime.now(timezone.utc).date().isoformat()


def _filter_today_passage_scope(rows: list[dict], *, passage_type_filter: str = "") -> list[dict]:
    clean_passage_type = _clean_passage_type(passage_type_filter)
    if passage_type_filter and clean_passage_type in PASSAGE_TYPES:
        return [row for row in rows if _clean_passage_type(row.get("passage_type") or "") == clean_passage_type]

    reading_rows = [row for row in rows if _clean_passage_type(row.get("passage_type") or "") == "reading_a"]
    active_reading_rows = [
        row
        for row in reading_rows
        if _is_completed_today(row) or _clean_passage_status(row.get("status") or "new") in {"reading", "new"}
    ]
    return reading_rows if active_reading_rows else rows


def _append_passage_pick(picked: list[dict], picked_ids: set[int], row: dict | None) -> None:
    if not row or len(picked) >= 2:
        return
    row_id = int(row["id"])
    if row_id in picked_ids:
        return
    picked.append(row)
    picked_ids.add(row_id)


def _pick_passage_pair_by_exam(rows: list[dict], picked: list[dict], picked_ids: set[int]) -> None:
    picked_exam_types = {_clean_exam_type(row.get("exam_type") or "") for row in picked}
    for exam_type in ("english1", "english2"):
        if len(picked) >= 2:
            return
        if exam_type in picked_exam_types:
            continue
        match = next(
            (
                row
                for row in rows
                if int(row["id"]) not in picked_ids
                and _clean_exam_type(row.get("exam_type") or "") == exam_type
            ),
            None,
        )
        _append_passage_pick(picked, picked_ids, match)


def _today_passage_rows(rows: list[dict], *, passage_type_filter: str = "") -> list[dict]:
    scoped_rows = _filter_today_passage_scope(rows, passage_type_filter=passage_type_filter)
    completed_today = [row for row in scoped_rows if _is_completed_today(row)]
    eligible = [
        row
        for row in scoped_rows
        if _clean_passage_status(row.get("status") or "new") in {"reading", "new"}
    ]

    picked: list[dict] = []
    picked_ids: set[int] = set()
    # A completed item is part of today's continuity; never replace it with a new item.
    for row in completed_today:
        if len(picked) >= 2:
            break
        _append_passage_pick(picked, picked_ids, row)
    _pick_passage_pair_by_exam(eligible, picked, picked_ids)

    for row in eligible:
        if len(picked) >= 2:
            break
        _append_passage_pick(picked, picked_ids, row)
    return picked[:2]


def _passage_where(*, user_id: int, include_deleted: bool = False) -> tuple[str, dict[str, Any]]:
    where = "WHERE user_id = :user_id"
    params: dict[str, Any] = {"user_id": int(user_id)}
    if not include_deleted:
        where += " AND COALESCE(deleted_at, '') = ''"
    return where, params


def list_passages(
    *,
    user_id: int,
    status: str = "",
    passage_type: str = "",
    exam_type: str = "",
    year: int | None = None,
    search: str = "",
    page: int = 1,
    page_size: int = 20,
    include_deleted: bool = False,
) -> dict:
    page = max(int(page or 1), 1)
    page_size = max(1, min(int(page_size or 20), 100))
    where, params = _passage_where(user_id=user_id, include_deleted=include_deleted)
    clean_status = _clean_passage_status(status)
    if status and clean_status in PASSAGE_STATUSES:
        where += " AND status = :status"
        params["status"] = clean_status
    clean_passage_type = _clean_passage_type(passage_type)
    if passage_type and clean_passage_type in PASSAGE_TYPES:
        where += " AND passage_type = :passage_type"
        params["passage_type"] = clean_passage_type
    clean_exam_type = _clean_exam_type(exam_type)
    if exam_type and clean_exam_type:
        where += " AND exam_type = :exam_type"
        params["exam_type"] = clean_exam_type
    clean_year = _clean_year(year)
    if year is not None and clean_year is not None:
        where += " AND year = :year"
        params["year"] = clean_year
    keyword = str(search or "").strip().lower()
    if keyword:
        params["kw"] = f"%{keyword}%"
        where += """
            AND (
                LOWER(title) LIKE :kw
                OR LOWER(source_label) LIKE :kw
                OR LOWER(passage_type) LIKE :kw
                OR LOWER(body_text) LIKE :kw
            )
        """
    with get_connection() as conn:
        total_row = conn.execute(f"SELECT COUNT(*) AS total FROM english_passages {where}", params).fetchone()
        all_rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT *
                FROM english_passages
                {where}
                """,
                params,
            ).fetchall()
        )
    sorted_rows = sorted(all_rows, key=_passage_training_sort_key)
    offset = (page - 1) * page_size
    rows = sorted_rows[offset : offset + page_size]
    today_rows = _today_passage_rows(sorted_rows, passage_type_filter=passage_type)
    return {
        "items": [serialize_passage(row) for row in rows],
        "today": serialize_passage(today_rows[0]) if today_rows else None,
        "today_items": [serialize_passage(row) for row in today_rows],
        "total": int(total_row["total"] if total_row else 0),
        "page": page,
        "page_size": page_size,
    }


def get_passage(passage_id: int, *, user_id: int, include_deleted: bool = False) -> dict | None:
    sql = "SELECT * FROM english_passages WHERE id = ? AND user_id = ?"
    params: tuple[Any, ...] = (passage_id, user_id)
    if not include_deleted:
        sql += " AND COALESCE(deleted_at, '') = ''"
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return serialize_passage(dict(row)) if row else None


def today_passage(*, user_id: int) -> dict | None:
    with get_connection() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM english_passages
                WHERE user_id = ?
                  AND COALESCE(deleted_at, '') = ''
                """,
                (user_id,),
            ).fetchall()
        )
    sorted_rows = sorted(rows, key=_passage_training_sort_key)
    today_rows = _today_passage_rows(sorted_rows)
    return serialize_passage(today_rows[0]) if today_rows else None


def create_passage(
    *,
    user_id: int,
    title: str = "",
    source_label: str = "",
    source_url: str = "",
    year: int | None = None,
    exam_type: str = "",
    passage_type: str = "custom",
    body_text: str,
) -> dict:
    body = _clean_body_text(body_text)
    if not body:
        raise ValueError("body_text is required")
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO english_passages(
                user_id, title, source_label, source_url, year, exam_type,
                passage_type, body_text, status, intensive_json, selected_sentence_ids_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', '{}', '[]', ?, ?)
            """,
            (
                user_id,
                str(title or "").strip(),
                str(source_label or "").strip(),
                str(source_url or "").strip(),
                _clean_year(year),
                _clean_exam_type(exam_type),
                _clean_passage_type(passage_type),
                body,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM english_passages WHERE id = ?", (int(cur.lastrowid),)).fetchone()
    return serialize_passage(dict(row))


def update_passage(
    *,
    passage_id: int,
    user_id: int,
    title: str = "",
    source_label: str = "",
    source_url: str = "",
    year: int | None = None,
    exam_type: str = "",
    passage_type: str = "custom",
    body_text: str,
    status: str = "",
) -> dict | None:
    body = _clean_body_text(body_text)
    if not body:
        raise ValueError("body_text is required")
    now = _now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM english_passages WHERE id = ? AND user_id = ? AND COALESCE(deleted_at, '') = ''",
            (passage_id, user_id),
        ).fetchone()
        if not existing:
            return None
        conn.execute(
            """
            UPDATE english_passages
            SET title = ?,
                source_label = ?,
                source_url = ?,
                year = ?,
                exam_type = ?,
                passage_type = ?,
                body_text = ?,
                status = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                str(title or "").strip(),
                str(source_label or "").strip(),
                str(source_url or "").strip(),
                _clean_year(year),
                _clean_exam_type(exam_type),
                _clean_passage_type(passage_type),
                body,
                _clean_passage_status(status),
                now,
                passage_id,
                user_id,
            ),
        )
        row = conn.execute("SELECT * FROM english_passages WHERE id = ? AND user_id = ?", (passage_id, user_id)).fetchone()
    return serialize_passage(dict(row)) if row else None


def complete_passage(*, passage_id: int, user_id: int) -> dict | None:
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM english_passages WHERE id = ? AND user_id = ? AND COALESCE(deleted_at, '') = ''",
            (passage_id, user_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE english_passages
            SET status = 'done',
                completed_at = CASE WHEN COALESCE(completed_at, '') = '' THEN ? ELSE completed_at END,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (now, now, passage_id, user_id),
        )
        updated = conn.execute("SELECT * FROM english_passages WHERE id = ? AND user_id = ?", (passage_id, user_id)).fetchone()
    return serialize_passage(dict(updated)) if updated else None


def delete_passage(*, passage_id: int, user_id: int) -> bool:
    now = _now()
    with get_connection() as conn:
        before = conn.total_changes
        conn.execute(
            """
            UPDATE english_passages
            SET deleted_at = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (now, now, passage_id, user_id),
        )
        return conn.total_changes > before
