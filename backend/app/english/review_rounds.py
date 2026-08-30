from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from ..platform.db import begin_immediate


ROUND_LENGTH_DAYS = 7


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def study_boundary_for(value: datetime | None = None) -> datetime:
    """Return the current study-day boundary (Beijing 08:00 = UTC midnight)."""
    current = value or _utc_now()
    return datetime.combine(
        current.astimezone(timezone.utc).date(),
        time.min,
        tzinfo=timezone.utc,
    )


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expiry_for(now: datetime) -> datetime:
    return study_boundary_for(now) + timedelta(days=ROUND_LENGTH_DAYS)


def _next_study_boundary(value: datetime) -> datetime:
    return study_boundary_for(value) + timedelta(days=1)


def _next_start_from_history(conn, *, user_id: int, now: datetime) -> datetime:
    """Find the fixed 08:00 boundary for the next schedule."""
    row = conn.execute(
        """
        SELECT *
        FROM english_review_rounds
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return study_boundary_for(now)

    if str(row["status"] or "") == "completed":
        completed_row = conn.execute(
            """
            SELECT MAX(completed_at) AS completed_at
            FROM english_review_round_items
            WHERE round_id = ? AND COALESCE(completed_at, '') <> ''
            """,
            (int(row["id"]),),
        ).fetchone()
        candidate = _next_study_boundary(_parse(completed_row["completed_at"] if completed_row else None) or now)
    else:
        candidate = _parse(row["expires_at"]) or study_boundary_for(now)

    while candidate + timedelta(days=ROUND_LENGTH_DAYS) <= now:
        candidate += timedelta(days=ROUND_LENGTH_DAYS)
    return candidate


def _previous_round(conn, *, user_id: int, round_id: int):
    return conn.execute(
        """
        SELECT *
        FROM english_review_rounds
        WHERE user_id = ? AND id < ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, round_id),
    ).fetchone()


