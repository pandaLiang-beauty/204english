from __future__ import annotations

import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.english import audio_generation, repository  # noqa: E402
from app.english import translation_generation  # noqa: E402
from app.english import translator  # noqa: E402
from app.english.ranking import sentence_word_network_metrics  # noqa: E402
from app.english.schema import initialize_schema as initialize_english_schema  # noqa: E402
from app.platform import db as platform_db  # noqa: E402
from app.platform.db import get_connection, initialize_database  # noqa: E402


def _decode_json(raw: object, fallback):
    try:
        return json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return fallback


def check_sentence_integrity() -> None:
    with get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, text, word_translations_json, word_tips_json, word_play_counts_json "
                "FROM english_sentences WHERE COALESCE(deleted_at, '') = ''"
            ).fetchall()
        ]
        conn.execute("SELECT COUNT(*) FROM english_review_rounds").fetchone()
        conn.execute("SELECT COUNT(*) FROM english_review_round_items").fetchone()
    identities = [repository.sentence_identity_key(row["text"]) for row in rows]
    assert len(identities) == len(set(identities)), "duplicate active English sentence identity"
    for row in rows:
        translations = _decode_json(row.get("word_translations_json"), {})
        tips = _decode_json(row.get("word_tips_json"), {})
        counts = _decode_json(row.get("word_play_counts_json"), {})
        translation_keys = {
            repository._normalize_focus_word(key)
            for key in translations
        }
        marked_keys = {
            repository._normalize_focus_word(surface)
            for surface in repository._marked_word_surfaces(row["text"])
        }
        assert translation_keys == marked_keys, row["id"]
        assert all(repository._normalize_focus_word(key) in translation_keys for key in tips), row["id"]
        assert all(repository._normalize_focus_word(key) in translation_keys for key in counts), row["id"]
    today = repository.stats(user_id=1)["today"]
    assert "reviewed_sentences" in today, today
    assert int(today["reviewed_sentences"]) <= int(today["sentence_reviews"]), today


