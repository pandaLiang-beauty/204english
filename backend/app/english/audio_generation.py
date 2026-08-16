from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..platform.db import get_connection, rows_to_dicts
from . import repository


DEFAULT_EDGE_VOICE = "en-US-JennyNeural"
DEFAULT_KOKORO_VOICE = "af_heart"
DEFAULT_KOKORO_SAMPLE_RATE = 24000
DEFAULT_KOKORO_MODEL_DIR = repository.ENGLISH_DATA_DIR / "kokoro"
VOICE_PREVIEW_DIR = repository.ENGLISH_AUDIO_DIR / "previews"
_SENTENCE_GENERATION_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, type(fallback)):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _plain_text(value: str) -> str:
    return repository.plain_sentence_audio_text(value)


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def auto_word_audio_enabled() -> bool:
    return _truthy_env("STUDY_ENGLISH_AUTO_WORD_AUDIO", True)


def auto_sentence_audio_enabled() -> bool:
    return _truthy_env("STUDY_ENGLISH_AUTO_SENTENCE_AUDIO", True)


def _words_from_row(row: dict[str, Any]) -> list[str]:
    translations = _json_loads(row.get("word_translations_json"), {})
    if not isinstance(translations, dict):
        return []
    seen = set()
    words: list[str] = []
    for raw_word in translations.keys():
        word = str(raw_word or "").strip()
        lowered = word.lower()
        if not word or lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)
    return words


def _word_audio_path(sentence_id: int, word: str) -> Path:
    folder = repository.ENGLISH_PRONUNCIATION_DIR / f"sentence_{int(sentence_id)}"
    return folder / repository._pronunciation_filename(word)


def _sentence_audio_path(sentence_id: int, *, provider: str, voice: str, suffix: str, audio_hash: str = "") -> Path:
    safe_provider = re.sub(r"[^A-Za-z0-9_-]+", "-", provider).strip("-").lower() or "tts"
    safe_voice = re.sub(r"[^A-Za-z0-9_-]+", "-", voice).strip("-") or "voice"
    safe_hash = re.sub(r"[^a-fA-F0-9]+", "", str(audio_hash or ""))[:16]
    hash_part = f"_{safe_hash}" if safe_hash else ""
    return repository.ENGLISH_AUDIO_DIR / f"sentence_{int(sentence_id)}_{safe_provider}_{safe_voice}{hash_part}.{suffix}"


def _make_audio_readable(path: Path) -> None:
    path.chmod(0o644)


def _has_word_audio(sentence_id: int, word: str) -> bool:
    path = _word_audio_path(sentence_id, word)
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _has_current_sentence_audio(row: dict[str, Any], *, provider: str, voice: str) -> bool:
    audio_path = str(row.get("audio_path") or "").strip()
    if not audio_path:
        return False
    path = repository.ENGLISH_AUDIO_DIR / Path(audio_path).name
    if not (path.exists() and path.is_file() and path.stat().st_size > 0):
        return False
    current_hash = repository.sentence_audio_hash(str(row.get("text") or ""), provider=provider, voice=voice)
    return (
        str(row.get("audio_status") or "").strip().lower() == "ready"
        and str(row.get("audio_provider") or "").strip() == provider
        and str(row.get("audio_voice") or "").strip() == voice
        and str(row.get("audio_hash") or "").strip() == current_hash
    )


