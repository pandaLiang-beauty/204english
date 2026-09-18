from __future__ import annotations

import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.english import repository, review_rounds
from app.english.schema import initialize_schema
from app.platform import db


@contextmanager
def _review_database():
    original_path, original_now = db.DB_PATH, review_rounds._utc_now
    clock = [datetime(2026, 9, 10, 2, tzinfo=timezone.utc)]
    try:
        with tempfile.TemporaryDirectory() as directory:
            db.DB_PATH = Path(directory) / "study.db"
            review_rounds._utc_now = lambda: clock[0]
            db.initialize_database()
            initialize_schema()
            with db.get_connection() as conn:
                conn.execute("INSERT INTO users(id, username, password_hash) VALUES (1, 'test', 'test')")
            yield clock
    finally:
        db.DB_PATH, review_rounds._utc_now = original_path, original_now


def _insert_sentences(first: int, last: int, created_at: str = "2026-09-09T00:00:00+00:00"):
    with db.get_connection() as conn:
        conn.executemany(
            "INSERT INTO english_sentences(id, text, created_at) VALUES (?, ?, ?)",
            [(identifier, f"Review sentence {identifier}.", created_at) for identifier in range(first, last + 1)],
        )


def check_review_round_length_preserves_progress_without_daily_limits() -> None:
    for total, expected in ((0, 1), (1, 1), (99, 1), (100, 1), (101, 2), (1000, 10), (1041, 11), (1100, 11), (1101, 12)):
        assert review_rounds.round_length_days(total) == expected, (total, expected)

    with _review_database() as clock:
        _insert_sentences(1, 710)
        schedule = [
            {"sentence_id": identifier, "repeat_index": repeat_index, "repeat_total": 2 if identifier <= 331 else 1}
            for repeat_index, identifiers in ((1, range(1, 711)), (2, range(1, 332)))
            for identifier in identifiers
        ]
        with db.get_connection() as conn:
            first, created = review_rounds.ensure_active_round(conn, user_id=1, schedule=schedule)
        assert created and first["expires_at"] == "2026-09-21T00:00:00+00:00", first
        round_id = int(first["id"])
        with db.get_connection() as conn:
            conn.execute("UPDATE english_review_rounds SET expires_at = '2026-09-17T00:00:00+00:00'")
            conn.execute(
                """UPDATE english_review_round_items SET completed_at = CASE
                    WHEN position <= 7 THEN '2026-09-11T01:00:00+00:00'
                    WHEN position <= 41 THEN '2026-09-12T01:00:00+00:00'
                    WHEN position <= 70 THEN '2026-09-13T01:00:00+00:00'
                    ELSE '2026-09-14T01:00:00+00:00' END
                    WHERE position <= 117"""
            )
            before_items = [dict(row) for row in conn.execute("SELECT * FROM english_review_round_items ORDER BY id")]
            before_sentences = [dict(row) for row in conn.execute("SELECT * FROM english_sentences ORDER BY id")]

        clock[0] = datetime(2026, 9, 15, 2, tzinfo=timezone.utc)
        migrated = repository.advance_due_review_rounds()
        assert migrated == [{"user_id": 1, "round_id": round_id, "created": False}], migrated
        with db.get_connection() as conn:
            assert [dict(row) for row in conn.execute("SELECT * FROM english_review_round_items ORDER BY id")] == before_items
            assert [dict(row) for row in conn.execute("SELECT * FROM english_sentences ORDER BY id")] == before_sentences
            current = dict(conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (round_id,)).fetchone())
        assert current["started_at"] == first["started_at"], current
        assert current["expires_at"] == "2026-09-21T00:00:00+00:00", current

        loaded = repository.list_sentences(user_id=1, page_size=200, resume=True)
        assert loaded["total"] == loaded["review_round"]["available"] == 1041, loaded["review_round"]
        assert loaded["review_round"]["completed"] == 117, loaded["review_round"]
        assert loaded["review_round"]["available_remaining"] == 924, loaded["review_round"]
        assert len(loaded["items"]) == 200, len(loaded["items"])

        # More than 100 completions on one study day must remain possible.
        for item in before_items[117:218]:
            result = repository.review_sentence(user_id=1, sentence_id=item["sentence_id"], round_item_id=item["id"])
            assert result["review_round_item_completed"] is True, result
            assert result["review_round_next_at"] == "", result
        # Later pages and a second appearance are also immediately available.
        later_item = before_items[900]
        later = repository.review_sentence(user_id=1, sentence_id=later_item["sentence_id"], round_item_id=later_item["id"])
        assert later["review_round_item_completed"] is True, later
        duplicate = repository.review_sentence(user_id=1, sentence_id=later_item["sentence_id"], round_item_id=later_item["id"])
        assert duplicate["review_round_item_completed"] is False, duplicate
        refreshed = repository.list_sentences(user_id=1, page_size=200, resume=True)
        assert refreshed["review_round"]["completed"] == 219, refreshed["review_round"]
        assert refreshed["review_round"]["available_remaining"] == 822, refreshed["review_round"]

        clock[0] = datetime(2026, 9, 17, tzinfo=timezone.utc)
        unchanged = repository.advance_due_review_rounds()
        assert unchanged[0]["round_id"] == round_id and unchanged[0]["created"] is False, unchanged
        clock[0] = datetime(2026, 9, 21, tzinfo=timezone.utc)
        rotated = repository.advance_due_review_rounds()
        assert rotated[0]["round_id"] != round_id and rotated[0]["created"] is True, rotated
        with db.get_connection() as conn:
            assert conn.execute("SELECT status FROM english_review_rounds WHERE id = ?", (round_id,)).fetchone()[0] == "expired"
            assert conn.execute("SELECT COUNT(*) FROM english_review_round_items WHERE round_id = ? AND completed_at <> ''", (round_id,)).fetchone()[0] == 219


