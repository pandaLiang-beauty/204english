from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.english import repository, review_rounds
from app.english.ranking import play_exposure, rank_sentences_for_review
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


def check_review_round_length_and_progress_without_daily_limits() -> None:
    for total, expected in ((0, 1), (1, 1), (99, 1), (100, 1), (101, 2), (1000, 10), (1041, 11), (1100, 11), (1101, 12)):
        assert review_rounds.round_length_days(total) == expected, (total, expected)

    with _review_database() as clock:
        _insert_sentences(1, 710)
        schedule = [
            {"sentence_id": identifier, "repeat_index": 1, "repeat_total": 1}
            for identifier in range(1, 711)
        ]
        with db.get_connection() as conn:
            first, created = review_rounds.ensure_active_round(conn, user_id=1, schedule=schedule)
        assert created and first["expires_at"] == "2026-09-18T00:00:00+00:00", first
        round_id = int(first["id"])
        with db.get_connection() as conn:
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
            after_items = [dict(row) for row in conn.execute("SELECT * FROM english_review_round_items ORDER BY id")]
            assert {int(row["sentence_id"]) for row in after_items} == {int(row["sentence_id"]) for row in before_items}
            assert sum(bool(row["completed_at"]) for row in after_items) == 117
            assert all(int(row["repeat_total"]) == 1 for row in after_items)
            assert [dict(row) for row in conn.execute("SELECT * FROM english_sentences ORDER BY id")] == before_sentences
            current = dict(conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (round_id,)).fetchone())
        assert current["started_at"] == first["started_at"], current
        # Refreshes and the scheduler must not recalculate a frozen deadline.
        assert current["expires_at"] == "2026-09-18T00:00:00+00:00", current

        loaded = repository.list_sentences(user_id=1, page_size=200, resume=True)
        assert loaded["total"] == loaded["review_round"]["available"] == 710, loaded["review_round"]
        assert loaded["review_round"]["completed"] == 117, loaded["review_round"]
        assert loaded["review_round"]["available_remaining"] == 593, loaded["review_round"]
        assert len(loaded["items"]) == 200, len(loaded["items"])

        # More than 100 completions on one study day must remain possible.
        for item in before_items[117:218]:
            result = repository.review_sentence(user_id=1, sentence_id=item["sentence_id"], round_item_id=item["id"])
            assert result["review_round_item_completed"] is True, result
            assert result["review_round_next_at"] == "", result
        # Later pages remain immediately available, while a completed item is
        # authoritative on retries and is not counted twice.
        later_item = before_items[500]
        later = repository.review_sentence(user_id=1, sentence_id=later_item["sentence_id"], round_item_id=later_item["id"])
        assert later["review_round_item_completed"] is True, later
        duplicate = repository.review_sentence(user_id=1, sentence_id=later_item["sentence_id"], round_item_id=later_item["id"])
        assert duplicate["review_round_item_completed"] is False and duplicate["review_round_item_is_completed"] is True, duplicate
        refreshed = repository.list_sentences(user_id=1, page_size=200, resume=True)
        assert refreshed["review_round"]["completed"] == 219, refreshed["review_round"]
        assert refreshed["review_round"]["available_remaining"] == 491, refreshed["review_round"]

        clock[0] = datetime(2026, 9, 17, tzinfo=timezone.utc)
        unchanged = repository.advance_due_review_rounds()
        assert unchanged[0]["round_id"] == round_id and unchanged[0]["created"] is False, unchanged
        clock[0] = datetime(2026, 9, 18, tzinfo=timezone.utc)
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
        # Catch-up freezes each snapshot at its boundary. The sentence created
        # on the 18th is not part of the snapshot beginning that morning.
        assert current["started_at"] == "2026-09-17T00:00:00+00:00", current
        assert current["expires_at"] == "2026-09-20T00:00:00+00:00", current
        assert len(members) == 201 and 202 not in members, members
        unchanged = repository.advance_due_review_rounds()
        assert unchanged[0]["created"] is False and unchanged[0]["round_id"] == current["id"], unchanged

        clock[0] = datetime(2026, 9, 22, tzinfo=timezone.utc)
        following = repository.advance_due_review_rounds()
        with db.get_connection() as conn:
            assert conn.execute("SELECT 1 FROM english_review_round_items WHERE round_id = ? AND sentence_id = 202", (following[0]["round_id"],)).fetchone()