def _load_sentence_rows(*, ids: list[int] | None = None, limit: int = 0) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = "WHERE COALESCE(deleted_at, '') = ''"
    if ids:
        placeholders = ",".join(["?"] * len(ids))
        where += f" AND id IN ({placeholders})"
        params.extend(ids)
        order_sql = " ".join(f"WHEN {int(sentence_id)} THEN {index}" for index, sentence_id in enumerate(ids))
        order_by = f"ORDER BY CASE id {order_sql} END"
    else:
        order_by = """
        ORDER BY
            CASE
                WHEN COALESCE(audio_status, '') IN ('pending', 'failed', 'missing') THEN 0
                WHEN COALESCE(audio_hash, '') = '' THEN 1
                ELSE 2
            END,
            id
        """
    sql = f"""
        SELECT id, text, audio_path, word_translations_json,
               audio_provider, audio_voice, audio_provider_override, audio_voice_override,
               audio_hash, audio_status
        FROM english_sentences
        {where}
        {order_by}
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(sql, params).fetchall())


async def _edge_tts_save(text: str, path: Path, *, voice: str = DEFAULT_EDGE_VOICE) -> None:
    try:
        import edge_tts
    except ImportError as exc:  # pragma: no cover - depends on optional package.
        raise RuntimeError("edge-tts is not installed; install backend/requirements.txt or use --skip-words") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _plain_text(text)
    if not cleaned:
        raise ValueError("empty TTS text")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(path.parent)) as handle:
        tmp_path = Path(handle.name)
    try:
        communicate = edge_tts.Communicate(cleaned, voice=voice)
        await communicate.save(str(tmp_path))
        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise RuntimeError("edge-tts wrote an empty audio file")
        tmp_path.replace(path)
        _make_audio_readable(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


async def generate_word_audio_for_rows(
    rows: list[dict[str, Any]],
    *,
    overwrite: bool = False,
    voice: str = DEFAULT_EDGE_VOICE,
    max_words: int = 0,
    sleep_seconds: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    generated = 0
    skipped = 0
    failed: list[dict[str, Any]] = []

    for row in rows:
        sentence_id = int(row["id"])
        for word in _words_from_row(row):
            path = _word_audio_path(sentence_id, word)
            if not overwrite and _has_word_audio(sentence_id, word):
                skipped += 1
                continue
            if max_words and generated >= max_words:
                return {"generated": generated, "skipped": skipped, "failed": failed}
            if dry_run:
                generated += 1
                continue
            try:
                await _edge_tts_save(word, path, voice=voice)
                generated += 1
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
            except Exception as exc:  # noqa: BLE001 - batch job records per-word failures.
                failed.append({"sentence_id": sentence_id, "word": word, "error": str(exc)[:240]})
    return {"generated": generated, "skipped": skipped, "failed": failed}


def _kokoro_model_dir() -> Path:
    configured = os.getenv("STUDY_ENGLISH_KOKORO_MODEL_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_KOKORO_MODEL_DIR


def _kokoro_language_code(voice: str) -> str:
    return "b" if str(voice or "").strip().lower().startswith("b") else "a"


def _kokoro_model():
    try:
        from kokoro import KModel
    except ImportError as exc:  # pragma: no cover - depends on optional packages.
        raise RuntimeError("kokoro is required for sentence audio") from exc

    model_dir = _kokoro_model_dir()
    config_path = model_dir / "config.json"
    model_path = model_dir / "kokoro-v1_0.pth"
    local_files = (config_path.is_file(), model_path.is_file())
    if any(local_files) and not all(local_files):
        raise RuntimeError(f"incomplete Kokoro model files in {model_dir}")
    if all(local_files):
        return KModel(config=str(config_path), model=str(model_path)).to("cpu").eval()
    return KModel().to("cpu").eval()


def _kokoro_pipeline(*, lang_code: str = "a", model: Any = None):
    try:
        from kokoro import KPipeline
    except ImportError as exc:  # pragma: no cover - depends on optional packages.
        raise RuntimeError("kokoro is required for sentence audio") from exc
    return KPipeline(lang_code=lang_code, model=model or _kokoro_model())


def _kokoro_voice_source(voice: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", voice):
        local_voice = _kokoro_model_dir() / "voices" / f"{voice}.pt"
        if local_voice.is_file():
            return str(local_voice)
    return voice


def _kokoro_generate_audio(text: str, path: Path, *, voice: str = DEFAULT_KOKORO_VOICE, pipeline: Any = None) -> None:
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - depends on optional packages.
        raise RuntimeError("numpy and soundfile are required for sentence audio") from exc

    cleaned = _plain_text(text)
    if not cleaned:
        raise ValueError("empty TTS text")
    path.parent.mkdir(parents=True, exist_ok=True)
    pipeline = pipeline or _kokoro_pipeline(lang_code=_kokoro_language_code(voice))
    chunks = []
    for _, _, audio in pipeline(cleaned, voice=_kokoro_voice_source(voice)):
        chunks.append(audio)
    if not chunks:
        raise RuntimeError("kokoro produced no audio")
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(path.parent)) as handle:
        tmp_path = Path(handle.name)
    try:
        sf.write(tmp_path, audio, DEFAULT_KOKORO_SAMPLE_RATE)
        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise RuntimeError("kokoro wrote an empty audio file")
        tmp_path.replace(path)
        _make_audio_readable(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def generate_sentence_audio_for_rows(
    rows: list[dict[str, Any]],
    *,
    overwrite: bool = False,
    provider: str | None = None,
    voice: str | None = None,
    max_sentences: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    generated = 0
    skipped = 0
    failed: list[dict[str, Any]] = []
    if (provider is None) != (voice is None):
        raise ValueError("sentence TTS provider and voice must be supplied together")
    if provider is not None and provider not in {"edge", "kokoro"}:
        raise ValueError(f"unsupported sentence TTS provider: {provider}")
    kokoro_model = None
    kokoro_pipelines: dict[str, Any] = {}
    audio_settings = repository.get_sentence_audio_settings() if provider is None else None

    for row in rows:
        sentence_id = int(row["id"])
        previous_audio_name = Path(str(row.get("audio_path") or "")).name
        previous_audio_path = repository.ENGLISH_AUDIO_DIR / previous_audio_name if previous_audio_name else None
        if provider is None:
            selected_provider, selected_voice = repository.effective_sentence_audio_identity(
                row,
                settings=audio_settings,
            )
        else:
            selected_provider, selected_voice = provider, voice
        current_hash = repository.sentence_audio_hash(
            str(row.get("text") or ""),
            provider=selected_provider,
            voice=selected_voice,
        )
        if not overwrite and _has_current_sentence_audio(
            row,
            provider=selected_provider,
            voice=selected_voice,
        ):
            skipped += 1
            continue
        if max_sentences and generated >= max_sentences:
            return {"generated": generated, "skipped": skipped, "failed": failed}
        suffix = "wav" if selected_provider == "kokoro" else "mp3"
        path = _sentence_audio_path(
            sentence_id,
            provider=selected_provider,
            voice=selected_voice,
            suffix=suffix,
            audio_hash=current_hash,
        )
        if dry_run:
            generated += 1
            continue
        try:
            with get_connection() as conn:
                before_changes = conn.total_changes
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_hash = ?, audio_status = 'pending', audio_error = '', updated_at = ?
                    WHERE id = ?
                      AND audio_hash = ?
                      AND COALESCE(deleted_at, '') = ''
                    """,
                    (current_hash, _now(), sentence_id, str(row.get("audio_hash") or "")),
                )
                claimed = conn.total_changes > before_changes
            if not claimed:
                skipped += 1
                continue
            row["audio_hash"] = current_hash
            if selected_provider == "kokoro":
                lang_code = _kokoro_language_code(selected_voice)
                if lang_code not in kokoro_pipelines:
                    if kokoro_model is None:
                        kokoro_model = _kokoro_model()
                    kokoro_pipelines[lang_code] = _kokoro_pipeline(
                        lang_code=lang_code,
                        model=kokoro_model,
                    )
                _kokoro_generate_audio(
                    str(row.get("text") or ""),
                    path,
                    voice=selected_voice,
                    pipeline=kokoro_pipelines[lang_code],
                )
            else:
                asyncio.run(_edge_tts_save(str(row.get("text") or ""), path, voice=selected_voice))
            with get_connection() as conn:
                current = conn.execute(
                    """
                    SELECT audio_provider_override, audio_voice_override
                    FROM english_sentences
                    WHERE id = ? AND audio_hash = ? AND COALESCE(deleted_at, '') = ''
                    """,
                    (sentence_id, current_hash),
                ).fetchone()
            current_data = dict(current) if current else {}
            current_provider, current_voice = repository.effective_sentence_audio_identity(current_data)
            if (current_provider, current_voice) != (selected_provider, selected_voice):
                path.unlink(missing_ok=True)
                skipped += 1
                continue
            generated_at = _now()
            with get_connection() as conn:
                before_changes = conn.total_changes
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_path = ?,
                        audio_provider = ?,
                        audio_voice = ?,
                        audio_hash = ?,
                        audio_status = 'ready',
                        audio_error = '',
                        audio_generated_at = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND audio_hash = ?
                      AND COALESCE(deleted_at, '') = ''
                    """,
                    (
                        path.name,
                        selected_provider,
                        selected_voice,
                        current_hash,
                        generated_at,
                        generated_at,
                        sentence_id,
                        current_hash,
                    ),
                )
                changed = conn.total_changes > before_changes
            if not changed:
                path.unlink(missing_ok=True)
                skipped += 1
                continue
            if previous_audio_path is not None and previous_audio_path != path:
                previous_audio_path.unlink(missing_ok=True)
            row["audio_path"] = path.name
            row["audio_provider"] = selected_provider
            row["audio_voice"] = selected_voice
            row["audio_hash"] = current_hash
            row["audio_status"] = "ready"
            generated += 1
        except Exception as exc:  # noqa: BLE001 - batch job records per-sentence failures.
            error = str(exc)[:240]
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET audio_status = 'failed',
                        audio_error = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND audio_hash = ?
                      AND COALESCE(deleted_at, '') = ''
                    """,
                    (error, _now(), sentence_id, current_hash),
                )
            failed.append({"sentence_id": sentence_id, "error": error})
    return {"generated": generated, "skipped": skipped, "failed": failed}


