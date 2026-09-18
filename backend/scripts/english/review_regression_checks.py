from __future__ import annotations

import asyncio
import errno
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.english import audio_generation, repository, review_rounds
from app.english.schema import initialize_schema
from app.english.word_play_history import reconcile_word_play_totals
from app.platform import db
from scripts.english.import_english_tts_review import _import_rows
from scripts.english.review_round_checks import _insert_sentences, _review_database


def check_completion_retries_return_authoritative_state() -> None:
    with _review_database() as clock:
        _insert_sentences(1, 2)
        schedule = [
            {"sentence_id": 1, "repeat_index": 1, "repeat_total": 2},
            {"sentence_id": 2},
            {"sentence_id": 1, "repeat_index": 2, "repeat_total": 2},
        ]
        with db.get_connection() as conn:
            state = review_rounds.queue_state(conn, user_id=1, schedule=schedule, page=1, page_size=20, resume=False)
        records = state["records"]
        item_id = records[0]["id"]
        # The first request commits; all concurrent retries must report the
        # persisted state without writing another completion or event.
        first = repository.review_sentence(user_id=1, sentence_id=1, round_item_id=item_id)
        with ThreadPoolExecutor(max_workers=4) as pool:
            retries = list(pool.map(lambda _: repository.review_sentence(user_id=1, sentence_id=1, round_item_id=item_id), range(8)))
        assert first["review_round_item_completed"] is True, first
        for retry in retries:
            assert retry["review_round_item_completed"] is False, retry
            assert retry["review_round_item_is_completed"] is True, retry
            assert retry["review_round"]["completed"] == 1, retry
            assert retry["review_round"]["remaining"] == 2, retry
            assert retry["completion_count"] == 1, retry
        with db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM english_review_events WHERE event_type = 'sentence_review'").fetchone()[0] == 1
            assert not conn.execute("SELECT completed_at FROM english_review_round_items WHERE id = ?", (records[2]["id"],)).fetchone()[0]
        for item in records[1:]:
            completed = repository.review_sentence(user_id=1, sentence_id=item["sentence_id"], round_item_id=item["id"])
        expected_next = completed["review_round_next_at"]
        clock[0] += timedelta(hours=3)
        retry = repository.review_sentence(user_id=1, sentence_id=1, round_item_id=records[2]["id"])
        assert retry["review_round"]["is_completed"] is True, retry
        assert retry["review_round_next_at"] == expected_next, retry
        assert retry["completion_count"] == 2, retry
        clock[0] += timedelta(days=1)
        with db.get_connection() as conn:
            new = review_rounds.queue_state(conn, user_id=1, schedule=schedule, page=1, page_size=20, resume=False)
        stale = repository.review_sentence(user_id=1, sentence_id=1, round_item_id=item_id)
        assert stale["review_round_expired"] is True, stale
        assert new["round"]["id"] != state["round"]["id"]
        with db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM english_review_round_items WHERE round_id = ? AND completed_at <> ''", (new["round"]["id"],)).fetchone()[0] == 0
        clock[0] += timedelta(days=2)
        for _ in range(2):
            expired = repository.review_sentence(user_id=1, sentence_id=1, round_item_id=new["records"][0]["id"])
            assert expired["review_round_expired"] is True, expired


