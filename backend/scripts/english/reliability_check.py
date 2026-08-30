from __future__ import annotations

import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.english import audio_generation, repository, review_rounds  # noqa: E402
from app.english import translation_generation  # noqa: E402
from app.english import translator  # noqa: E402
from app.english.ranking import (  # noqa: E402
    build_review_schedule,
    sentence_exposure_metrics,
    sentence_word_network_metrics,
)
from app.english.schema import initialize_schema as initialize_english_schema  # noqa: E402
from app.platform import db as platform_db  # noqa: E402
from app.platform.db import get_connection, initialize_database  # noqa: E402


def _decode_json(raw: object, fallback):
    try:
        return json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return fallback


def _mark_sentence_audio_ready(sentence_id: int) -> dict:
    sentence = repository.get_sentence(sentence_id)
    assert sentence, sentence_id
    provider = str(sentence["audio_effective_provider"])
    voice = str(sentence["audio_effective_voice"])
    audio_hash = repository.sentence_audio_hash(
        str(sentence["text"]),
        provider=provider,
        voice=voice,
    )
    audio_path = repository.ENGLISH_AUDIO_DIR / f"sentence-{sentence_id}-{audio_hash[:12]}.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"ready-audio")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE english_sentences
            SET audio_path = ?, audio_provider = ?, audio_voice = ?, audio_hash = ?,
                audio_status = 'ready', audio_error = ''
            WHERE id = ?
            """,
            (audio_path.name, provider, voice, audio_hash, sentence_id),
        )
    ready = repository.get_sentence(sentence_id)
    assert ready and ready["audio_available"] is True, ready
    return ready


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
    summary = repository.stats(user_id=1)
    lightweight_summary = repository.stats(user_id=1, include_word_network=False)
    assert "word_network" in summary, summary
    assert "word_network" not in lightweight_summary, lightweight_summary
    assert lightweight_summary["today"] == summary["today"], lightweight_summary
    today = summary["today"]
    assert "reviewed_sentences" in today, today
    assert int(today["reviewed_sentences"]) <= int(today["sentence_completions"]), today


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
    names = (
        "STUDY_ENGLISH_AI_BASE_URL",
        "STUDY_ENGLISH_AI_API_KEY",
        "STUDY_ENGLISH_AI_MODEL",
        "STUDY_ENGLISH_AI_TEMPERATURE",
        "STUDY_ENGLISH_AI_MAX_TOKENS",
        "STUDY_ENGLISH_AI_TIMEOUT_SECONDS",
    )
    original = {name: os.environ.get(name) for name in names}
    try:
        os.environ["STUDY_ENGLISH_AI_BASE_URL"] = "https://ai.example/v1"
        os.environ["STUDY_ENGLISH_AI_API_KEY"] = "test-key"
        os.environ["STUDY_ENGLISH_AI_MODEL"] = "provider/deepseek-v4-pro"
        os.environ["STUDY_ENGLISH_AI_MAX_TOKENS"] = "1200"
        options = translator._english_ai_options()
        assert options["base_url"] == "https://ai.example/v1", options
        assert options["api_key"] == "test-key", options
        assert options["model"] == "provider/deepseek-v4-pro", options
        assert "max_tokens" not in options, options
        os.environ["STUDY_ENGLISH_AI_TEMPERATURE"] = "not-a-number"
        try:
            translator._english_ai_options()
        except translator.AIProviderError as exc:
            assert "温度参数" in exc.user_message, exc.user_message
        else:
            raise AssertionError("invalid English AI temperature must be controlled")
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


def check_startup_translation_recovery_scans_only_pending_sentences() -> None:
    original_path = platform_db.DB_PATH
    original_configured = translation_generation.translation_configured
    original_translate_many = translation_generation.translate_sentences_if_missing_best_effort
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            initialize_english_schema()
            pending = repository.create_sentence(text="A **pending** sentence needs translation.")
            complete = repository.create_sentence(
                text="A **complete** sentence already has translation.",
                word_translations={"complete": "本义：完整的；句中：完整的"},
                sentence_translation="一个完整的句子已经有翻译。",
                sentence_segments=["A complete sentence already has translation."],
                translation_segments=["一个完整的句子已经有翻译。"],
            )
            deleted = repository.create_sentence(text="A deleted sentence needs translation.")
            assert repository.delete_sentence(sentence_id=int(deleted["id"]))

            captured: list[tuple[list[int], dict[int, str]]] = []

            def fake_translate(sentence_ids, expected_texts=None):
                captured.append((list(sentence_ids), dict(expected_texts or {})))

            translation_generation.translation_configured = lambda: True
            translation_generation.translate_sentences_if_missing_best_effort = fake_translate
            translation_generation.resume_pending_translation_generation_best_effort()

            assert captured == [
                (
                    [int(pending["id"])],
                    {int(pending["id"]): "A **pending** sentence needs translation."},
                )
            ], captured
            assert int(complete["id"]) not in captured[0][0]
            assert int(deleted["id"]) not in captured[0][0]
    finally:
        translation_generation.translation_configured = original_configured
        translation_generation.translate_sentences_if_missing_best_effort = original_translate_many
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
            repository.review_sentence(
                user_id=1,
                sentence_id=sentence_id,
                event_type="sentence_play",
                complete_round_item=False,
            )
            assert repository.delete_sentence(sentence_id=sentence_id)
            summary = repository.stats(user_id=1)
            heatmap = repository.review_heatmap(user_id=1, days=7)
            assert summary["sentence_reviews"] == 1, summary
            assert heatmap["tracked_sentence_reviews"] == 1, heatmap
            assert heatmap["lifetime_sentence_reviews"] == 1, heatmap
            assert heatmap["legacy_sentence_reviews"] == 0, heatmap
    finally:
        platform_db.DB_PATH = original_path


def check_audio_play_does_not_complete_review_item() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            created = repository.create_sentence(text="Listening alone must not complete this sentence.")
            sentence_id = int(created["id"])
            _mark_sentence_audio_ready(sentence_id)
            repository.list_sentences(user_id=1, sort="smart", page=1, page_size=20, resume=True)

            played = repository.review_sentence(
                user_id=1,
                sentence_id=sentence_id,
                event_type="sentence_play",
                complete_round_item=True,
            )
            assert played and played["review_count"] == 1, played
            assert played["review_round_item_completed"] is False, played
            with get_connection() as conn:
                round_item = conn.execute(
                    "SELECT completed_at FROM english_review_round_items WHERE sentence_id = ?",
                    (sentence_id,),
                ).fetchone()
            assert round_item and str(round_item["completed_at"] or "") == "", round_item

            reviewed = repository.review_sentence(
                user_id=1,
                sentence_id=sentence_id,
                event_type="sentence_review",
            )
            assert reviewed and reviewed["review_count"] == 1, reviewed
            assert reviewed["completion_count"] == 1, reviewed
            assert reviewed["review_round_item_completed"] is True, reviewed
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_sentence_write_boundaries() -> None:
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

            try:
                repository.create_sentence(text="   ")
            except ValueError:
                pass
            else:
                raise AssertionError("blank sentence must be rejected")

            first = repository.create_sentence(
                text="A **focus** word starts the review round.",
                word_translations={"focus": "重点"},
            )
            repository.list_sentences(user_id=1, sort="smart", page=1, page_size=20, resume=True)
            second = repository.create_sentence(text="A later sentence is not yet in that frozen round.")
            reviewed = repository.review_sentence(user_id=1, sentence_id=int(second["id"]))
            assert reviewed and reviewed["review_round_item_completed"] is False, reviewed

            try:
                repository.record_word_play(user_id=1, sentence_id=int(first["id"]), word="other")
            except ValueError:
                pass
            else:
                raise AssertionError("non-focus word play must be rejected")

            assert repository.delete_sentence(sentence_id=int(second["id"]))
            assert repository.update_sentence(
                sentence_id=int(second["id"]),
                text="Deleted content must stay deleted.",
            ) is None
    finally:
        platform_db.DB_PATH = original_path


def check_review_queue_includes_audio_optional_sentences_and_freezes_membership() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            pending = repository.create_sentence(text="A pending sentence must wait outside review.")
            failed = repository.create_sentence(text="A failed sentence must also wait outside review.")
            missing = repository.create_sentence(text="A missing sentence must stay outside review.")
            with get_connection() as conn:
                conn.execute(
                    "UPDATE english_sentences SET audio_status = 'failed' WHERE id = ?",
                    (int(failed["id"]),),
                )
                conn.execute(
                    "UPDATE english_sentences SET audio_status = 'missing' WHERE id = ?",
                    (int(missing["id"]),),
                )

            first_load = repository.list_sentences(
                user_id=1,
                sort="smart",
                page=1,
                page_size=20,
                resume=True,
            )
            round_id = int(first_load["review_round"]["id"])
            assert {int(item["id"]) for item in first_load["items"]} == {
                int(pending["id"]),
                int(failed["id"]),
                int(missing["id"]),
            }, first_load
            assert first_load["total"] == 3, first_load
            assert first_load["review_round"]["available"] == 3, first_load
            with get_connection() as conn:
                item_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM english_review_round_items WHERE round_id = ?",
                    (round_id,),
                ).fetchone()["count"]
            assert int(item_count) == 3, item_count

            later = repository.create_sentence(text="A new sentence waits for the next seven-day cycle.")
            frozen_load = repository.list_sentences(
                user_id=1,
                sort="smart",
                page=1,
                page_size=20,
                resume=True,
            )
            assert frozen_load["review_round"]["id"] == round_id, frozen_load
            assert frozen_load["total"] == 3, frozen_load
            assert all(int(item["id"]) != int(later["id"]) for item in frozen_load["items"]), frozen_load
    finally:
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


def check_exposure_formula_and_double_peak_repeats() -> None:
    linked_rows = [
        {
            "id": 1,
            "text": "**Echo** returns, and echo remains.",
            "word_translations_json": json.dumps({"Echo": "回声"}),
            "word_play_counts_json": json.dumps({"Echo": 3}),
            "review_count": 0,
            "word_play_total": 3,
            "completion_count": 1,
        },
        {
            "id": 2,
            "text": "An echo fades.",
            "word_translations_json": "{}",
            "word_play_counts_json": "{}",
            "review_count": 0,
            "word_play_total": 0,
            "completion_count": 1,
        },
    ]
    linked = sentence_exposure_metrics(linked_rows)
    assert linked[1]["word_exposure"] == linked[2]["word_exposure"] * 2, linked

    peak_rows = [
        {
            "id": index + 1,
            "text": f"Plain sentence {index}.",
            "word_translations_json": "{}",
            "word_play_counts_json": "{}",
            "review_count": index,
            "word_play_total": 0,
            "completion_count": 1,
        }
        for index in range(5)
    ]
    peak = sentence_exposure_metrics(peak_rows)
    assert [peak[index]["repeat_count"] for index in range(1, 6)] == [1, 7, 1, 7, 1], peak
    ranked = [(row, {"score": 0}) for row in peak_rows]
    schedule = build_review_schedule(ranked)
    counts = {
        sentence_id: sum(1 for item in schedule if int(item["sentence_id"]) == sentence_id)
        for sentence_id in range(1, 6)
    }
    assert [counts[index] for index in range(1, 6)] == [1, 7, 1, 7, 1], counts
    positions = [
        index
        for index, item in enumerate(schedule)
        if int(item["sentence_id"]) == 2
    ]
    assert len(positions) == 7 and positions == sorted(positions), positions


def check_repeated_items_complete_independently_and_wait_until_next_boundary() -> None:
    original_path = platform_db.DB_PATH
    original_now = review_rounds._utc_now
    clock = [datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)]
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            review_rounds._utc_now = lambda: clock[0]
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )
            sentences = [repository.create_sentence(text=f"Review schedule sentence {index}.") for index in range(5)]
            with get_connection() as conn:
                # These sentences existed before the fixed 08:00 boundary;
                # they belong to the first cycle's frozen snapshot.
                conn.execute(
                    "UPDATE english_sentences SET created_at = '2026-08-20T23:00:00+00:00'"
                )
                for index, sentence in enumerate(sentences):
                    conn.execute(
                        "UPDATE english_sentences SET review_count = ?, completion_count = 1 WHERE id = ?",
                        (index, int(sentence["id"])),
                    )

            first = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            round_id = int(first["review_round"]["id"])
            assert first["review_round"]["total"] == 17, first["review_round"]
            repeated = next(item for item in first["items"] if int(item["review_repeat_total"]) == 7)
            same_sentence_items = [
                item for item in first["items"] if int(item["id"]) == int(repeated["id"])
            ]
            assert len(same_sentence_items) == 7, same_sentence_items

            completed = repository.review_sentence(
                user_id=1,
                sentence_id=int(repeated["id"]),
                round_item_id=int(same_sentence_items[0]["review_round_item_id"]),
            )
            assert completed and completed["review_round_item_completed"] is True, completed
            assert completed["review_count"] == int(repeated["review_count"]), completed
            assert completed["completion_count"] == 2, completed
            with get_connection() as conn:
                remaining_same = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM english_review_round_items
                    WHERE round_id = ? AND sentence_id = ? AND COALESCE(completed_at, '') = ''
                    """,
                    (round_id, int(repeated["id"])),
                ).fetchone()["count"]
            assert int(remaining_same) == 6, remaining_same

            with get_connection() as conn:
                remaining = conn.execute(
                    """
                    SELECT id, sentence_id
                    FROM english_review_round_items
                    WHERE round_id = ? AND COALESCE(completed_at, '') = ''
                    ORDER BY position
                    """,
                    (round_id,),
                ).fetchall()
            for item in remaining:
                repository.review_sentence(
                    user_id=1,
                    sentence_id=int(item["sentence_id"]),
                    round_item_id=int(item["id"]),
                )

            waiting = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            assert int(waiting["review_round"]["id"]) == round_id, waiting["review_round"]
            assert waiting["review_round"]["is_completed"] is True, waiting["review_round"]
            assert waiting["review_round"]["next_round_at"] == "2026-08-22T00:00:00+00:00", waiting

            clock[0] += timedelta(hours=14)
            next_round = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            assert int(next_round["review_round"]["id"]) != round_id, next_round["review_round"]
            next_round_id = int(next_round["review_round"]["id"])
            stale_item = next_round["items"][0]
            clock[0] += timedelta(days=7)
            expired = repository.review_sentence(
                user_id=1,
                sentence_id=int(stale_item["id"]),
                round_item_id=int(stale_item["review_round_item_id"]),
            )
            assert expired and expired["review_round_expired"] is True, expired
            refreshed = repository.list_sentences(user_id=1, sort="smart", page=1, page_size=200, resume=True)
            assert int(refreshed["review_round"]["id"]) != next_round_id, refreshed["review_round"]
    finally:
        review_rounds._utc_now = original_now
        platform_db.DB_PATH = original_path