def _voice_preview_path(*, provider: str, voice: str) -> Path:
    suffix = "wav" if provider == "kokoro" else "mp3"
    preview_hash = repository.sentence_audio_hash(
        repository.SENTENCE_AUDIO_PREVIEW_TEXT,
        provider=provider,
        voice=voice,
    )[:16]
    safe_provider = re.sub(r"[^A-Za-z0-9_-]+", "-", provider).strip("-").lower()
    safe_voice = re.sub(r"[^A-Za-z0-9_-]+", "-", voice).strip("-")
    return VOICE_PREVIEW_DIR / f"{safe_provider}_{safe_voice}_{preview_hash}.{suffix}"


def voice_preview_file(*, provider: str, voice: str) -> Path | None:
    clean_provider, clean_voice = repository.validate_sentence_audio_identity(provider, voice)
    path = _voice_preview_path(provider=clean_provider, voice=clean_voice)
    return path if path.is_file() and path.stat().st_size > 0 else None


def generate_voice_preview(*, provider: str, voice: str) -> Path:
    clean_provider, clean_voice = repository.validate_sentence_audio_identity(provider, voice)
    path = _voice_preview_path(provider=clean_provider, voice=clean_voice)
    with _SENTENCE_GENERATION_LOCK:
        if path.is_file() and path.stat().st_size > 0:
            return path
        if clean_provider == "kokoro":
            _kokoro_generate_audio(
                repository.SENTENCE_AUDIO_PREVIEW_TEXT,
                path,
                voice=clean_voice,
                pipeline=_kokoro_pipeline(lang_code=_kokoro_language_code(clean_voice)),
            )
        else:
            asyncio.run(
                _edge_tts_save(
                    repository.SENTENCE_AUDIO_PREVIEW_TEXT,
                    path,
                    voice=clean_voice,
                )
            )
    return path