def normalize_active_round_boundary(conn, *, user_id: int, now: datetime | None = None) -> dict | None:
    """Repair an active cycle created by the old request-time implementation.

    Existing progress is preserved; only the cycle's fixed boundary timestamps
    are corrected. New cycles are created with these timestamps from the start.
    """
    current_now = now or _utc_now()
    row = _round_row(conn, user_id=user_id)
    if not row:
        return None
    previous = _previous_round(conn, user_id=user_id, round_id=int(row["id"]))
    if not previous:
        current_expiry = _parse(row["expires_at"])
        expected_start = (
            current_expiry - timedelta(days=ROUND_LENGTH_DAYS)
            if current_expiry
            else study_boundary_for(current_now)
        )
        if expected_start <= current_now and _parse(row["started_at"]) != expected_start:
            now_text = _iso(current_now)
            conn.execute(
                """
                UPDATE english_review_rounds
                SET started_at = ?, expires_at = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (_iso(expected_start), _iso(expected_start + timedelta(days=ROUND_LENGTH_DAYS)), now_text, int(row["id"])),
            )
            return dict(conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (int(row["id"]),)).fetchone())
        return dict(row)
    expected_start = None
    previous_expiry = _parse(previous["expires_at"])
    if str(previous["end_reason"] or "") == "completed":
        completed_row = conn.execute(
            "SELECT MAX(completed_at) AS completed_at FROM english_review_round_items WHERE round_id = ?",
            (int(previous["id"]),),
        ).fetchone()
        completed_at = _parse(completed_row["completed_at"] if completed_row else None)
        expected_start = _next_study_boundary(completed_at or previous_expiry or current_now)
    else:
        expected_start = previous_expiry
    if expected_start is None:
        expected_start = study_boundary_for(current_now)
    if expected_start > current_now:
        return dict(row)
    expected_expiry = expected_start + timedelta(days=ROUND_LENGTH_DAYS)
    if _parse(row["started_at"]) == expected_start and _parse(row["expires_at"]) == expected_expiry:
        return dict(row)
    now_text = _iso(current_now)
    conn.execute(
        """
        UPDATE english_review_rounds
        SET started_at = ?, expires_at = ?, updated_at = ?
        WHERE id = ? AND status = 'active'
        """,
        (_iso(expected_start), _iso(expected_expiry), now_text, int(row["id"])),
    )
    updated = dict(conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (int(row["id"]),)).fetchone())
    return updated


def due_round_start(conn, *, user_id: int, now: datetime | None = None) -> datetime | None:
    """Return the next cycle start if rotation is due, otherwise ``None``."""
    current_now = now or _utc_now()
    row = _round_row(conn, user_id=user_id)
    if not row:
        return _next_start_from_history(conn, user_id=user_id, now=current_now)

    expires_at = _parse(row["expires_at"])
    if expires_at is None or current_now >= expires_at:
        return _next_start_from_history(conn, user_id=user_id, now=current_now)

    total, completed = _active_sentence_counts(conn, round_id=int(row["id"]))
    if total > 0 and completed >= total:
        completed_row = conn.execute(
            "SELECT MAX(completed_at) AS completed_at FROM english_review_round_items WHERE round_id = ?",
            (int(row["id"]),),
        ).fetchone()
        next_boundary = _next_study_boundary(_parse(completed_row["completed_at"] if completed_row else None) or current_now)
        if current_now >= next_boundary:
            return next_boundary
    return None


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


def _create_round(
    conn,
    *,
    user_id: int,
    schedule: list[dict],
    now: datetime,
    started_at: datetime | None = None,
) -> dict:
    created_text = _iso(now)
    round_start = started_at or study_boundary_for(now)
    start_text = _iso(round_start)
    conn.execute(
        """
        INSERT INTO english_review_rounds(
            user_id, status, started_at, expires_at, ended_at, end_reason, created_at, updated_at
        ) VALUES (?, 'active', ?, ?, '', '', ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (user_id, start_text, _iso(round_start + timedelta(days=ROUND_LENGTH_DAYS)), created_text, created_text),
    )
    row = _round_row(conn, user_id=user_id)
    if not row:
        raise RuntimeError("failed to create English review round")
    round_id = int(row["id"])
    for position, item in enumerate(schedule, start=1):
        conn.execute(
            """
            INSERT INTO english_review_round_items(
                round_id, user_id, sentence_id, position,
                repeat_index, repeat_total, exposure_score,
                completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                round_id,
                user_id,
                int(item["sentence_id"]),
                position,
                int(item.get("repeat_index") or 1),
                int(item.get("repeat_total") or 1),
                float(item.get("exposure_score") or 0),
                created_text,
                created_text,
            ),
        )
    return dict(row)


def advance_active_round(
    conn,
    *,
    user_id: int,
    schedule: list[dict],
    now: datetime | None = None,
    start_at: datetime | None = None,
) -> tuple[dict, bool]:
    """Rotate the user's schedule using fixed Beijing-08:00 boundaries.

    The caller must hold the SQLite write transaction. This function is used by
    both the background scheduler and request-time recovery.
    """
    now = now or _utc_now()
    row = _round_row(conn, user_id=user_id)
    if row:
        return dict(row), False
    current = _create_round(
        conn,
        user_id=user_id,
        schedule=schedule,
        now=now,
        started_at=start_at or due_round_start(conn, user_id=user_id, now=now) or study_boundary_for(now),
    )
    return current, True


def close_due_round(conn, *, user_id: int, now: datetime | None = None) -> datetime | None:
    """Close a due active round and return the fixed start for its replacement."""
    current_now = now or _utc_now()
    start = due_round_start(conn, user_id=user_id, now=current_now)
    if start is None:
        return None
    row = _round_row(conn, user_id=user_id)
    if row:
        expires_at = _parse(row["expires_at"])
        total, completed = _active_sentence_counts(conn, round_id=int(row["id"]))
        reason = "expired" if expires_at is None or current_now >= expires_at else "completed"
        if reason == "completed" and not (total > 0 and completed >= total):
            reason = "expired"
        _close_round(conn, round_id=int(row["id"]), reason=reason, now=current_now)
    return start


def ensure_active_round(conn, *, user_id: int, schedule: list[dict]) -> tuple[dict, bool]:
    begin_immediate(conn)
    now = _utc_now()
    normalize_active_round_boundary(conn, user_id=user_id, now=now)
    start = due_round_start(conn, user_id=user_id, now=now)
    if start is None:
        row = _round_row(conn, user_id=user_id)
        if not row:
            raise RuntimeError("failed to resolve active English review round")
        return dict(row), False
    row = _round_row(conn, user_id=user_id)
    if row:
        expires_at = _parse(row["expires_at"])
        total, completed = _active_sentence_counts(conn, round_id=int(row["id"]))
        reason = None
        if expires_at is None or now >= expires_at:
            reason = "expired"
        elif total > 0 and completed >= total:
            reason = "completed"
        if reason:
            _close_round(conn, round_id=int(row["id"]), reason=reason, now=now)
    return advance_active_round(
        conn,
        user_id=user_id,
        schedule=schedule,
        now=now,
        start_at=start,
    )


def queue_state(
    conn,
    *,
    user_id: int,
    schedule: list[dict],
    page: int,
    page_size: int,
    resume: bool,
) -> dict:
    current, created = ensure_active_round(conn, user_id=user_id, schedule=schedule)
    round_id = int(current["id"])
    items = conn.execute(
        """
        SELECT ri.id, ri.sentence_id, ri.position,
               ri.repeat_index, ri.repeat_total, ri.exposure_score,
               ri.completed_at
        FROM english_review_round_items ri
        JOIN english_sentences s ON s.id = ri.sentence_id
        WHERE ri.round_id = ? AND COALESCE(s.deleted_at, '') = ''
        ORDER BY ri.position
        """,
        (round_id,),
    ).fetchall()
    records = [dict(item) for item in items]
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
    total = len(records)
    completed = sum(1 for item in records if str(item.get("completed_at") or ""))
    next_round_at = str(current.get("next_round_at") or "")
    if completed >= total > 0 and not next_round_at:
        completed_values = [
            _parse(item.get("completed_at"))
            for item in records
            if item.get("completed_at")
        ]
        last_completed = max((value for value in completed_values if value), default=_utc_now())
        next_round_at = _iso(_next_study_boundary(last_completed))
    return {
        "round": {
            "id": round_id,
            "started_at": current.get("started_at") or "",
            "expires_at": current.get("expires_at") or "",
            "completed": completed,
            "total": total,
            "remaining": max(total - completed, 0),
            "is_completed": total > 0 and completed >= total,
            "next_round_at": next_round_at,
            "available": queue_total,
            "available_remaining": max(queue_total - queue_completed, 0),
            "resume_page": resume_page,
        },
        "page": actual_page,
        "records": records[start : start + page_size],
        "total": queue_total,
    }


def complete_current_item(
    conn,
    *,
    user_id: int,
    sentence_id: int,
    round_item_id: int | None = None,
) -> dict:
    row = _round_row(conn, user_id=user_id)
    if not row:
        return {"completed": False, "round_completed": False}
    current = dict(row)
    now = _utc_now()
    expires_at = _parse(current.get("expires_at"))
    if expires_at is None or now >= expires_at:
        _close_round(conn, round_id=int(current["id"]), reason="expired", now=now)
        return {
            "completed": False,
            "round_completed": False,
            "round_expired": True,
            "round_id": int(current["id"]),
        }
    now_text = _iso(now)
    target = None
    if round_item_id:
        target = conn.execute(
            """
            SELECT id
            FROM english_review_round_items
            WHERE id = ? AND round_id = ? AND user_id = ? AND sentence_id = ?
              AND COALESCE(completed_at, '') = ''
            """,
            (round_item_id, int(current["id"]), user_id, sentence_id),
        ).fetchone()
    else:
        target = conn.execute(
            """
            SELECT id
            FROM english_review_round_items
            WHERE round_id = ? AND user_id = ? AND sentence_id = ?
              AND COALESCE(completed_at, '') = ''
            ORDER BY position
            LIMIT 1
            """,
            (int(current["id"]), user_id, sentence_id),
        ).fetchone()
    if not target:
        return {"completed": False, "round_completed": False, "round_id": int(current["id"])}
    item_id = int(target["id"])
    cursor = conn.execute(
        """
        UPDATE english_review_round_items
        SET completed_at = ?, updated_at = ?
        WHERE id = ? AND COALESCE(completed_at, '') = ''
        """,
        (now_text, now_text, item_id),
    )
    if cursor.rowcount <= 0:
        return {"completed": False, "round_completed": False, "round_id": int(current["id"])}
    total, completed = _active_sentence_counts(conn, round_id=int(current["id"]))
    done = total > 0 and completed >= total
    return {
        "completed": True,
        "round_completed": done,
        "round_id": int(current["id"]),
        "round_item_id": item_id,
        "next_round_at": _iso(_next_study_boundary(_parse(now_text) or _utc_now())) if done else "",
    }