def check_word_play_history_survives_focus_edits_and_repair() -> None:
    with _review_database():
        sentence = repository.create_sentence(text="An **alpha** and **beta** example.", word_translations={"alpha": "甲", "beta": "乙"})
        sentence_id = sentence["id"]
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE english_sentences SET word_play_counts_json = ?, word_play_total = 11 WHERE id = ?",
                (json.dumps({"Alpha": 10, "beta": 1}), sentence_id),
            )
            for word in ["alpha"] * 2 + ["beta"] * 4 + ["removed"] * 3:
                repository._record_event(conn, user_id=1, event_type="word_play", sentence_id=sentence_id, word=word)
        initialize_schema()
        repaired = repository.get_sentence(sentence_id)
        assert repaired["word_play_total"] == 17, repaired  # 9 tracked + 8 retained legacy.
        assert repaired["focus_word_play_total"] == 11, repaired
        with db.get_connection() as conn:
            assert reconcile_word_play_totals(conn) == []
        assert repository.stats(user_id=1)["legacy"]["word_reviews"] == 8
        unmarked = repository.toggle_focus_word(user_id=1, sentence_id=sentence_id, word="alpha", action="unmark")
        assert unmarked["word_play_total"] == 17, unmarked
        assert unmarked["focus_word_play_total"] == 1, unmarked
        played = repository.record_word_play(user_id=1, sentence_id=sentence_id, word="beta")
        assert played["word_play_total"] == 18, played
        edited = repository.update_sentence(sentence_id=sentence_id, text="An alpha and beta example.")
        assert edited["word_play_total"] == 18, edited
        assert edited["focus_word_play_total"] == 0, edited
        repository.toggle_focus_word(user_id=1, sentence_id=sentence_id, word="alpha", action="mark")
        played = repository.record_word_play(user_id=1, sentence_id=sentence_id, word="alpha")
        assert played["word_play_total"] == 19, played
        assert played["focus_word_play_total"] == 1, played
        reused = repository.create_sentences_bulk([{"text": "An **alpha** and **beta** example.", "word_translations": {"beta": "乙"}}])
        assert reused["reused"] == 1, reused
        assert reused["items"][0]["word_play_total"] == 19, reused
        repository.reconcile_sentence_focus_state()
        initialize_schema()
        summary = repository.stats(user_id=1)
        assert summary["word_reviews"] == 19 and summary["legacy"]["word_reviews"] == 8, summary
        repository.delete_sentence(sentence_id=sentence_id)
        assert repository.stats(user_id=1)["word_reviews"] == 19
        assert repository.review_heatmap(user_id=1)["lifetime_word_reviews"] == 19


def check_word_play_history_preserves_imports_and_concurrent_writes() -> None:
    with _review_database():
        sentence = repository.create_sentence(text="A **focus** example.", word_translations={"focus": "重点"})
        sentence_id = sentence["id"]
        with db.get_connection() as conn:
            conn.execute("UPDATE english_sentences SET word_play_total = 50, word_play_counts_json = '{\"focus\": 5}' WHERE id = ?", (sentence_id,))
        initialize_schema()
        assert repository.get_sentence(sentence_id)["word_play_total"] == 50

        def play_and_reconcile(_):
            repository.record_word_play(user_id=1, sentence_id=sentence_id, word="focus")
            with db.get_connection() as conn:
                reconcile_word_play_totals(conn)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(play_and_reconcile, range(20)))
        played = repository.get_sentence(sentence_id)
        assert played["word_play_total"] == 70, played
        assert played["focus_word_play_total"] == 25, played
        # Reimporting a smaller legacy aggregate may refresh content but cannot
        # lower the lifetime counter already accumulated in this repository.
        source = {
            "id": sentence_id, "text": sentence["text"], "word_translations": {"focus": "重点"},
            "word_tips": {}, "word_pronunciation_counts": {"focus": 2}, "audio_path": "",
            "review_count": 0, "word_review_total": 2, "sentence_translation": "", "deleted_at": "",
            "created_at": "2026-09-09T00:00:00+00:00", "updated_at": "2026-09-09T00:00:00+00:00",
        }
        _import_rows([source])
        assert repository.get_sentence(sentence_id)["word_play_total"] == 70
        source["id"] = 2
        source["word_review_total"] = 30
        _import_rows([source])
        assert repository.get_sentence(2)["word_play_total"] == 30


def check_passage_sentence_boundary_parity_and_sync() -> None:
    fixture_path = Path(__file__).resolve().parents[3] / "fixtures" / "passage_sentence_cases.json"
    fixtures = json.loads(fixture_path.read_text())
    with _review_database():
        for fixture in fixtures:
            sentences = repository._split_marked_passage_sentences(fixture["text"])
            candidates = repository._marked_passage_sentence_candidates(fixture["text"])
            assert sentences == fixture["sentences"], (fixture["name"], sentences)
            assert [item["text"] for item in candidates] == fixture["candidates"], (fixture["name"], candidates)
            passage = repository.create_passage(user_id=1, body_text=fixture["text"])
            last_index = len(candidates) - 1
            result = repository.sync_passage_sentences(passage_id=passage["id"], user_id=1, candidate_indexes=[last_index])
            assert len(result["sentences"]) == 1, result
            assert result["sentences"][0]["text"] == candidates[last_index]["text"], (fixture["name"], result)
            again = repository.sync_passage_sentences(passage_id=passage["id"], user_id=1, candidate_indexes=[last_index])
            assert again["inserted"] == 0 and again["reused"] == 1, again