def check_review_round_freeze_tracks_visible_membership_and_early_completion() -> None:
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
        assert all(int(item["id"]) < 102 for item in loaded["items"]), loaded["items"]
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE english_review_round_items SET completed_at = ? WHERE round_id = ?",
                (clock[0].isoformat(), round_id),
            )
        waiting = repository.list_sentences(user_id=1, page_size=200)
        assert waiting["review_round"]["is_completed"] is True, waiting["review_round"]
        assert waiting["review_round"]["next_round_at"] == "2026-09-11T00:00:00+00:00", waiting["review_round"]
        clock[0] = datetime(2026, 9, 11, tzinfo=timezone.utc)
        following = repository.advance_due_review_rounds()
        assert following[0]["created"] is True and following[0]["round_id"] != round_id, following
        with db.get_connection() as conn:
            old = conn.execute("SELECT * FROM english_review_rounds WHERE id = ?", (round_id,)).fetchone()
            assert old["status"] == "completed", dict(old)


def check_frozen_round_positions_survive_refresh_completion_scheduler_and_restart() -> None:
    with _review_database() as clock:
        _insert_sentences(1, 120)
        initial = repository.advance_due_review_rounds()
        round_id = int(initial[0]["round_id"])
        first_load = repository.list_sentences(user_id=1, page_size=200, resume=False)
        with db.get_connection() as conn:
            before = [dict(row) for row in conn.execute(
                "SELECT * FROM english_review_round_items WHERE round_id = ? ORDER BY position",
                (round_id,),
            )]
        assert len(before) == 120, before

        _insert_sentences(121, 121, "2026-09-10T03:00:00+00:00")
        refreshed = repository.list_sentences(user_id=1, page_size=200, resume=False)
        assert refreshed["total"] == 120, refreshed
        assert refreshed["review_round"]["id"] == round_id, refreshed["review_round"]
        assert 121 not in {int(item["id"]) for item in refreshed["items"]}, refreshed["items"]
        with db.get_connection() as conn:
            after_refresh = [dict(row) for row in conn.execute(
                "SELECT * FROM english_review_round_items WHERE round_id = ? ORDER BY position",
                (round_id,),
            )]
        assert after_refresh == before, after_refresh

        target = first_load["items"][12]
        completed = repository.review_sentence(
            user_id=1,
            sentence_id=int(target["id"]),
            round_item_id=int(target["review_round_item_id"]),
        )
        assert completed["review_round_item_completed"] is True, completed
        with db.get_connection() as conn:
            after_completion = [dict(row) for row in conn.execute(
                "SELECT * FROM english_review_round_items WHERE round_id = ? ORDER BY position",
                (round_id,),
            )]
        assert [(row["id"], row["sentence_id"], row["position"]) for row in after_completion] == [
            (row["id"], row["sentence_id"], row["position"]) for row in before
        ]

        clock[0] = clock[0].replace(hour=4)
        scheduled = repository.advance_due_review_rounds()
        assert scheduled[0]["round_id"] == round_id and scheduled[0]["created"] is False, scheduled
        initialize_schema()
        restarted = repository.list_sentences(user_id=1, page_size=200, resume=False)
        assert restarted["review_round"]["id"] == round_id, restarted["review_round"]
        with db.get_connection() as conn:
            after_restart = [dict(row) for row in conn.execute(
                "SELECT * FROM english_review_round_items WHERE round_id = ? ORDER BY position",
                (round_id,),
            )]
        assert after_restart == after_completion, after_restart

        deleted_id = int(restarted["items"][20]["id"])
        assert repository.delete_sentence(sentence_id=deleted_id)
        visible = repository.list_sentences(user_id=1, page_size=200, resume=False)
        assert visible["total"] == 119, visible
        assert deleted_id not in {int(item["id"]) for item in visible["items"]}, visible["items"]
        with db.get_connection() as conn:
            after_delete = [dict(row) for row in conn.execute(
                "SELECT * FROM english_review_round_items WHERE round_id = ? ORDER BY position",
                (round_id,),
            )]
        assert [(row["id"], row["position"]) for row in after_delete] == [
            (row["id"], row["position"]) for row in after_completion
        ]

        clock[0] = datetime(2026, 9, 12, tzinfo=timezone.utc)
        rotated = repository.advance_due_review_rounds()
        assert rotated[0]["created"] is True and rotated[0]["round_id"] != round_id, rotated
        with db.get_connection() as conn:
            next_members = {
                int(row["sentence_id"])
                for row in conn.execute(
                    "SELECT sentence_id FROM english_review_round_items WHERE round_id = ?",
                    (rotated[0]["round_id"],),
                )
            }
        assert 121 in next_members and deleted_id not in next_members, next_members