def generate_word_audio_for_sentence_ids(
    sentence_ids: list[int],
    *,
    overwrite: bool = False,
    voice: str | None = None,
    max_words: int = 0,
) -> dict[str, Any]:
    ids = [int(value) for value in sentence_ids if int(value) > 0]
    if not ids:
        return {"generated": 0, "skipped": 0, "failed": []}
    rows = _load_sentence_rows(ids=ids)
    selected_voice = voice or os.getenv("STUDY_ENGLISH_EDGE_VOICE", DEFAULT_EDGE_VOICE).strip() or DEFAULT_EDGE_VOICE
    return asyncio.run(
        generate_word_audio_for_rows(
            rows,
            overwrite=overwrite,
            voice=selected_voice,
            max_words=max_words,
            sleep_seconds=float(os.getenv("STUDY_ENGLISH_EDGE_SLEEP_SECONDS", "0") or 0),
        )
    )


def generate_word_audio_for_sentence_ids_best_effort(sentence_ids: list[int]) -> None:
    if not auto_word_audio_enabled():
        return
    try:
        limit = int(os.getenv("STUDY_ENGLISH_AUTO_WORD_AUDIO_LIMIT", "0") or 0)
        result = generate_word_audio_for_sentence_ids(sentence_ids, max_words=limit)
        if result.get("failed"):
            print(json.dumps({"english_word_audio": result}, ensure_ascii=False), flush=True)
    except Exception as exc:  # noqa: BLE001 - background job must never break the write request.
        print(f"english word audio generation failed: {type(exc).__name__}: {exc}", flush=True)


def generate_sentence_audio_for_sentence_ids_best_effort(sentence_ids: list[int]) -> None:
    if not auto_sentence_audio_enabled():
        return
    ids = [int(value) for value in sentence_ids if int(value) > 0]
    if not ids:
        return
    try:
        with _SENTENCE_GENERATION_LOCK:
            limit = int(os.getenv("STUDY_ENGLISH_AUTO_SENTENCE_AUDIO_LIMIT", "0") or 0)
            rows = _load_sentence_rows(ids=ids)
            result = generate_sentence_audio_for_rows(
                rows,
                max_sentences=limit,
            )
        if result.get("failed"):
            print(json.dumps({"english_sentence_audio": result}, ensure_ascii=False), flush=True)
    except Exception as exc:  # noqa: BLE001 - background job must never break the write request.
        print(f"english sentence audio generation failed: {type(exc).__name__}: {exc}", flush=True)


def resume_pending_audio_generation_best_effort() -> None:
    try:
        reconciliation = repository.reconcile_sentence_audio_metadata()
        if any(reconciliation.values()):
            print(json.dumps({"english_audio_metadata": reconciliation}, ensure_ascii=False), flush=True)
    except Exception as exc:  # noqa: BLE001 - startup recovery must not stop the application.
        print(f"english audio metadata reconciliation failed: {type(exc).__name__}: {exc}", flush=True)
    rows = _load_sentence_rows()
    pending_ids = [
        int(row["id"])
        for row in rows
        if str(row.get("audio_status") or "").strip().lower() in {"pending", "failed", "missing"}
    ]
    if not pending_ids:
        return
    generate_word_audio_for_sentence_ids_best_effort(pending_ids)
    generate_sentence_audio_for_sentence_ids_best_effort(pending_ids)


def load_rows_for_generation(*, ids: list[int] | None = None, limit: int = 0) -> list[dict[str, Any]]:
    return _load_sentence_rows(ids=ids, limit=limit)
