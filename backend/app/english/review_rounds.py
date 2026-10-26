from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from typing import Any

from ..platform.db import begin_immediate


RECOMMENDED_DAILY_ITEMS = 100
TEST_ROUND_ID_ENV = "STUDY_ENGLISH_REVIEW_ROUND_TEST_ID"
TEST_EXPIRES_AT_ENV = "STUDY_ENGLISH_REVIEW_ROUND_TEST_EXPIRES_AT"


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


def _test_expiry_override(row: Any) -> datetime | None:
    """Return a one-round expiry override used for explicit cycle tests."""
    try:
        configured_round_id = int(os.getenv(TEST_ROUND_ID_ENV, "").strip())
    except ValueError:
        return None
    if configured_round_id != int(row["id"]):
        return None
    target = _parse(os.getenv(TEST_EXPIRES_AT_ENV, ""))
    started_at = _parse(row["started_at"])
    if target is None or started_at is None or target <= started_at:
        return None
    return target


def round_length_days(item_count: int) -> int:
    """Plan at most 100 items per day, without limiting actual review activity."""
    return max(1, (item_count + RECOMMENDED_DAILY_ITEMS - 1) // RECOMMENDED_DAILY_ITEMS)


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

    # The caller resolves missed cycles using each new snapshot's item count.
    return candidate


def _schedule_by_sentence(schedule: list[dict]) -> dict[int, dict]:
    """Collapse a schedule to one item per sentence in its first-seen order."""
    result: dict[int, dict] = {}
    for item in schedule:
        sentence_id = int(item["sentence_id"])
        result.setdefault(sentence_id, item)
    return result


def sync_active_round_items(
    conn,
    *,
    user_id: int,
    schedule: list[dict],
    now: datetime | None = None,
) -> dict | None:
    """Make the active round match the current active sentence set.

    A sentence is represented once in the active round. Existing completion
    state follows the sentence, new sentences are appended in smart order, and
    sentences removed from the active sentence set leave the current queue.
    Historical rounds remain unchanged.
    """
    round_row = _round_row(conn, user_id=user_id)
    if not round_row:
        return None

    desired = _schedule_by_sentence(schedule)
    round_id = int(round_row["id"])
    existing = conn.execute(
        """
        SELECT *
        FROM english_review_round_items
        WHERE round_id = ?
        ORDER BY position, id
        """,
        (round_id,),
    ).fetchall()

    kept_by_sentence: dict[int, Any] = {}
    for item in existing:
        sentence_id = int(item["sentence_id"])
        if sentence_id not in desired:
            continue
        previous = kept_by_sentence.get(sentence_id)
        if previous is None or (
            not str(previous["completed_at"] or "")
            and str(item["completed_at"] or "")
        ):
            kept_by_sentence[sentence_id] = item

    kept_ids = {int(item["id"]) for item in kept_by_sentence.values()}
    removed_ids = [int(item["id"]) for item in existing if int(item["id"]) not in kept_ids]
    if removed_ids:
        conn.executemany(
            "DELETE FROM english_review_round_items WHERE id = ?",
            [(item_id,) for item_id in removed_ids],
        )

    ordered = list(desired.items())
    position_offset = max(len(existing), len(ordered), 1) + 1000
    if kept_by_sentence:
        conn.execute(
            "UPDATE english_review_round_items SET position = position + ? WHERE round_id = ?",
            (position_offset, round_id),
        )

    timestamp = _iso(now or _utc_now())
    for position, (sentence_id, item) in enumerate(ordered, start=1):
        existing_item = kept_by_sentence.get(sentence_id)
        if existing_item is None:
            conn.execute(
                """
                INSERT INTO english_review_round_items(
                    round_id, user_id, sentence_id, position,
                    repeat_index, repeat_total, exposure_score,
                    completed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, 1, ?, '', ?, ?)
                """,
                (
                    round_id,
                    user_id,
                    sentence_id,
                    position,
                    float(item.get("exposure_score") or 0),
                    timestamp,
                    timestamp,
                ),
            )
            continue
        conn.execute(
            """
            UPDATE english_review_round_items
            SET position = ?, repeat_index = 1, repeat_total = 1,
                exposure_score = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                position,
                float(item.get("exposure_score") or 0),
                timestamp,
                int(existing_item["id"]),
            ),
        )

    return dict(conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (round_id,)).fetchone())


def normalize_active_round_boundary(conn, *, user_id: int, now: datetime | None = None) -> dict | None:
    """Recalculate the active round deadline from its visible item count."""
    current_now = now or _utc_now()
    row = _round_row(conn, user_id=user_id)
    if not row:
        return None
    started_at = _parse(row["started_at"]) or study_boundary_for(current_now)
    item_count = int(conn.execute(
        """
        SELECT COUNT(*)
        FROM english_review_round_items ri
        JOIN english_sentences s ON s.id = ri.sentence_id
        WHERE ri.round_id = ? AND COALESCE(s.deleted_at, '') = ''
        """,
        (int(row["id"]),),
    ).fetchone()[0])
    expected_expiry = _test_expiry_override(row) or started_at + timedelta(days=round_length_days(item_count))
    if _parse(row["expires_at"]) == expected_expiry:
        return dict(row)
    conn.execute(
        """
        UPDATE english_review_rounds
        SET expires_at = ?, updated_at = ?
        WHERE id = ? AND status = 'active'
        """,
        (_iso(expected_expiry), _iso(current_now), int(row["id"])),
    )
    return dict(conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (int(row["id"]),)).fetchone())


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
        (user_id, start_text, _iso(round_start + timedelta(days=round_length_days(len(schedule)))), created_text, created_text),
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
    """Rotate the user's schedule using Beijing-08:00 boundaries.

    The caller must hold the SQLite write transaction. This function is used by
    both the background scheduler and request-time recovery.
    """
    now = now or _utc_now()
    row = _round_row(conn, user_id=user_id)
    if row:
        return dict(row), False
    round_start = start_at or due_round_start(conn, user_id=user_id, now=now) or study_boundary_for(now)
    duration = timedelta(days=round_length_days(len(schedule)))
    if round_start + duration <= now:
        round_start += ((now - round_start) // duration) * duration
    current = _create_round(
        conn,
        user_id=user_id,
        schedule=schedule,
        now=now,
        started_at=round_start,
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
    sync_active_round_items(conn, user_id=user_id, schedule=schedule, now=now)
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


def _completion_state(conn, current: dict, target, *, newly_completed: bool = False) -> dict:
    round_id = int(current["id"])
    total, completed = _active_sentence_counts(conn, round_id=round_id)
    done = total > 0 and completed >= total
    next_round_at = ""
    if done:
        last_completed = conn.execute(
            "SELECT MAX(completed_at) FROM english_review_round_items WHERE round_id = ?",
            (round_id,),
        ).fetchone()[0]
        next_round_at = _iso(_next_study_boundary(_parse(last_completed) or _utc_now()))
    return {
        # Keep the write-result flag for callers that increment event counters.
        "completed": newly_completed,
        "item_is_completed": bool(target and (newly_completed or target["completed_at"])),
        "round_completed": done,
        "round_id": round_id,
        "round_item_id": int(target["id"]) if target else None,
        "next_round_at": next_round_at,
        "round": {
            "id": round_id,
            "started_at": current["started_at"],
            "expires_at": current["expires_at"],
            "total": total,
            "completed": completed,
            "remaining": max(total - completed, 0),
            "available": total,
            "available_remaining": max(total - completed, 0),
            "is_completed": done,
            "next_round_at": next_round_at,
        },
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
        return {"completed": False, "round_completed": False, "round_expired": bool(round_item_id)}
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
            SELECT id, completed_at
            FROM english_review_round_items
            WHERE id = ? AND round_id = ? AND user_id = ? AND sentence_id = ?
            """,
            (round_item_id, int(current["id"]), user_id, sentence_id),
        ).fetchone()
    else:
        target = conn.execute(
            """
            SELECT id, completed_at
            FROM english_review_round_items
            WHERE round_id = ? AND user_id = ? AND sentence_id = ?
              AND COALESCE(completed_at, '') = ''
            ORDER BY position
            LIMIT 1
            """,
            (int(current["id"]), user_id, sentence_id),
        ).fetchone()
    if not target:
        return {
            **_completion_state(conn, current, None),
            "round_expired": bool(round_item_id),
        }
    if target["completed_at"]:
        return _completion_state(conn, current, target)
    item_id = int(target["id"])
    cursor = conn.execute(
        """
        UPDATE english_review_round_items
        SET completed_at = ?, updated_at = ?
        WHERE id = ? AND COALESCE(completed_at, '') = ''
        """,
        (now_text, now_text, item_id),
    )
    return _completion_state(conn, current, target, newly_completed=cursor.rowcount > 0)