def check_review_round_catch_up_uses_each_snapshot_length() -> None:
    with _review_database() as clock:
        _insert_sentences(1, 100)
        initial = repository.advance_due_review_rounds()
        _insert_sentences(101, 201, "2026-09-10T12:00:00+00:00")
        _insert_sentences(202, 202, "2026-09-18T12:00:00+00:00")
        clock[0] = datetime(2026, 9, 19, 2, tzinfo=timezone.utc)
        caught_up = repository.advance_due_review_rounds()
        assert caught_up[0]["round_id"] != initial[0]["round_id"], caught_up
        with db.get_connection() as conn:
            current = dict(conn.execute("SELECT * FROM english_review_rounds WHERE status = 'active'").fetchone())
            members = {row[0] for row in conn.execute("SELECT sentence_id FROM english_review_round_items WHERE round_id = ?", (current["id"],))}
            assert conn.execute("SELECT COUNT(*) FROM english_review_rounds").fetchone()[0] == 2
        # One day initially, then three-day cycles: 11th, 14th, 17th, 20th.
        assert current["started_at"] == "2026-09-17T00:00:00+00:00", current
        assert current["expires_at"] == "2026-09-20T00:00:00+00:00", current
        assert len(members) == 201 and 202 not in members, members
        unchanged = repository.advance_due_review_rounds()
        assert unchanged[0]["created"] is False and unchanged[0]["round_id"] == current["id"], unchanged

        clock[0] = datetime(2026, 9, 20, tzinfo=timezone.utc)
        following = repository.advance_due_review_rounds()
        with db.get_connection() as conn:
            assert conn.execute("SELECT 1 FROM english_review_round_items WHERE round_id = ? AND sentence_id = 202", (following[0]["round_id"],)).fetchone()


def check_review_round_deadline_is_frozen_and_early_completion_still_works() -> None:
    with _review_database() as clock:
        _insert_sentences(1, 101)
        initial = repository.advance_due_review_rounds()
        round_id = initial[0]["round_id"]
        assert repository.delete_sentence(sentence_id=101)
        _insert_sentences(102, 202, "2026-09-10T01:00:00+00:00")
        same = repository.advance_due_review_rounds()
        assert same[0]["round_id"] == round_id and same[0]["created"] is False, same
        loaded = repository.list_sentences(user_id=1, page_size=200)
        assert loaded["total"] == 100, loaded["total"]
        assert loaded["review_round"]["expires_at"] == "2026-09-12T00:00:00+00:00", loaded["review_round"]
        with db.get_connection() as conn:
            conn.execute("UPDATE english_review_round_items SET completed_at = ? WHERE round_id = ? AND sentence_id <= 100", (clock[0].isoformat(), round_id))
        waiting = repository.list_sentences(user_id=1, page_size=200)
        assert waiting["review_round"]["is_completed"] is True, waiting["review_round"]
        assert waiting["review_round"]["next_round_at"] == "2026-09-11T00:00:00+00:00", waiting["review_round"]
        clock[0] = datetime(2026, 9, 11, tzinfo=timezone.utc)
        following = repository.advance_due_review_rounds()
        assert following[0]["created"] is True and following[0]["round_id"] != round_id, following
        with db.get_connection() as conn:
            old = conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (round_id,)).fetchone()
            assert old["status"] == "completed", dict(old)