def check_audio_assets() -> None:
    with get_connection() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM english_sentences
                WHERE COALESCE(deleted_at, '') = ''
                  AND audio_status = 'ready'
                """
            ).fetchall()
        ]
    for row in rows:
        audio_path = str(row["audio_path"] or "").strip()
        assert audio_path, dict(row)
        assert str(row.get("audio_provider") or "").strip(), row["id"]
        assert str(row.get("audio_voice") or "").strip(), row["id"]
        assert str(row.get("audio_hash") or "").strip(), row["id"]
        local_path = repository.ENGLISH_AUDIO_DIR / Path(audio_path).name
        assert local_path.is_file() and local_path.stat().st_size > 0, {
            "sentence_id": int(row["id"]),
            "path": audio_path,
        }


def check_kokoro_voice_catalog() -> None:
    catalog = repository.sentence_audio_voice_catalog()
    kokoro_voices = [item for item in catalog if item["provider"] == "kokoro"]
    assert len(kokoro_voices) == 28, len(kokoro_voices)
    assert len({item["voice"] for item in kokoro_voices}) == 28
    assert all(item["available"] for item in kokoro_voices), [
        item["voice"] for item in kokoro_voices if not item["available"]
    ]
    assert audio_generation._kokoro_language_code("af_heart") == "a"
    assert audio_generation._kokoro_language_code("bf_emma") == "b"


def check_dedicated_ai_configuration() -> None:
    names = ("STUDY_ENGLISH_AI_BASE_URL", "STUDY_ENGLISH_AI_API_KEY", "STUDY_ENGLISH_AI_MODEL")
    original = {name: os.environ.get(name) for name in names}
    try:
        os.environ["STUDY_ENGLISH_AI_BASE_URL"] = "https://ai.example/v1"
        os.environ["STUDY_ENGLISH_AI_API_KEY"] = "test-key"
        os.environ["STUDY_ENGLISH_AI_MODEL"] = "provider/deepseek-v4-pro"
        options = translator._english_ai_options()
        assert options["base_url"] == "https://ai.example/v1", options
        assert options["api_key"] == "test-key", options
        assert options["model"] == "provider/deepseek-v4-pro", options
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_library_metadata() -> None:
    assert repository._stored_sentence_audio_identity(
        {
            "audio_path": "sentence_724_kokoro_af_heart.mp3",
            "audio_provider": "",
            "audio_voice": "",
        }
    ) == ("kokoro", "af_heart")
    assert repository._stored_sentence_audio_identity(
        {
            "audio_path": "sentence_724_kokoro_af_heart_deadbeefcafebabe.wav",
            "audio_provider": "",
            "audio_voice": "",
        }
    ) == ("kokoro", "af_heart")
    assert repository._stored_sentence_audio_identity(
        {
            "audio_path": "sentence_724_kokoro_af_heart.wav",
            "audio_provider": "edge",
            "audio_voice": "custom-voice",
        }
    ) == ("edge", "custom-voice")

    rows = [
        {
            "id": 1,
            "text": "A **shared** word appears here.",
            "word_translations_json": '{"shared":"句中：共同的"}',
            "word_play_counts_json": "{}",
            "review_count": 0,
        },
        {
            "id": 2,
            "text": "This is another **shared** example.",
            "word_translations_json": '{"shared":"句中：共同的"}',
            "word_play_counts_json": "{}",
            "review_count": 0,
        },
    ]
    metrics = sentence_word_network_metrics(rows)
    assert metrics[1]["linked_words"][0]["linked_sentences"] == 2, metrics
    assert metrics[2]["linked_words"][0]["key"] == "shared", metrics


def check_two_stage_translation_pipeline() -> None:
    sentence = "People often complain that **plastics** are too **durable**."
    responses = [
        {
            "sentence_translation": "人们抱怨塑料太耐用。",
            "sentence_segments": ["People often complain that plastics are too durable."],
            "translation_segments": ["人们抱怨塑料太耐用。"],
            "words": [
                {"word": "plastics", "base_translation": "塑料", "context_translation": "塑料", "tip": ""},
                {"word": "durable", "base_translation": "耐用的", "context_translation": "耐用的", "tip": ""},
            ],
        },
        {
            "sentence_translation": "人们常常抱怨塑料过于耐用。",
            "sentence_segments": ["People often complain that plastics are too durable."],
            "translation_segments": ["人们常常抱怨塑料过于耐用。"],
            "words": [
                {"word": "plastics", "base_translation": "塑料", "context_translation": "塑料制品", "tip": ""},
                {"word": "durable", "base_translation": "耐用的", "context_translation": "难以降解的", "tip": ""},
            ],
        },
    ]
    calls: list[list[dict]] = []
    original_chat = translator._chat_completion

    def fake_chat(messages, **_kwargs):
        calls.append(messages)
        return json.dumps(responses[len(calls) - 1], ensure_ascii=False)

    translator._chat_completion = fake_chat
    try:
        result = translator.translate_text(sentence, words=["plastics", "durable"])
    finally:
        translator._chat_completion = original_chat
    assert len(calls) == 2, len(calls)
    assert result["sentence_translation"] == "人们常常抱怨塑料过于耐用。", result
    assert result["word_translations"]["durable"].endswith("句中：难以降解的"), result

    failed_calls = 0

    def failing_chat(_messages, **_kwargs):
        nonlocal failed_calls
        failed_calls += 1
        raise translator.AIProviderError("AI 服务网络请求失败", "AI provider HTTP 500")

    translator._chat_completion = failing_chat
    try:
        try:
            translator.translate_text(sentence, words=["plastics", "durable"])
        except translator.AIProviderError:
            pass
        else:
            raise AssertionError("provider failure was unexpectedly accepted")
    finally:
        translator._chat_completion = original_chat
    assert failed_calls == 1, failed_calls


def check_edit_translation_invalidation() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            created = repository.create_sentence(
                text="The **old** sentence is here.",
                word_translations={"old": "本义：旧的；句中：旧的"},
                sentence_translation="旧句子在这里。",
                sentence_segments=["The old sentence is here."],
                translation_segments=["旧句子在这里。"],
            )
            updated = repository.update_sentence(
                sentence_id=int(created["id"]),
                text="The **new** sentence is here.",
                word_translations=created["word_translations"],
                sentence_translation=created["sentence_translation"],
                sentence_segments=created["sentence_segments"],
                translation_segments=created["translation_segments"],
            )
            assert updated and updated["translation_pending"] is True, updated
            assert updated["sentence_translation"] == "", updated
            assert updated["word_translations"] == {"new": ""}, updated
            result = {
                "sentence_translation": "新句子在这里。",
                "sentence_segments": ["The new sentence is here."],
                "translation_segments": ["新句子在这里。"],
                "word_translations": {"new": "本义：新的；句中：新的", "old": "不应写回"},
                "word_tips": {},
            }
            assert not translation_generation._apply_translation_if_still_missing(
                int(created["id"]),
                result,
                expected_text="stale source",
            )
            assert translation_generation._apply_translation_if_still_missing(
                int(created["id"]),
                result,
                expected_text="The **new** sentence is here.",
            )
            refreshed = repository.get_sentence(int(created["id"]))
            assert refreshed and refreshed["word_translations"] == {
                "new": "本义：新的；句中：新的"
            }, refreshed
    finally:
        platform_db.DB_PATH = original_path


def check_audio_voice_settings() -> None:
    original_path = platform_db.DB_PATH
    env_names = (
        "STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER",
        "STUDY_ENGLISH_EDGE_VOICE",
        "STUDY_ENGLISH_KOKORO_VOICE",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    try:
        os.environ["STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER"] = "edge"
        os.environ["STUDY_ENGLISH_EDGE_VOICE"] = "en-US-JennyNeural"
        os.environ["STUDY_ENGLISH_KOKORO_VOICE"] = "af_heart"
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()

            first = repository.create_sentence(text="The first voice setting example is ready.")
            assert first["audio_uses_global"] is True, first
            assert (first["audio_effective_provider"], first["audio_effective_voice"]) == (
                "edge",
                "en-US-JennyNeural",
            ), first

            settings = repository.set_global_sentence_audio_settings(provider="kokoro", voice="af_heart")
            assert settings["global"]["source"] == "database", settings
            second = repository.create_sentence(text="The second voice setting example is ready.")
            assert (second["audio_effective_provider"], second["audio_effective_voice"]) == (
                "kokoro",
                "af_heart",
            ), second

            overridden = repository.set_sentence_audio_override(
                sentence_id=int(first["id"]),
                provider="edge",
                voice="en-US-GuyNeural",
            )
            assert overridden and overridden["audio_uses_global"] is False, overridden
            assert overridden["audio_effective_voice"] == "en-US-GuyNeural", overridden

            repository.set_global_sentence_audio_settings(provider="edge", voice="en-US-AriaNeural")
            refreshed_override = repository.get_sentence(int(first["id"]))
            refreshed_global = repository.get_sentence(int(second["id"]))
            assert refreshed_override and refreshed_override["audio_effective_voice"] == "en-US-GuyNeural"
            assert refreshed_global and refreshed_global["audio_effective_voice"] == "en-US-AriaNeural"

            queued = repository.queue_global_sentence_audio_regeneration()
            assert queued["sentence_ids"] == [int(second["id"])], queued
            inherited = repository.set_sentence_audio_override(
                sentence_id=int(first["id"]),
                use_global=True,
            )
            assert inherited and inherited["audio_uses_global"] is True, inherited
            assert inherited["audio_effective_voice"] == "en-US-AriaNeural", inherited

            try:
                repository.validate_sentence_audio_identity("edge", "unsupported-voice")
            except ValueError:
                pass
            else:
                raise AssertionError("unsupported voice was accepted")
    finally:
        platform_db.DB_PATH = original_path
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_legacy_audio_metadata_reconciliation() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    env_names = ("STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER", "STUDY_ENGLISH_EDGE_VOICE")
    original_env = {name: os.environ.get(name) for name in env_names}
    try:
        os.environ["STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER"] = "edge"
        os.environ["STUDY_ENGLISH_EDGE_VOICE"] = "en-US-JennyNeural"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            repository.ENGLISH_AUDIO_DIR.mkdir(parents=True)
            initialize_database()
            initialize_english_schema()

            legacy = repository.create_sentence(text="A legacy sentence audio file remains usable.")
            stale = repository.create_sentence(text="A stale sentence audio file must be regenerated.")
            legacy_path = repository.ENGLISH_AUDIO_DIR / (
                f"sentence_{legacy['id']}_edge_en-US-JennyNeural.mp3"
            )
            stale_path = repository.ENGLISH_AUDIO_DIR / (
                f"sentence_{stale['id']}_edge_en-US-JennyNeural.mp3"
            )
            legacy_path.write_bytes(b"legacy-audio")
            stale_path.write_bytes(b"stale-audio")
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?, audio_provider = '', audio_voice = '',
                        audio_hash = '', audio_status = 'ready'
                    WHERE id = ?
                    """,
                    (legacy_path.name, int(legacy["id"])),
                )
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?, audio_provider = 'edge', audio_voice = 'en-US-JennyNeural',
                        audio_hash = 'stale-hash', audio_status = 'ready'
                    WHERE id = ?
                    """,
                    (stale_path.name, int(stale["id"])),
                )

            result = repository.reconcile_sentence_audio_metadata()
            assert result["backfilled"] == 1, result
            assert result["queued"] == 1, result
            refreshed_legacy = repository.get_sentence(int(legacy["id"]))
            refreshed_stale = repository.get_sentence(int(stale["id"]))
            assert refreshed_legacy and refreshed_legacy["audio_available"] is True, refreshed_legacy
            with get_connection() as conn:
                legacy_hash = conn.execute(
                    "SELECT audio_hash FROM english_sentences WHERE id = ?",
                    (int(legacy["id"]),),
                ).fetchone()["audio_hash"]
            assert legacy_hash == repository.sentence_audio_hash(
                legacy["text"], provider="edge", voice="en-US-JennyNeural"
            )
            assert refreshed_stale and refreshed_stale["audio_status"] == "pending", refreshed_stale
            assert refreshed_stale["audio_available"] is False, refreshed_stale
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_focus_map_pruning_and_reconciliation() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            created = repository.create_sentence(
                text="A **focus** word remains here.",
                word_translations={"focus": "重点"},
            )
            sentence_id = int(created["id"])
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET word_translations_json = ?, word_tips_json = ?,
                        word_play_counts_json = ?, word_play_total = 7
                    WHERE id = ?
                    """,
                    (
                        json.dumps({"focus": "重点", "stale": "过期"}, ensure_ascii=False),
                        json.dumps({"focus": "提示", "stale": "过期提示"}, ensure_ascii=False),
                        json.dumps({"focus": 2, "stale": 5}, ensure_ascii=False),
                        sentence_id,
                    ),
                )
            assert repository.reconcile_sentence_focus_state() == 1
            repaired = repository.get_sentence(sentence_id)
            assert repaired and repaired["word_translations"] == {"focus": "重点"}, repaired
            assert repaired["word_tips"] == {"focus": "提示"}, repaired
            assert repaired["word_play_counts"] == {"focus": 2}, repaired
            assert repaired["word_play_total"] == 2, repaired

            unmarked = repository.update_sentence(
                sentence_id=sentence_id,
                text="A focus word remains here.",
                word_translations=repaired["word_translations"],
                word_tips=repaired["word_tips"],
            )
            assert unmarked and unmarked["word_translations"] == {}, unmarked
            assert unmarked["word_tips"] == {}, unmarked
            assert unmarked["word_play_counts"] == {}, unmarked
            assert unmarked["word_play_total"] == 0, unmarked
    finally:
        platform_db.DB_PATH = original_path


