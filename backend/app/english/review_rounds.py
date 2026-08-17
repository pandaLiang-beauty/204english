from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any


ROUND_LENGTH_DAYS = 7


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expiry_for(now: datetime) -> datetime:
    # UTC midnight is the configured 08:00 study-day boundary in Beijing.
    boundary = datetime.combine(now.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return boundary + timedelta(days=ROUND_LENGTH_DAYS)


def _round_row(conn, *, user_id: int):
    return conn.execute(
        """
        SELECT *
        FROM english_review_rounds
        WHERE user_id = ? AND status = 'active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def _close_round(conn, *, round_id: int, reason: str, now: datetime) -> None:
    conn.execute(
        """
        UPDATE english_review_rounds
        SET status = ?, ended_at = ?, end_reason = ?, updated_at = ?
        WHERE id = ? AND status = 'active'
        """,
        ("completed" if reason == "completed" else "expired", _iso(now), reason, _iso(now), round_id),
    )


def _active_sentence_counts(conn, *, round_id: int) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN COALESCE(ri.completed_at, '') <> '' THEN 1 ELSE 0 END), 0) AS completed
        FROM english_review_round_items ri
        JOIN english_sentences s ON s.id = ri.sentence_id
        WHERE ri.round_id = ? AND COALESCE(s.deleted_at, '') = ''
        """,
        (round_id,),
    ).fetchone()
    return (int(row["total"] or 0), int(row["completed"] or 0)) if row else (0, 0)


def _create_round(conn, *, user_id: int, sentence_ids: list[int], now: datetime) -> dict:
    now_text = _iso(now)
    conn.execute(
        """
        INSERT INTO english_review_rounds(
            user_id, status, started_at, expires_at, ended_at, end_reason, created_at, updated_at
        ) VALUES (?, 'active', ?, ?, '', '', ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (user_id, now_text, _iso(_expiry_for(now)), now_text, now_text),
    )
    row = _round_row(conn, user_id=user_id)
    if not row:
        raise RuntimeError("failed to create English review round")
    round_id = int(row["id"])
    for position, sentence_id in enumerate(sentence_ids, start=1):
        conn.execute(
            """
            INSERT INTO english_review_round_items(
                round_id, user_id, sentence_id, position, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '', ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (round_id, user_id, sentence_id, position, now_text, now_text),
        )
    return dict(row)


def ensure_active_round(conn, *, user_id: int, ordered_sentence_ids: list[int]) -> tuple[dict, bool]:
    now = _utc_now()
    row = _round_row(conn, user_id=user_id)
    created = False
    if row:
        current = dict(row)
        expires_at = _parse(current.get("expires_at"))
        total, completed = _active_sentence_counts(conn, round_id=int(current["id"]))
        if expires_at is None or now >= expires_at:
            _close_round(conn, round_id=int(current["id"]), reason="expired", now=now)
            row = None
        elif total > 0 and completed >= total:
            _close_round(conn, round_id=int(current["id"]), reason="completed", now=now)
            row = None

    if not row:
        current = _create_round(conn, user_id=user_id, sentence_ids=ordered_sentence_ids, now=now)
        created = True
    else:
        current = dict(row)
        existing_rows = conn.execute(
            "SELECT sentence_id FROM english_review_round_items WHERE round_id = ?",
            (int(current["id"]),),
        ).fetchall()
        existing_ids = {int(item["sentence_id"]) for item in existing_rows}
        missing_ids = [sentence_id for sentence_id in ordered_sentence_ids if sentence_id not in existing_ids]
        if missing_ids:
            max_row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS value FROM english_review_round_items WHERE round_id = ?",
                (int(current["id"]),),
            ).fetchone()
            position = int(max_row["value"] or 0)
            now_text = _iso(now)
            for sentence_id in missing_ids:
                position += 1
                conn.execute(
                    """
                    INSERT INTO english_review_round_items(
                        round_id, user_id, sentence_id, position, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, '', ?, ?)
                    """,
                    (int(current["id"]), user_id, sentence_id, position, now_text, now_text),
                )
    return current, created


def queue_state(
    conn,
    *,
    user_id: int,
    ordered_sentence_ids: list[int],
    page: int,
    page_size: int,
    resume: bool,
) -> dict:
    current, created = ensure_active_round(conn, user_id=user_id, ordered_sentence_ids=ordered_sentence_ids)
    round_id = int(current["id"])
    eligible_sentence_ids = {int(sentence_id) for sentence_id in ordered_sentence_ids}
    items = conn.execute(
        """
        SELECT ri.sentence_id, ri.position, ri.completed_at
        FROM english_review_round_items ri
        JOIN english_sentences s ON s.id = ri.sentence_id
        WHERE ri.round_id = ? AND COALESCE(s.deleted_at, '') = ''
        ORDER BY ri.position
        """,
        (round_id,),
    ).fetchall()
    all_records = [dict(item) for item in items]
    records = [
        item
        for item in all_records
        if int(item["sentence_id"]) in eligible_sentence_ids
    ]
    first_incomplete_index = next(
        (index for index, item in enumerate(records) if not str(item.get("completed_at") or "")),
        0,
    )
    resume_page = first_incomplete_index // page_size + 1
    page_count = max(1, (len(records) + page_size - 1) // page_size)
    requested_page = min(max(int(page or 1), 1), page_count)
    actual_page = 1 if created else resume_page if resume else requested_page
    start = (actual_page - 1) * page_size
    queue_total = len(records)
    queue_completed = sum(1 for item in records if str(item.get("completed_at") or ""))
    total = len(all_records)
    completed = sum(1 for item in all_records if str(item.get("completed_at") or ""))
    return {
        "round": {
            "id": round_id,
            "started_at": current.get("started_at") or "",
            "expires_at": current.get("expires_at") or "",
            "completed": completed,
            "total": total,
            "remaining": max(total - completed, 0),
            "available": queue_total,
            "available_remaining": max(queue_total - queue_completed, 0),
            "resume_page": resume_page,
        },
        "page": actual_page,
        "records": records[start : start + page_size],
        "total": queue_total,
    }


def complete_current_item(conn, *, user_id: int, sentence_id: int) -> dict:
    row = _round_row(conn, user_id=user_id)
    if not row:
        return {"completed": False, "round_completed": False}
    current = dict(row)
    now_text = _iso(_utc_now())
    cursor = conn.execute(
        """
        UPDATE english_review_round_items
        SET completed_at = CASE WHEN COALESCE(completed_at, '') = '' THEN ? ELSE completed_at END,
            updated_at = ?
        WHERE round_id = ? AND user_id = ? AND sentence_id = ?
        """,
        (now_text, now_text, int(current["id"]), user_id, sentence_id),
    )
    if cursor.rowcount <= 0:
        return {"completed": False, "round_completed": False, "round_id": int(current["id"])}
    total, completed = _active_sentence_counts(conn, round_id=int(current["id"]))
    done = total > 0 and completed >= total
    if done:
        _close_round(conn, round_id=int(current["id"]), reason="completed", now=_utc_now())
    return {"completed": True, "round_completed": done, "round_id": int(current["id"])}