def check_missing_word_audio_recovers_independently() -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        rows = [
            {"id": 710, "audio_status": "ready", "word_translations_json": '{"trapping": "捕获", "present": "已有"}'},
            {"id": 711, "audio_status": "ready", "word_translations_json": '{"ready": "就绪"}'},
            {"id": 712, "audio_status": "pending", "word_translations_json": '{}'},
        ]
        path_for = lambda sentence_id, word: target / f"{sentence_id}_{word}.mp3"
        path_for(710, "present").write_bytes(b"existing")
        path_for(711, "ready").write_bytes(b"existing")
        generated = []

        async def save(word, path, *, voice):
            generated.append(word)
            path.write_bytes(b"generated")

        def generate_words(ids):
            asyncio.run(audio_generation.generate_word_audio_for_rows([row for row in rows if row["id"] in ids]))

        with (
            patch.object(repository, "reconcile_sentence_audio_metadata", return_value={}),
            patch.object(audio_generation, "_load_sentence_rows", return_value=rows),
            patch.object(audio_generation, "_word_audio_path", side_effect=path_for),
            patch.object(audio_generation, "_edge_tts_save", side_effect=save),
            patch.object(audio_generation, "generate_word_audio_for_sentence_ids_best_effort", side_effect=generate_words) as words,
            patch.object(audio_generation, "generate_sentence_audio_for_sentence_ids_best_effort") as sentences,
        ):
            audio_generation.resume_pending_audio_generation_best_effort()
            words.assert_called_once_with([710])
            sentences.assert_called_once_with([712])
            assert generated == ["trapping"], generated
            assert path_for(710, "present").read_bytes() == b"existing"
            rows[2]["audio_status"] = "ready"
            words.reset_mock()
            sentences.reset_mock()
            audio_generation.resume_pending_audio_generation_best_effort()
            words.assert_not_called()
            sentences.assert_not_called()
            # Simulate a failed/empty word asset with every sentence ready.
            path_for(710, "trapping").write_bytes(b"")
            audio_generation.resume_pending_audio_generation_best_effort()
            words.assert_called_once_with([710])
            sentences.assert_not_called()


def check_word_audio_retries_unreachable_ipv6_atomically() -> None:
    import edge_tts
    import socket

    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "trapping.mp3"
        destination.write_bytes(b"existing audio")
        calls = []

        class Communicate:
            def __init__(self, text, *, voice, connector=None):
                calls.append((text, voice, connector))
                self.connector = connector

            async def save(self, target):
                Path(target).write_bytes(b"partial")
                assert destination.read_bytes() == b"existing audio"
                if self.connector is None:
                    raise OSError(errno.ENETUNREACH, "IPv6 network is unreachable")
                assert self.connector.family == socket.AF_INET
                Path(target).write_bytes(b"complete audio")

        with patch.object(edge_tts, "Communicate", Communicate):
            asyncio.run(audio_generation._edge_tts_save("trapping", destination, voice="en-US-AriaNeural"))
        assert [(text, voice) for text, voice, _ in calls] == [("trapping", "en-US-AriaNeural")] * 2
        assert calls[1][2].closed
        assert destination.read_bytes() == b"complete audio"
        assert list(Path(directory).iterdir()) == [destination]


REGRESSION_CHECKS = (
    check_completion_retries_return_authoritative_state,
    check_word_play_history_survives_focus_edits_and_repair,
    check_word_play_history_preserves_imports_and_concurrent_writes,
    check_passage_sentence_boundary_parity_and_sync,
    check_missing_word_audio_recovers_independently,
    check_word_audio_retries_unreachable_ipv6_atomically,
)