def check_review_priority_ranking_groups_and_five_x_formula() -> None:
    def row(identifier: int, plays: int, text: str = "", words: dict | None = None) -> dict:
        return {
            "id": identifier,
            "text": text,
            "word_translations_json": json.dumps(words or {}),
            "word_play_counts_json": "{}",
            "review_count": plays,
            "word_play_total": 0,
            "completion_count": 0,
        }

    rows = [
        row(1, 10),
        row(2, 1),
        row(3, 10),
        row(4, 0),
        row(5, 6),
        row(6, 6),
    ]
    ranked = rank_sentences_for_review(
        rows,
        previous_completed_sentence_ids={1, 4},
        previous_sentence_plays={1: 4, 2: 1, 5: 1, 6: 1},
    )
    ordered_ids = [int(item[0]["id"]) for item in ranked]
    assert ordered_ids == [2, 5, 6, 3, 1, 4], ordered_ids
    metrics_by_id = {int(item[0]["id"]): item[1] for item in ranked}
    assert metrics_by_id[1]["priority_score"] == 14.0, metrics_by_id[1]
    assert metrics_by_id[2]["priority_score"] == 5.0, metrics_by_id[2]
    assert metrics_by_id[3]["priority_score"] == -10.0, metrics_by_id[3]
    assert metrics_by_id[5]["priority_score"] == 0.0, metrics_by_id[5]

    word_row = {
        "id": 7,
        "text": "**alpha** appears here.",
        "word_translations_json": '{"alpha": "alpha meaning"}',
        "word_play_counts_json": '{"alpha": 5}',
        "review_count": 0,
        "word_play_total": 5,
        "completion_count": 0,
    }
    word_ranked = rank_sentences_for_review(
        [word_row],
        previous_word_plays={7: {"alpha": 2}},
    )
    word_metrics = word_ranked[0][1]
    expected_previous = play_exposure(0, {"alpha": 2})
    expected_historical = play_exposure(0, {"alpha": 3})
    assert abs(word_metrics["previous_exposure"] - expected_previous) < 1e-6, word_metrics
    assert abs(word_metrics["historical_exposure"] - expected_historical) < 1e-6, word_metrics
    assert abs(word_metrics["priority_score"] - (5 * expected_previous - expected_historical)) < 1e-6, word_metrics


def check_review_events_record_their_round_and_item() -> None:
    with _review_database():
        sentence = repository.create_sentence(
            text="An **alpha** sentence records its round.",
            word_translations={"alpha": "alpha meaning"},
        )
        repository.advance_due_review_rounds()
        loaded = repository.list_sentences(user_id=1, page_size=20, resume=False)
        item = loaded["items"][0]
        round_id = int(loaded["review_round"]["id"])
        item_id = int(item["review_round_item_id"])
        repository.review_sentence(
            user_id=1,
            sentence_id=int(sentence["id"]),
            event_type="sentence_play",
            round_item_id=item_id,
        )
        repository.record_word_play(user_id=1, sentence_id=int(sentence["id"]), word="alpha")
        repository.review_sentence(
            user_id=1,
            sentence_id=int(sentence["id"]),
            event_type="sentence_review",
            round_item_id=item_id,
        )
        with db.get_connection() as conn:
            events = conn.execute(
                "SELECT event_type, metadata_json FROM english_review_events ORDER BY id"
            ).fetchall()
        assert [event["event_type"] for event in events] == ["sentence_play", "word_play", "sentence_review"]
        for event in events:
            metadata = json.loads(event["metadata_json"])
            assert metadata["round_id"] == round_id, metadata
            assert metadata["round_item_id"] == item_id, metadata


def check_round_play_context_ignores_previous_round_tail_events() -> None:
    with _review_database() as clock:
        clock[0] = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
        _insert_sentences(1, 1)
        with db.get_connection() as conn:
            first_id = int(conn.execute(
                """
                INSERT INTO english_review_rounds(
                    user_id, status, started_at, expires_at, ended_at, end_reason, created_at, updated_at
                ) VALUES (1, 'expired', '2026-09-10T00:00:00+00:00',
                          '2026-09-11T00:00:00+00:00', '2026-09-11T09:00:00+00:00',
                          'expired', '2026-09-10T00:00:02+00:00', '2026-09-11T09:00:00+00:00')
                """
            ).lastrowid)
            second_id = int(conn.execute(
                """
                INSERT INTO english_review_rounds(
                    user_id, status, started_at, expires_at, previous_round_id, created_at, updated_at
                ) VALUES (1, 'active', '2026-09-11T00:00:00+00:00',
                          '2026-09-12T00:00:00+00:00', ?, '2026-09-11T09:00:00+00:00',
                          '2026-09-11T09:00:00+00:00')
                """,
                (first_id,),
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO english_review_events(
                    user_id, sentence_id, event_type, word, metadata_json, created_at
                ) VALUES
                    (1, 1, 'sentence_play', '', '{}', '2026-09-11T03:00:00+00:00'),
                    (1, 1, 'sentence_play', '', '{}', '2026-09-11T10:00:00+00:00'),
                    (1, 1, 'word_play', 'alpha', '{}', '2026-09-11T11:00:00+00:00')
                """
            )
            context = review_rounds.round_play_context(conn, user_id=1, round_id=second_id)
        assert context["sentence_plays"] == {1: 1}, context
        assert context["word_plays"] == {1: {"alpha": 1}}, context