def check_deleted_sentence_lifetime_stats() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )
            created = repository.create_sentence(text="A reviewed sentence may later be deleted.")
            sentence_id = int(created["id"])
            repository.review_sentence(user_id=1, sentence_id=sentence_id, complete_round_item=False)
            assert repository.delete_sentence(sentence_id=sentence_id)
            summary = repository.stats(user_id=1)
            heatmap = repository.review_heatmap(user_id=1, days=7)
            assert summary["sentence_reviews"] == 1, summary
            assert heatmap["tracked_sentence_reviews"] == 1, heatmap
            assert heatmap["lifetime_sentence_reviews"] == 1, heatmap
            assert heatmap["legacy_sentence_reviews"] == 0, heatmap
    finally:
        platform_db.DB_PATH = original_path


def check_sqlite_review_concurrency_and_stale_audio() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            repository.ENGLISH_AUDIO_DIR.mkdir(parents=True)
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            created = repository.create_sentence(
                text="A **focus** word appears in this sentence.",
                word_translations={"focus": "重点"},
            )
            sentence_id = int(created["id"])
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(
                    pool.map(
                        lambda _: repository.record_word_play(
                            user_id=1,
                            sentence_id=sentence_id,
                            word="focus",
                        ),
                        range(20),
                    )
                )
            assert all(results), results
            refreshed = repository.get_sentence(sentence_id)
            assert refreshed and refreshed["word_play_counts"]["focus"] == 20, refreshed
            assert refreshed["word_play_total"] == 20, refreshed
            with get_connection() as conn:
                event_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM english_review_events WHERE event_type = 'word_play'"
                ).fetchone()["count"]
            assert int(event_count) == 20, event_count

            provider = str(refreshed["audio_effective_provider"])
            voice = str(refreshed["audio_effective_voice"])
            audio_path = repository.ENGLISH_AUDIO_DIR / "sentence-current.mp3"
            audio_path.write_bytes(b"current-audio")
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?, audio_provider = ?, audio_voice = ?, audio_hash = ?, audio_status = 'ready'
                    WHERE id = ?
                    """,
                    (
                        audio_path.name,
                        provider,
                        voice,
                        repository.sentence_audio_hash(created["text"], provider=provider, voice=voice),
                        sentence_id,
                    ),
                )
            ready = repository.get_sentence(sentence_id)
            assert ready and ready["audio_available"] is True, ready
            changed = repository.update_sentence(
                sentence_id=sentence_id,
                text="A changed **focus** word appears in this sentence.",
                word_translations=ready["word_translations"],
                word_tips=ready["word_tips"],
            )
            assert changed and changed["audio_status"] == "pending", changed
            assert changed["audio_needs_regeneration"] is True, changed
            assert changed["audio_available"] is False and changed["audio_url"] == "", changed
            assert repository.audio_file_for_sentence(sentence_id) is None
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_today_passage_keeps_completed_items() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )
            first_completed = repository.create_passage(
                user_id=1,
                title="First completed today",
                exam_type="english1",
                passage_type="reading_a",
                body_text="The first completed passage.",
            )
            second_completed = repository.create_passage(
                user_id=1,
                title="Second completed today",
                exam_type="english1",
                passage_type="reading_a",
                body_text="The second completed passage.",
            )
            repository.create_passage(
                user_id=1,
                title="Still new",
                exam_type="english2",
                passage_type="reading_a",
                body_text="A new passage.",
            )
            repository.complete_passage(passage_id=int(first_completed["id"]), user_id=1)
            repository.complete_passage(passage_id=int(second_completed["id"]), user_id=1)
            result = repository.list_passages(user_id=1)
            today_ids = [int(item["id"]) for item in result["today_items"]]
            assert today_ids == [int(first_completed["id"]), int(second_completed["id"])], result
    finally:
        platform_db.DB_PATH = original_path


CHECKS = (
    check_sentence_integrity,
    check_audio_assets,
    check_kokoro_voice_catalog,
    check_dedicated_ai_configuration,
    check_library_metadata,
    check_two_stage_translation_pipeline,
    check_edit_translation_invalidation,
    check_audio_voice_settings,
    check_legacy_audio_metadata_reconciliation,
    check_focus_map_pruning_and_reconciliation,
    check_deleted_sentence_lifetime_stats,
    check_sqlite_review_concurrency_and_stale_audio,
    check_today_passage_keeps_completed_items,
)


def run_checks() -> None:
    initialize_database()
    initialize_english_schema()
    for check in CHECKS:
        check()
        print(f"OK english.{check.__name__}")


def main() -> int:
    run_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