def check_review_rounds_use_fixed_boundaries_and_catch_up_without_request() -> None:
    original_path = platform_db.DB_PATH
    original_audio_dir = repository.ENGLISH_AUDIO_DIR
    original_now = review_rounds._utc_now
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform_db.DB_PATH = root / "study.db"
            repository.ENGLISH_AUDIO_DIR = root / "audio"
            initialize_database()
            initialize_english_schema()
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, display_name) VALUES ('admin', 'test', 'Admin')"
                )

            first = repository.create_sentence(text="Fixed boundary sentence.")
            first_time = datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc)
            created = repository.advance_due_review_rounds(now=first_time)
            assert created and created[0]["created"] is True, created
            with get_connection() as conn:
                round_row = conn.execute(
                    "SELECT * FROM english_review_rounds WHERE status = 'active'"
                ).fetchone()
            assert round_row["started_at"] == "2026-08-21T00:00:00+00:00", round_row
            assert round_row["expires_at"] == "2026-08-28T00:00:00+00:00", round_row

            # No request is needed at the boundary: the scheduler entry point
            # catches up and creates the next fixed cycle.
            next_cycle = repository.advance_due_review_rounds(
                now=datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
            )
            assert next_cycle and next_cycle[0]["round_id"] != int(round_row["id"]), next_cycle
            with get_connection() as conn:
                rounds = conn.execute(
                    "SELECT * FROM english_review_rounds ORDER BY id"
                ).fetchall()
            assert rounds[-1]["started_at"] == "2026-08-28T00:00:00+00:00", rounds[-1]
            assert rounds[-1]["expires_at"] == "2026-09-04T00:00:00+00:00", rounds[-1]

            # A sentence added after the fixed boundary is deferred to the
            # following cycle.
            later = repository.create_sentence(text="Added after boundary.")
            with get_connection() as conn:
                conn.execute(
                    "UPDATE english_sentences SET created_at = '2026-09-01T00:00:00+00:00' WHERE id = ?",
                    (int(later["id"]),),
                )
                conn.execute(
                    "UPDATE english_review_rounds SET expires_at = '2026-09-04T00:00:00+00:00' WHERE status = 'active'"
                )
            following = repository.advance_due_review_rounds(
                now=datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
            )
            assert following and following[0]["created"] is True, following
            with get_connection() as conn:
                latest_id = int(conn.execute("SELECT MAX(id) FROM english_review_rounds").fetchone()[0])
                included = conn.execute(
                    "SELECT 1 FROM english_review_round_items WHERE round_id = ? AND sentence_id = ?",
                    (latest_id, int(later["id"])),
                ).fetchone()
            assert included is not None, (latest_id, later)
    finally:
        review_rounds._utc_now = original_now
        platform_db.DB_PATH = original_path
        repository.ENGLISH_AUDIO_DIR = original_audio_dir


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
    check_startup_translation_recovery_scans_only_pending_sentences,
    check_audio_voice_settings,
    check_legacy_audio_metadata_reconciliation,
    check_focus_map_pruning_and_reconciliation,
    check_deleted_sentence_lifetime_stats,
    check_audio_play_does_not_complete_review_item,
    check_sentence_write_boundaries,
    check_review_queue_includes_audio_optional_sentences_and_freezes_membership,
    check_exposure_formula_and_double_peak_repeats,
    check_repeated_items_complete_independently_and_wait_until_next_boundary,
    check_review_rounds_use_fixed_boundaries_and_catch_up_without_request,
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
