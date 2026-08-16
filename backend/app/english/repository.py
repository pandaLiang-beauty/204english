from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..platform.db import DATA_DIR, begin_immediate, get_connection, rows_to_dicts
from .passages import (
    complete_passage,
    create_passage,
    delete_passage,
    get_passage,
    list_passages,
    serialize_passage,
    today_passage,
    update_passage,
)
from .ranking import (
    _normalize_focus_word,
    _rank_sentences_by_peak_familiarity,
    _word_key_candidates,
    sentence_word_network_metrics,
)
from .review_rounds import complete_current_item, queue_state
from .stats import review_heatmap, stats


ENGLISH_DATA_DIR = DATA_DIR / "english"
ENGLISH_AUDIO_DIR = ENGLISH_DATA_DIR / "audio"
ENGLISH_PRONUNCIATION_DIR = ENGLISH_AUDIO_DIR / "pronunciations"
DEFAULT_SENTENCE_AUDIO_PROVIDER = "edge"
DEFAULT_SENTENCE_AUDIO_VOICE = "en-US-JennyNeural"
SENTENCE_AUDIO_STATUSES = {"missing", "pending", "ready", "failed"}
SENTENCE_AUDIO_PREVIEW_TEXT = "Clear voices make every English sentence easier to follow and remember."
_KOKORO_ENGLISH_VOICE_SPECS = (
    ("af_heart", "Heart", "美式", "女声", "A"),
    ("af_alloy", "Alloy", "美式", "女声", "C"),
    ("af_aoede", "Aoede", "美式", "女声", "C+"),
    ("af_bella", "Bella", "美式", "女声", "A-"),
    ("af_jessica", "Jessica", "美式", "女声", "D"),
    ("af_kore", "Kore", "美式", "女声", "C+"),
    ("af_nicole", "Nicole", "美式", "女声", "B-"),
    ("af_nova", "Nova", "美式", "女声", "C"),
    ("af_river", "River", "美式", "女声", "D"),
    ("af_sarah", "Sarah", "美式", "女声", "C+"),
    ("af_sky", "Sky", "美式", "女声", "C-"),
    ("am_adam", "Adam", "美式", "男声", "F+"),
    ("am_echo", "Echo", "美式", "男声", "D"),
    ("am_eric", "Eric", "美式", "男声", "D"),
    ("am_fenrir", "Fenrir", "美式", "男声", "C+"),
    ("am_liam", "Liam", "美式", "男声", "D"),
    ("am_michael", "Michael", "美式", "男声", "C+"),
    ("am_onyx", "Onyx", "美式", "男声", "D"),
    ("am_puck", "Puck", "美式", "男声", "C+"),
    ("am_santa", "Santa", "美式", "男声", "D-"),
    ("bf_emma", "Emma", "英式", "女声", "B-"),
    ("bf_isabella", "Isabella", "英式", "女声", "C"),
    ("bf_alice", "Alice", "英式", "女声", "D"),
    ("bf_lily", "Lily", "英式", "女声", "D"),
    ("bm_george", "George", "英式", "男声", "C"),
    ("bm_lewis", "Lewis", "英式", "男声", "D+"),
    ("bm_daniel", "Daniel", "英式", "男声", "D"),
    ("bm_fable", "Fable", "英式", "男声", "C"),
)
SENTENCE_AUDIO_VOICES = tuple(
    {
        "provider": "kokoro",
        "voice": voice,
        "name": name,
        "accent": accent,
        "gender": gender,
        "grade": grade,
        "description": f"{accent}{gender} · 官方评级 {grade}",
    }
    for voice, name, accent, gender, grade in _KOKORO_ENGLISH_VOICE_SPECS
) + (
    {
        "provider": "edge",
        "voice": "en-US-JennyNeural",
        "name": "Jenny",
        "accent": "美式",
        "gender": "女声",
        "grade": "",
        "description": "清晰稳定的美式女声",
    },
    {
        "provider": "edge",
        "voice": "en-US-AriaNeural",
        "name": "Aria",
        "accent": "美式",
        "gender": "女声",
        "grade": "",
        "description": "明亮自然的美式女声",
    },
    {
        "provider": "edge",
        "voice": "en-US-GuyNeural",
        "name": "Guy",
        "accent": "美式",
        "gender": "男声",
        "grade": "",
        "description": "沉稳清楚的美式男声",
    },
    {
        "provider": "edge",
        "voice": "en-US-AndrewNeural",
        "name": "Andrew",
        "accent": "美式",
        "gender": "男声",
        "grade": "",
        "description": "自然平和的美式男声",
    },
)
SMART_SORTS = {"smart", "default", "peak-familiarity"}
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _environment_sentence_audio_identity() -> tuple[str, str]:
    provider = os.getenv("STUDY_ENGLISH_SENTENCE_AUDIO_PROVIDER", DEFAULT_SENTENCE_AUDIO_PROVIDER).strip().lower()
    if provider not in {"edge", "kokoro"}:
        provider = DEFAULT_SENTENCE_AUDIO_PROVIDER
    env_name = "STUDY_ENGLISH_KOKORO_VOICE" if provider == "kokoro" else "STUDY_ENGLISH_EDGE_VOICE"
    default = "af_heart" if provider == "kokoro" else DEFAULT_SENTENCE_AUDIO_VOICE
    return provider, os.getenv(env_name, default).strip() or default


def sentence_audio_voice_catalog() -> list[dict[str, Any]]:
    configured_dir = os.getenv("STUDY_ENGLISH_KOKORO_MODEL_DIR", "").strip()
    kokoro_dir = Path(configured_dir).expanduser() if configured_dir else ENGLISH_DATA_DIR / "kokoro"
    result = []
    for item in SENTENCE_AUDIO_VOICES:
        available = True
        if item["provider"] == "kokoro":
            available = all(
                path.is_file()
                for path in (
                    kokoro_dir / "config.json",
                    kokoro_dir / "kokoro-v1_0.pth",
                    kokoro_dir / "voices" / f"{item['voice']}.pt",
                )
            )
        result.append({**item, "available": available})
    return result


def validate_sentence_audio_identity(provider: str, voice: str) -> tuple[str, str]:
    clean_provider = str(provider or "").strip().lower()
    clean_voice = str(voice or "").strip()
    match = next(
        (
            item
            for item in sentence_audio_voice_catalog()
            if item["provider"] == clean_provider and item["voice"] == clean_voice
        ),
        None,
    )
    if not match:
        raise ValueError("不支持这个英语音色")
    if not match["available"]:
        raise ValueError("这个音色尚未安装")
    return clean_provider, clean_voice


def get_sentence_audio_settings() -> dict[str, str]:
    fallback_provider, fallback_voice = _environment_sentence_audio_identity()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM english_audio_settings WHERE id = 1").fetchone()
    if not row:
        return {
            "provider": fallback_provider,
            "voice": fallback_voice,
            "source": "environment",
            "updated_at": "",
        }
    data = dict(row)
    provider = str(data.get("sentence_provider") or "").strip().lower()
    voice = str(data.get("sentence_voice") or "").strip()
    if provider not in {"edge", "kokoro"} or not voice:
        provider, voice = fallback_provider, fallback_voice
    return {
        "provider": provider,
        "voice": voice,
        "source": "database",
        "updated_at": str(data.get("updated_at") or ""),
    }


def sentence_audio_voice() -> str:
    return get_sentence_audio_settings()["voice"]


def sentence_audio_provider() -> str:
    return get_sentence_audio_settings()["provider"]


def effective_sentence_audio_identity(
    row: dict[str, Any] | None = None,
    *,
    settings: dict[str, str] | None = None,
) -> tuple[str, str]:
    data = row or {}
    override_provider = str(data.get("audio_provider_override") or "").strip().lower()
    override_voice = str(data.get("audio_voice_override") or "").strip()
    if override_provider in {"edge", "kokoro"} and override_voice:
        return override_provider, override_voice
    selected = settings or get_sentence_audio_settings()
    return selected["provider"], selected["voice"]


def plain_sentence_audio_text(value: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(value or "")).strip()


def sentence_identity_key(value: str) -> str:
    plain = plain_sentence_audio_text(value)
    plain = plain.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", plain).strip().casefold()


def sentence_translation_source_key(value: str) -> str:
    return re.sub(r"\s+", " ", plain_sentence_audio_text(value)).strip()


def sentence_audio_hash(text: str, *, provider: str | None = None, voice: str | None = None) -> str:
    settings = get_sentence_audio_settings() if provider is None or voice is None else None
    clean_provider = (provider or settings["provider"]).strip()
    clean_voice = (voice or settings["voice"]).strip()
    source = plain_sentence_audio_text(text)
    digest_source = f"{clean_provider}\n{clean_voice}\n{source}"
    return hashlib.sha1(digest_source.encode("utf-8")).hexdigest()


def _clean_audio_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in SENTENCE_AUDIO_STATUSES else "missing"


def _initial_sentence_audio_fields(text: str) -> dict[str, str]:
    settings = get_sentence_audio_settings()
    provider = settings["provider"]
    voice = settings["voice"]
    return {
        "provider": provider,
        "voice": voice,
        "hash": sentence_audio_hash(text, provider=provider, voice=voice),
        "status": "pending",
        "error": "",
        "generated_at": "",
    }


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


def _json_dumps(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False)


def _normalize_dict(value: Any) -> dict:
    parsed = _json_loads(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _normalize_segments(value: Any) -> list[str]:
    parsed = _json_loads(value, [])
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    for item in parsed:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if text:
            result.append(text)
    return result[:40]


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _calculate_word_total(counts: dict) -> int:
    return sum(_safe_int(value) for value in counts.values())


def _slugify_word(word: str) -> str:
    lowered = str(word or "").lower().strip()
    slug = _SLUG_PATTERN.sub("-", lowered).strip("-") or "word"
    digest = hashlib.md5(lowered.encode("utf-8"), usedforsecurity=False).hexdigest()[:6]
    return f"{slug}-{digest}"


def _pronunciation_filename(word: str) -> str:
    return f"{_slugify_word(word)}.mp3"


def pronunciation_urls(sentence_id: int, words: list[str] | Any) -> dict:
    folder = ENGLISH_PRONUNCIATION_DIR / f"sentence_{sentence_id}"
    if not folder.exists():
        return {}
    result: dict[str, str] = {}
    for raw_word in words or []:
        word = str(raw_word or "").strip()
        if not word:
            continue
        filename = _pronunciation_filename(word)
        path = folder / filename
        if path.exists() and path.stat().st_size > 0:
            result[word] = f"/api/english/pronunciations/{sentence_id}/{filename}"
    return result


def _audio_file(row: dict) -> Path | None:
    audio_path = str(row.get("audio_path") or "").strip()
    if not audio_path:
        return None
    candidate = ENGLISH_AUDIO_DIR / Path(audio_path).name
    try:
        return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None
    except OSError:
        return None


def _stored_sentence_audio_identity(row: dict) -> tuple[str, str]:
    provider = str(row.get("audio_provider") or "").strip().lower()
    voice = str(row.get("audio_voice") or "").strip()
    stem = Path(str(row.get("audio_path") or "")).stem
    match = re.match(r"^sentence_\d+_(edge|kokoro)_(.+)$", stem, flags=re.IGNORECASE)
    if match:
        inferred_provider = match.group(1).lower()
        inferred_voice = re.sub(r"_[0-9a-fA-F]{12,16}$", "", match.group(2))
        provider = provider or inferred_provider
        voice = voice or inferred_voice
    return provider, voice


def _sentence_audio_is_current(
    row: dict,
    *,
    audio_file: Path | None = None,
    settings: dict[str, str] | None = None,
) -> bool:
    resolved_file = audio_file if audio_file is not None else _audio_file(row)
    if resolved_file is None or _clean_audio_status(row.get("audio_status")) != "ready":
        return False
    stored_provider, stored_voice = _stored_sentence_audio_identity(row)
    effective_provider, effective_voice = effective_sentence_audio_identity(row, settings=settings)
    expected_hash = sentence_audio_hash(
        str(row.get("text") or ""),
        provider=effective_provider,
        voice=effective_voice,
    )
    return (
        (stored_provider, stored_voice) == (effective_provider, effective_voice)
        and str(row.get("audio_hash") or "") == expected_hash
    )


def reconcile_sentence_audio_metadata() -> dict[str, int]:
    """Repair legacy audio rows before the background generator resumes."""
    settings = get_sentence_audio_settings()
    now = _now()
    result = {"recovered": 0, "backfilled": 0, "queued": 0, "updated": 0}
    with get_connection() as conn:
        begin_immediate(conn)
        rows = rows_to_dicts(
            conn.execute(
                "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
            ).fetchall()
        )
        for row in rows:
            status = _clean_audio_status(row.get("audio_status"))
            stored_provider, stored_voice = _stored_sentence_audio_identity(row)
            effective_provider, effective_voice = effective_sentence_audio_identity(row, settings=settings)
            expected_hash = sentence_audio_hash(
                str(row.get("text") or ""),
                provider=effective_provider,
                voice=effective_voice,
            )
            audio_file = _audio_file(row)
            file_ready = audio_file is not None
            metadata_current = (
                file_ready
                and (stored_provider, stored_voice) == (effective_provider, effective_voice)
                and str(row.get("audio_hash") or "") == expected_hash
            )
            if metadata_current:
                if (
                    status == "ready"
                    and str(row.get("audio_provider") or "").strip().lower() == effective_provider
                    and str(row.get("audio_voice") or "").strip() == effective_voice
                ):
                    continue
                next_status = "ready"
                result["recovered"] += 1
            elif (
                file_ready
                and not str(row.get("audio_hash") or "").strip()
                and (stored_provider, stored_voice) == (effective_provider, effective_voice)
            ):
                # Existing files from before content-addressed metadata can be trusted
                # when their filename identifies the current provider and voice.
                next_status = "ready"
                result["backfilled"] += 1
            elif status == "ready":
                next_status = "pending"
                result["queued"] += 1
            elif status in {"pending", "failed", "missing"}:
                next_status = status
                if (
                    str(row.get("audio_provider") or "").strip().lower() != effective_provider
                    or str(row.get("audio_voice") or "").strip() != effective_voice
                    or str(row.get("audio_hash") or "").strip() != expected_hash
                ):
                    result["updated"] += 1
                else:
                    continue
            else:
                next_status = "pending" if file_ready else "missing"
                result["updated"] += 1

            generated_at = str(row.get("audio_generated_at") or "").strip()
            if next_status == "ready" and not generated_at:
                generated_at = now
            conn.execute(
                """
                UPDATE english_sentences
                SET audio_provider = ?, audio_voice = ?, audio_hash = ?,
                    audio_status = ?, audio_error = ?, audio_generated_at = ?, updated_at = ?
                WHERE id = ? AND COALESCE(deleted_at, '') = ''
                """,
                (
                    effective_provider,
                    effective_voice,
                    expected_hash,
                    next_status,
                    "" if next_status in {"ready", "pending"} else str(row.get("audio_error") or ""),
                    generated_at,
                    now,
                    int(row["id"]),
                ),
            )
    return result


def audio_settings_overview() -> dict[str, Any]:
    settings = get_sentence_audio_settings()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(
                       CASE
                           WHEN COALESCE(audio_provider_override, '') <> ''
                            AND COALESCE(audio_voice_override, '') <> ''
                           THEN 1 ELSE 0
                       END
                   ) AS overridden,
                   SUM(CASE WHEN audio_status = 'pending' THEN 1 ELSE 0 END) AS pending
            FROM english_sentences
            WHERE COALESCE(deleted_at, '') = ''
            """
        ).fetchone()
    counts = dict(row) if row else {}
    total = _safe_int(counts.get("total"))
    overridden = _safe_int(counts.get("overridden"))
    return {
        "global": settings,
        "voices": sentence_audio_voice_catalog(),
        "sample_text": SENTENCE_AUDIO_PREVIEW_TEXT,
        "sentences": {
            "total": total,
            "overridden": overridden,
            "following_global": max(total - overridden, 0),
            "pending": _safe_int(counts.get("pending")),
        },
    }


def set_global_sentence_audio_settings(*, provider: str, voice: str) -> dict[str, Any]:
    clean_provider, clean_voice = validate_sentence_audio_identity(provider, voice)
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO english_audio_settings(id, sentence_provider, sentence_voice, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                sentence_provider = excluded.sentence_provider,
                sentence_voice = excluded.sentence_voice,
                updated_at = excluded.updated_at
            """,
            (clean_provider, clean_voice, now),
        )
    return audio_settings_overview()


def set_sentence_audio_override(
    *,
    sentence_id: int,
    provider: str = "",
    voice: str = "",
    use_global: bool = False,
) -> dict | None:
    settings = get_sentence_audio_settings()
    if use_global:
        override_provider, override_voice = "", ""
    else:
        override_provider, override_voice = validate_sentence_audio_identity(provider, voice)
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (sentence_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        target_row = {
            **data,
            "audio_provider_override": override_provider,
            "audio_voice_override": override_voice,
        }
        target_provider, target_voice = effective_sentence_audio_identity(target_row, settings=settings)
        stored_provider, stored_voice = _stored_sentence_audio_identity(data)
        target_hash = sentence_audio_hash(
            str(data.get("text") or ""),
            provider=target_provider,
            voice=target_voice,
        )
        generation_required = (
            _audio_file(data) is None
            or _clean_audio_status(data.get("audio_status")) != "ready"
            or (stored_provider, stored_voice) != (target_provider, target_voice)
            or str(data.get("audio_hash") or "") != target_hash
        )
        next_status = "pending" if generation_required else _clean_audio_status(data.get("audio_status"))
        next_error = "" if generation_required else str(data.get("audio_error") or "")
        next_hash = (
            target_hash
            if generation_required
            else str(data.get("audio_hash") or "")
        )
        conn.execute(
            """
            UPDATE english_sentences
            SET audio_provider_override = ?,
                audio_voice_override = ?,
                audio_hash = ?,
                audio_status = ?,
                audio_error = ?,
                updated_at = ?
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (
                override_provider,
                override_voice,
                next_hash,
                next_status,
                next_error,
                now,
                sentence_id,
            ),
        )
        updated = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (sentence_id,)).fetchone()
    return serialize_sentence(dict(updated), audio_settings=settings) if updated else None


def queue_global_sentence_audio_regeneration() -> dict[str, Any]:
    settings = get_sentence_audio_settings()
    target_provider = settings["provider"]
    target_voice = settings["voice"]
    now = _now()
    sentence_ids: list[int] = []
    following_global = 0
    with get_connection() as conn:
        rows = rows_to_dicts(
            conn.execute(
                "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
            ).fetchall()
        )
        for data in rows:
            if (
                str(data.get("audio_provider_override") or "").strip()
                and str(data.get("audio_voice_override") or "").strip()
            ):
                continue
            following_global += 1
            stored_provider, stored_voice = _stored_sentence_audio_identity(data)
            target_hash = sentence_audio_hash(
                str(data.get("text") or ""),
                provider=target_provider,
                voice=target_voice,
            )
            already_current = (
                _audio_file(data) is not None
                and _clean_audio_status(data.get("audio_status")) == "ready"
                and (stored_provider, stored_voice) == (target_provider, target_voice)
                and str(data.get("audio_hash") or "") == target_hash
            )
            if already_current:
                continue
            sentence_id = int(data["id"])
            sentence_ids.append(sentence_id)
            conn.execute(
                """
                UPDATE english_sentences
                SET audio_hash = ?, audio_status = 'pending', audio_error = '', updated_at = ?
                WHERE id = ? AND COALESCE(deleted_at, '') = ''
                """,
                (
                    target_hash,
                    now,
                    sentence_id,
                ),
            )
    return {
        "sentence_ids": sentence_ids,
        "queued": len(sentence_ids),
        "unchanged": max(following_global - len(sentence_ids), 0),
        "following_global": following_global,
        "global": settings,
    }


def serialize_sentence(
    row: dict,
    algorithm: dict | None = None,
    *,
    word_network: dict | None = None,
    audio_settings: dict[str, str] | None = None,
) -> dict:
    translations = _normalize_dict(row.get("word_translations_json"))
    tips = _normalize_dict(row.get("word_tips_json"))
    counts = _normalize_dict(row.get("word_play_counts_json"))
    sentence_segments = _normalize_segments(row.get("sentence_segments_json"))
    translation_segments = _normalize_segments(row.get("translation_segments_json"))
    sentence_id = int(row["id"])
    updated_at = str(row.get("updated_at") or "")
    audio_file = _audio_file(row)
    audio_provider, audio_voice = _stored_sentence_audio_identity(row)
    selected_settings = audio_settings or get_sentence_audio_settings()
    effective_provider, effective_voice = effective_sentence_audio_identity(row, settings=selected_settings)
    override_provider = str(row.get("audio_provider_override") or "").strip().lower()
    override_voice = str(row.get("audio_voice_override") or "").strip()
    audio_uses_global = not (override_provider and override_voice)
    audio_status = _clean_audio_status(row.get("audio_status"))
    if audio_status == "ready" and audio_file is None:
        audio_status = "missing"
    audio_is_current = _sentence_audio_is_current(
        row,
        audio_file=audio_file,
        settings=selected_settings,
    )
    audio_needs_regeneration = not audio_is_current
    audio_url = ""
    if audio_is_current and audio_file is not None:
        version = ""
        try:
            version = str(int(audio_file.stat().st_mtime))
        except OSError:
            version = ""
        audio_url = f"/api/english/audio/{sentence_id}"
        if version:
            audio_url = f"{audio_url}?v={version}"
        elif updated_at:
            audio_url = f"{audio_url}?v={updated_at}"
    pronunciations = pronunciation_urls(sentence_id, list(translations.keys()))
    resolved_word_network = word_network
    if resolved_word_network is None and algorithm:
        resolved_word_network = algorithm.get("word_network")
    data = {
        "id": sentence_id,
        "text": row.get("text") or "",
        "word_translations": translations,
        "word_tips": tips,
        "word_play_counts": counts,
        "word_play_total": _safe_int(row.get("word_play_total")),
        "sentence_translation": row.get("sentence_translation") or "",
        "sentence_segments": sentence_segments,
        "translation_segments": translation_segments,
        "translation_pending": (
            not str(row.get("sentence_translation") or "").strip()
            or any(not str(value or "").strip() for value in translations.values())
        ),
        "audio_available": audio_is_current,
        "audio_status": audio_status,
        "audio_provider": audio_provider,
        "audio_voice": audio_voice,
        "audio_provider_override": override_provider,
        "audio_voice_override": override_voice,
        "audio_effective_provider": effective_provider,
        "audio_effective_voice": effective_voice,
        "audio_uses_global": audio_uses_global,
        "audio_needs_regeneration": audio_needs_regeneration,
        "audio_error": row.get("audio_error") or "",
        "audio_generated_at": row.get("audio_generated_at") or "",
        "audio_url": audio_url,
        "pronunciations": pronunciations,
        "word_audio_provider": "edge",
        "word_audio_voice": os.getenv("STUDY_ENGLISH_EDGE_VOICE", DEFAULT_SENTENCE_AUDIO_VOICE).strip()
        or DEFAULT_SENTENCE_AUDIO_VOICE,
        "word_audio_count": len(pronunciations),
        "review_count": _safe_int(row.get("review_count")),
        "deleted_at": row.get("deleted_at") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": updated_at,
    }
    if resolved_word_network is not None:
        data["word_network"] = resolved_word_network
    if algorithm is not None:
        data["algorithm"] = algorithm
    return data


def _search_filter(search: str, params: dict) -> str:
    keyword = search.strip().lower()
    if not keyword:
        return ""
    params["kw"] = f"%{keyword}%"
    if keyword.isdigit():
        params["kw_id"] = int(keyword)
        return """
            AND (
                LOWER(text) LIKE :kw
                OR LOWER(sentence_translation) LIKE :kw
                OR LOWER(word_translations_json) LIKE :kw
                OR id = :kw_id
            )
        """
    return """
        AND (
            LOWER(text) LIKE :kw
            OR LOWER(sentence_translation) LIKE :kw
            OR LOWER(word_translations_json) LIKE :kw
        )
    """


def list_sentences(
    *,
    user_id: int | None = None,
    search: str = "",
    sort: str = "smart",
    page: int = 1,
    page_size: int = 40,
    include_deleted: bool = False,
    resume: bool = False,
) -> dict:
    page = max(int(page or 1), 1)
    page_size = max(1, min(int(page_size or 40), 200))
    audio_settings = get_sentence_audio_settings()
    params: dict[str, Any] = {}
    where = "WHERE 1 = 1"
    if not include_deleted:
        where += " AND COALESCE(deleted_at, '') = ''"
    where += _search_filter(search, params)
    with get_connection() as conn:
        total_row = conn.execute(f"SELECT COUNT(*) AS total FROM english_sentences {where}", params).fetchone()
        rows = rows_to_dicts(conn.execute(f"SELECT * FROM english_sentences {where}", params).fetchall())
        network_rows = rows
        if search or include_deleted:
            network_rows = rows_to_dicts(
                conn.execute(
                    "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = ''"
                ).fetchall()
            )

    sort_key = (sort or "smart").strip().lower()
    needs_standalone_network = sort_key not in SMART_SORTS or network_rows is not rows
    network_metrics_by_id = sentence_word_network_metrics(network_rows) if needs_standalone_network else {}

    def serialize_list_sentence(row: dict, algorithm: dict | None = None) -> dict:
        return serialize_sentence(
            row,
            algorithm,
            word_network=network_metrics_by_id.get(int(row["id"])),
            audio_settings=audio_settings,
        )

    if sort_key in SMART_SORTS:
        ranked_items = _rank_sentences_by_peak_familiarity(rows)
        if user_id is not None and not search and not include_deleted:
            row_by_id = {int(row["id"]): row for row, _ in ranked_items}
            metrics_by_id = {int(row["id"]): metrics for row, metrics in ranked_items}
            with get_connection() as conn:
                state = queue_state(
                    conn,
                    user_id=int(user_id),
                    ordered_sentence_ids=[int(row["id"]) for row, _ in ranked_items],
                    page=page,
                    page_size=page_size,
                    resume=resume,
                )
            items = []
            for record in state["records"]:
                sentence_id = int(record["sentence_id"])
                row = row_by_id.get(sentence_id)
                if not row:
                    continue
                item = serialize_list_sentence(row, metrics_by_id.get(sentence_id))
                item["review_round_position"] = int(record["position"])
                item["review_round_item_completed"] = bool(str(record.get("completed_at") or ""))
                items.append(item)
            return {
                "items": items,
                "total": int(state["total"]),
                "page": int(state["page"]),
                "page_size": page_size,
                "review_round": state["round"],
            }
        items = [
            serialize_list_sentence(row, metrics)
            for row, metrics in ranked_items[(page - 1) * page_size : page * page_size]
        ]
    elif sort_key in {"latest", "created-desc"}:
        rows.sort(key=lambda row: (str(row.get("created_at") or ""), int(row["id"])), reverse=True)
        start = (page - 1) * page_size
        items = [serialize_list_sentence(row) for row in rows[start : start + page_size]]
    elif sort_key in {"oldest", "created-asc"}:
        rows.sort(key=lambda row: (str(row.get("created_at") or ""), int(row["id"])))
        start = (page - 1) * page_size
        items = [serialize_list_sentence(row) for row in rows[start : start + page_size]]
    elif sort_key == "id-desc":
        rows.sort(key=lambda row: int(row["id"]), reverse=True)
        start = (page - 1) * page_size
        items = [serialize_list_sentence(row) for row in rows[start : start + page_size]]
    elif sort_key == "id-asc":
        rows.sort(key=lambda row: int(row["id"]))
        start = (page - 1) * page_size
        items = [serialize_list_sentence(row) for row in rows[start : start + page_size]]
    elif sort_key == "missing-audio":
        rows.sort(
            key=lambda row: (
                1 if _sentence_audio_is_current(row, settings=audio_settings) else 0,
                int(row["id"]),
            )
        )
        start = (page - 1) * page_size
        items = [serialize_list_sentence(row) for row in rows[start : start + page_size]]
    else:
        rows.sort(key=lambda row: (_safe_int(row.get("review_count")), _safe_int(row.get("word_play_total")), int(row["id"])))
        start = (page - 1) * page_size
        items = [serialize_list_sentence(row) for row in rows[start : start + page_size]]
    return {
        "items": items,
        "total": int(total_row["total"] if total_row else 0),
        "page": page,
        "page_size": page_size,
    }


def get_sentence(sentence_id: int, *, include_deleted: bool = False) -> dict | None:
    audio_settings = get_sentence_audio_settings()
    sql = "SELECT * FROM english_sentences WHERE id = ?"
    params: tuple[Any, ...] = (sentence_id,)
    if not include_deleted:
        sql += " AND COALESCE(deleted_at, '') = ''"
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return serialize_sentence(dict(row), audio_settings=audio_settings) if row else None


def _candidate_focus_words(candidate: dict) -> list[dict]:
    words = candidate.get("focus_words") or candidate.get("words") or candidate.get("vocabulary") or []
    if isinstance(words, dict):
        words = [{"word": key, "translation": value} for key, value in words.items()]
    result: list[dict] = []
    seen = set()
    for item in words if isinstance(words, list) else []:
        if isinstance(item, str):
            word = item.strip()
            translation = ""
            tip = ""
        elif isinstance(item, dict):
            word = str(item.get("word") or item.get("surface") or "").strip()
            translation = str(
                item.get("translation")
                or item.get("meaning")
                or item.get("context_translation")
                or ""
            ).strip()
            tip = str(item.get("tip") or item.get("note") or "").strip()
        else:
            continue
        normalized = _normalize_focus_word(word)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append({"word": word, "translation": translation, "tip": tip[:40]})
    return result


def _mark_focus_words(text: str, focus_words: list[dict]) -> str:
    updated = str(text or "").strip()
    if not updated:
        return updated
    marked = {_normalize_focus_word(value) for value in _marked_word_surfaces(updated)}
    for item in focus_words:
        word = str(item.get("word") or "").strip()
        normalized = _normalize_focus_word(word)
        if not word or normalized in marked or not re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)?", word):
            continue
        pattern = re.compile(rf"\b({re.escape(word)})\b", re.IGNORECASE)
        parts = re.split(r"(\*\*.*?\*\*)", updated)
        for index in range(0, len(parts), 2):
            replaced, count = pattern.subn(r"**\1**", parts[index], count=1)
            parts[index] = replaced
            if count:
                marked.add(normalized)
                break
        updated = "".join(parts)
    return updated


def _find_sentence_by_identity(conn, text: str, *, exclude_id: int | None = None):
    identity = sentence_identity_key(text)
    if not identity:
        return None
    rows = conn.execute(
        "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
    ).fetchall()
    for row in rows:
        if exclude_id is not None and int(row["id"]) == int(exclude_id):
            continue
        if sentence_identity_key(str(row["text"] or "")) == identity:
            return row
    return None


def _merge_focus_maps(existing: dict, incoming: dict) -> dict:
    result = {str(key): value for key, value in (existing or {}).items() if str(key).strip()}
    by_normalized = {_normalize_focus_word(key): key for key in result if _normalize_focus_word(key)}
    for raw_key, value in (incoming or {}).items():
        key = str(raw_key or "").strip()
        normalized = _normalize_focus_word(key)
        if not key or not normalized:
            continue
        current_key = by_normalized.get(normalized)
        if current_key:
            if not str(result.get(current_key) or "").strip() and str(value or "").strip():
                result[current_key] = value
            continue
        result[key] = value
        by_normalized[normalized] = key
    return result


def _marked_word_surfaces(text: str) -> list[str]:
    result = []
    seen = set()
    for match in _BOLD_PATTERN.findall(str(text or "")):
        surface = re.sub(r"\s+", " ", str(match or "").strip())
        normalized = _normalize_focus_word(surface)
        if surface and normalized and normalized not in seen:
            result.append(surface)
            seen.add(normalized)
    return result


def _related_focus_key(mapping: dict, surface: str) -> str:
    surface_candidates = set(_word_key_candidates(_normalize_focus_word(surface)))
    for key in mapping:
        key_candidates = set(_word_key_candidates(_normalize_focus_word(key)))
        if surface_candidates and key_candidates and surface_candidates.intersection(key_candidates):
            return str(key)
    return ""


def _coherent_focus_state(text: str, translations: dict, tips: dict, counts: dict) -> tuple[str, dict, dict, dict]:
    source_translations = _normalize_dict(translations)
    source_tips = _normalize_dict(tips)
    source_counts = _normalize_dict(counts)
    output_translations: dict[str, Any] = {}

    for surface in _marked_word_surfaces(text):
        normalized = _normalize_focus_word(surface)
        existing_key = _find_map_key_by_normalized(source_translations, normalized)
        related_key = existing_key or _related_focus_key(source_translations, surface)
        output_translations[surface] = source_translations.get(related_key, "")

    output_tips: dict[str, Any] = {}
    output_counts: dict[str, int] = {}
    for key in output_translations:
        normalized = _normalize_focus_word(key)
        tip_key = _find_map_key_by_normalized(source_tips, normalized) or _related_focus_key(source_tips, key)
        count_key = _find_map_key_by_normalized(source_counts, normalized) or _related_focus_key(source_counts, key)
        if tip_key and str(source_tips.get(tip_key) or "").strip():
            output_tips[key] = source_tips[tip_key]
        if count_key:
            output_counts[key] = _safe_int(source_counts.get(count_key))

    return str(text or "").strip(), output_translations, output_tips, output_counts


def reconcile_sentence_focus_state() -> int:
    repaired = 0
    now = _now()
    with get_connection() as conn:
        begin_immediate(conn)
        rows = rows_to_dicts(
            conn.execute(
                "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
            ).fetchall()
        )
        for row in rows:
            current_translations = _normalize_dict(row.get("word_translations_json"))
            current_tips = _normalize_dict(row.get("word_tips_json"))
            current_counts = _normalize_dict(row.get("word_play_counts_json"))
            _, translations, tips, counts = _coherent_focus_state(
                str(row.get("text") or ""),
                current_translations,
                current_tips,
                current_counts,
            )
            if (
                translations == current_translations
                and tips == current_tips
                and counts == current_counts
                and _calculate_word_total(counts) == _safe_int(row.get("word_play_total"))
            ):
                continue
            conn.execute(
                """
                UPDATE english_sentences
                SET word_translations_json = ?, word_tips_json = ?,
                    word_play_counts_json = ?, word_play_total = ?, updated_at = ?
                WHERE id = ? AND COALESCE(deleted_at, '') = ''
                """,
                (
                    _json_dumps(translations, {}),
                    _json_dumps(tips, {}),
                    _json_dumps(counts, {}),
                    _calculate_word_total(counts),
                    now,
                    int(row["id"]),
                ),
            )
            repaired += 1
    return repaired


def _merge_sentence_focus_data(conn, row: dict, *, text: str, translations: dict, tips: dict, now: str) -> dict:
    existing_translations = _normalize_dict(row.get("word_translations_json"))
    existing_tips = _normalize_dict(row.get("word_tips_json"))
    merged_translations = _merge_focus_maps(existing_translations, translations)
    merged_tips = _merge_focus_maps(existing_tips, tips)
    merged_text, merged_translations, merged_tips, merged_counts = _coherent_focus_state(
        _mark_focus_words(str(row.get("text") or text), [{"word": key} for key in translations]),
        merged_translations,
        merged_tips,
        _normalize_dict(row.get("word_play_counts_json")),
    )
    conn.execute(
        """
        UPDATE english_sentences
        SET text = ?, word_translations_json = ?, word_tips_json = ?,
            word_play_counts_json = ?, word_play_total = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            merged_text,
            _json_dumps(merged_translations, {}),
            _json_dumps(merged_tips, {}),
            _json_dumps(merged_counts, {}),
            _calculate_word_total(merged_counts),
            now,
            int(row["id"]),
        ),
    )
    updated = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (int(row["id"]),)).fetchone()
    return dict(updated)


def _split_marked_passage_sentences(body_text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", str(body_text or "").strip())
    if not text:
        return []
    chunks: list[str] = []
    for paragraph in re.split(r"\n{2,}", text):
        normalized = paragraph.strip()
        if not normalized:
            continue
        matches = re.findall(r"[^.!?。！？]+[.!?。！？]+(?:[\"')\]]+)?|[^.!?。！？]+$", normalized)
        if matches:
            chunks.extend(item.strip() for item in matches if item.strip())
        else:
            chunks.append(normalized)
    return chunks


def _marked_passage_sentence_candidates(body_text: str) -> list[dict]:
    candidates: list[dict] = []
    seen = set()
    for sentence in _split_marked_passage_sentences(body_text):
        focus_words = []
        focus_seen = set()
        for match in _BOLD_PATTERN.findall(sentence):
            surface = re.sub(r"\s+", " ", str(match or "").strip())
            normalized = _normalize_focus_word(surface)
            if not surface or not normalized or normalized in focus_seen:
                continue
            focus_seen.add(normalized)
            focus_words.append({"word": surface, "translation": "", "tip": ""})
        if not focus_words:
            continue
        sentence_key = sentence_identity_key(sentence)
        if not sentence_key or sentence_key in seen:
            continue
        seen.add(sentence_key)
        candidates.append(
            {
                "text": sentence,
                "translation": "",
                "reason": "手工标注",
                "focus_words": focus_words,
            }
        )
    return candidates


def sync_passage_sentences(*, passage_id: int, user_id: int, candidate_indexes: list[int] | None = None) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM english_passages WHERE id = ? AND user_id = ? AND COALESCE(deleted_at, '') = ''",
            (passage_id, user_id),
        ).fetchone()
        if not row:
            return None
        passage = dict(row)
        candidates = _marked_passage_sentence_candidates(passage.get("body_text") or "")
        if not candidates:
            raise ValueError("文章还没有手工标注句子")
        selected = candidate_indexes if candidate_indexes else list(range(len(candidates)))
        normalized_indexes = []
        for value in selected:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(candidates) and index not in normalized_indexes:
                normalized_indexes.append(index)
        if not normalized_indexes:
            raise ValueError("no valid sentence candidates selected")

        now = _now()
        existing_ids = _json_loads(passage.get("selected_sentence_ids_json"), [])
        if not isinstance(existing_ids, list):
            existing_ids = []
        sentence_ids = [int(item) for item in existing_ids if str(item).isdigit()]
        serialized_sentences = []
        inserted = 0
        reused = 0

        for index in normalized_indexes:
            candidate = candidates[index]
            focus_words = _candidate_focus_words(candidate)
            text = _mark_focus_words(candidate["text"], focus_words)
            audio_fields = _initial_sentence_audio_fields(text)
            translations = {
                str(item["word"]): str(item.get("translation") or "")
                for item in focus_words
                if str(item.get("word") or "").strip()
            }
            tips = {
                str(item["word"]): str(item.get("tip") or "")
                for item in focus_words
                if str(item.get("word") or "").strip() and str(item.get("tip") or "").strip()
            }
            existing = _find_sentence_by_identity(conn, text)
            if existing:
                sentence_row = _merge_sentence_focus_data(
                    conn,
                    dict(existing),
                    text=text,
                    translations=translations,
                    tips=tips,
                    now=now,
                )
                reused += 1
            else:
                cur = conn.execute(
                    """
                    INSERT INTO english_sentences(
                        text, word_translations_json, word_tips_json, word_play_counts_json,
                        sentence_translation, sentence_segments_json, translation_segments_json,
                        audio_provider, audio_voice, audio_hash,
                        audio_status, audio_error, audio_generated_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, '{}', ?, '[]', '[]', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        text,
                        _json_dumps(translations, {}),
                        _json_dumps(tips, {}),
                        str(candidate.get("translation") or ""),
                        audio_fields["provider"],
                        audio_fields["voice"],
                        audio_fields["hash"],
                        audio_fields["status"],
                        audio_fields["error"],
                        audio_fields["generated_at"],
                        now,
                        now,
                    ),
                )
                sentence_row = dict(conn.execute("SELECT * FROM english_sentences WHERE id = ?", (int(cur.lastrowid),)).fetchone())
                inserted += 1
            sentence_id = int(sentence_row["id"])
            if sentence_id not in sentence_ids:
                sentence_ids.append(sentence_id)
            serialized_sentences.append(serialize_sentence(sentence_row))

        conn.execute(
            """
            UPDATE english_passages
            SET selected_sentence_ids_json = ?,
                status = CASE WHEN status = 'done' THEN status ELSE 'reading' END,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (_json_dumps(sentence_ids, []), now, passage_id, user_id),
        )
        updated = conn.execute("SELECT * FROM english_passages WHERE id = ? AND user_id = ?", (passage_id, user_id)).fetchone()
    return {
        "passage": serialize_passage(dict(updated)) if updated else None,
        "sentences": serialized_sentences,
        "inserted": inserted,
        "reused": reused,
    }


def _record_event(
    conn,
    *,
    user_id: int,
    event_type: str,
    sentence_id: int | None = None,
    word: str = "",
    metadata: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO english_review_events(user_id, sentence_id, event_type, word, client, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            sentence_id,
            event_type,
            word,
            "web",
            _json_dumps(metadata or {}, {}),
            _now(),
        ),
    )


def review_sentence(
    *,
    user_id: int,
    sentence_id: int,
    event_type: str = "sentence_review",
    complete_round_item: bool = True,
) -> dict | None:
    now = _now()
    clean_event_type = event_type if event_type in {"sentence_play", "sentence_review"} else "sentence_review"
    with get_connection() as conn:
        begin_immediate(conn)
        row = conn.execute(
            "SELECT * FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (sentence_id,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE english_sentences
            SET review_count = review_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (now, sentence_id),
        )
        _record_event(conn, user_id=user_id, event_type=clean_event_type, sentence_id=sentence_id)
        round_result = (
            complete_current_item(conn, user_id=user_id, sentence_id=sentence_id)
            if complete_round_item
            else {"completed": False, "round_completed": False}
        )
        updated = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (sentence_id,)).fetchone()
    if not updated:
        return None
    result = serialize_sentence(dict(updated))
    result["review_round_item_completed"] = bool(round_result.get("completed"))
    result["review_round_completed"] = bool(round_result.get("round_completed"))
    return result


def record_word_play(*, user_id: int, sentence_id: int, word: str) -> dict | None:
    clean_word = str(word or "").strip()
    if not clean_word:
        raise ValueError("word is required")
    now = _now()
    with get_connection() as conn:
        begin_immediate(conn)
        row = conn.execute(
            "SELECT * FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (sentence_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        translations = _normalize_dict(data.get("word_translations_json"))
        counts = _normalize_dict(data.get("word_play_counts_json"))
        key = _find_map_key_by_normalized(translations, _normalize_focus_word(clean_word)) or clean_word
        counts[key] = _safe_int(counts.get(key)) + 1
        word_total = _calculate_word_total(counts)
        conn.execute(
            """
            UPDATE english_sentences
            SET word_play_counts_json = ?,
                word_play_total = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_json_dumps(counts, {}), word_total, now, sentence_id),
        )
        _record_event(conn, user_id=user_id, event_type="word_play", sentence_id=sentence_id, word=clean_word)
        updated = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (sentence_id,)).fetchone()
    return serialize_sentence(dict(updated)) if updated else None


def create_sentence(
    *,
    text: str,
    word_translations: dict | None = None,
    word_tips: dict | None = None,
    sentence_translation: str = "",
    sentence_segments: list[str] | None = None,
    translation_segments: list[str] | None = None,
) -> dict:
    now = _now()
    text, word_translations, word_tips, _ = _coherent_focus_state(
        text,
        word_translations or {},
        word_tips or {},
        {},
    )
    audio_fields = _initial_sentence_audio_fields(text)
    with get_connection() as conn:
        begin_immediate(conn)
        existing = _find_sentence_by_identity(conn, text)
        if existing:
            merged = _merge_sentence_focus_data(
                conn,
                dict(existing),
                text=text,
                translations=word_translations or {},
                tips=word_tips or {},
                now=now,
            )
            if sentence_translation and not str(merged.get("sentence_translation") or "").strip():
                conn.execute(
                    """
                    UPDATE english_sentences
                    SET sentence_translation = ?, sentence_segments_json = ?, translation_segments_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        sentence_translation,
                        _json_dumps(_normalize_segments(sentence_segments or []), []),
                        _json_dumps(_normalize_segments(translation_segments or []), []),
                        now,
                        int(merged["id"]),
                    ),
                )
                merged = dict(conn.execute("SELECT * FROM english_sentences WHERE id = ?", (int(merged["id"]),)).fetchone())
            return serialize_sentence(merged)
        cur = conn.execute(
            """
            INSERT INTO english_sentences(
                text, word_translations_json, word_tips_json, word_play_counts_json,
                sentence_translation, sentence_segments_json, translation_segments_json,
                audio_provider, audio_voice, audio_hash,
                audio_status, audio_error, audio_generated_at, created_at, updated_at
            )
            VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                text,
                _json_dumps(word_translations or {}, {}),
                _json_dumps(word_tips or {}, {}),
                sentence_translation,
                _json_dumps(_normalize_segments(sentence_segments or []), []),
                _json_dumps(_normalize_segments(translation_segments or []), []),
                audio_fields["provider"],
                audio_fields["voice"],
                audio_fields["hash"],
                audio_fields["status"],
                audio_fields["error"],
                audio_fields["generated_at"],
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (int(cur.lastrowid),)).fetchone()
    return serialize_sentence(dict(row))


def create_sentences_bulk(items: list[dict]) -> dict:
    created = 0
    reused = 0
    sentences = []
    with get_connection() as conn:
        begin_immediate(conn)
        for item in items:
            now = _now()
            text, translations, tips, _ = _coherent_focus_state(
                str(item.get("text") or ""),
                item.get("word_translations") or {},
                item.get("word_tips") or {},
                {},
            )
            if not text:
                raise ValueError("sentence text is required")
            existing = _find_sentence_by_identity(conn, text)
            if existing:
                row = _merge_sentence_focus_data(
                    conn,
                    dict(existing),
                    text=text,
                    translations=translations,
                    tips=tips,
                    now=now,
                )
                reused += 1
            else:
                audio_fields = _initial_sentence_audio_fields(text)
                cur = conn.execute(
                    """
                    INSERT INTO english_sentences(
                        text, word_translations_json, word_tips_json, word_play_counts_json,
                        sentence_translation, sentence_segments_json, translation_segments_json,
                        audio_provider, audio_voice, audio_hash,
                        audio_status, audio_error, audio_generated_at, created_at, updated_at
                    ) VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        text,
                        _json_dumps(translations, {}),
                        _json_dumps(tips, {}),
                        str(item.get("sentence_translation") or ""),
                        _json_dumps(_normalize_segments(item.get("sentence_segments") or []), []),
                        _json_dumps(_normalize_segments(item.get("translation_segments") or []), []),
                        audio_fields["provider"],
                        audio_fields["voice"],
                        audio_fields["hash"],
                        audio_fields["status"],
                        audio_fields["error"],
                        audio_fields["generated_at"],
                        now,
                        now,
                    ),
                )
                row = dict(conn.execute("SELECT * FROM english_sentences WHERE id = ?", (int(cur.lastrowid),)).fetchone())
                created += 1
            sentences.append(serialize_sentence(row))
    return {"items": sentences, "created": created, "reused": reused}


def update_sentence(
    *,
    sentence_id: int,
    text: str,
    word_translations: dict | None = None,
    word_tips: dict | None = None,
    sentence_translation: str = "",
    sentence_segments: list[str] | None = None,
    translation_segments: list[str] | None = None,
) -> dict | None:
    now = _now()
    audio_settings = get_sentence_audio_settings()
    with get_connection() as conn:
        begin_immediate(conn)
        existing = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (sentence_id,)).fetchone()
        if not existing:
            return None
        existing_data = dict(existing)
        incoming_text = str(text or "").strip()
        translation_source_changed = (
            sentence_translation_source_key(incoming_text)
            != sentence_translation_source_key(str(existing_data.get("text") or ""))
        )
        existing_translations = _normalize_dict(existing_data.get("word_translations_json"))
        incoming_translations = _normalize_dict(word_translations or {})
        manually_changed_word_translation = False
        for raw_key, raw_value in incoming_translations.items():
            value = str(raw_value or "").strip()
            if not value:
                continue
            key = str(raw_key or "").strip()
            existing_key = _find_map_key_by_normalized(existing_translations, _normalize_focus_word(key))
            if not existing_key or value != str(existing_translations.get(existing_key) or "").strip():
                manually_changed_word_translation = True
                break
        sentence_payload_changed = (
            str(sentence_translation or "").strip()
            != str(existing_data.get("sentence_translation") or "").strip()
            or _normalize_segments(sentence_segments or [])
            != _normalize_segments(existing_data.get("sentence_segments_json"))
            or _normalize_segments(translation_segments or [])
            != _normalize_segments(existing_data.get("translation_segments_json"))
        )
        reset_stale_sentence = translation_source_changed and not sentence_payload_changed
        reset_stale_words = translation_source_changed and not manually_changed_word_translation
        focus_translations = (
            {surface: "" for surface in _marked_word_surfaces(incoming_text)}
            if reset_stale_words
            else incoming_translations
        )
        text, word_translations, word_tips, word_counts = _coherent_focus_state(
            incoming_text,
            focus_translations,
            {} if reset_stale_words else (word_tips or {}),
            _normalize_dict(existing_data.get("word_play_counts_json")),
        )
        if reset_stale_sentence:
            sentence_translation = ""
            sentence_segments = []
            translation_segments = []
        duplicate = _find_sentence_by_identity(conn, text, exclude_id=sentence_id)
        if duplicate:
            raise ValueError(f"相同句子已存在：#{int(duplicate['id'])}")
        provider, voice = effective_sentence_audio_identity(existing_data, settings=audio_settings)
        next_hash = sentence_audio_hash(text, provider=provider, voice=voice)
        current_hash = str(existing_data.get("audio_hash") or "")
        current_provider = str(existing_data.get("audio_provider") or "")
        current_voice = str(existing_data.get("audio_voice") or "")
        stored_provider, stored_voice = _stored_sentence_audio_identity(existing_data)
        plain_text_changed = plain_sentence_audio_text(text) != plain_sentence_audio_text(str(existing_data.get("text") or ""))
        audio_changed = (
            plain_text_changed
            or not str(existing_data.get("audio_path") or "").strip()
            or (stored_provider, stored_voice) != (provider, voice)
        )
        if audio_changed:
            next_provider = current_provider
            next_voice = current_voice
            audio_status = "pending"
            audio_error = ""
            audio_generated_at = ""
        else:
            next_provider = current_provider
            next_voice = current_voice
            next_hash = current_hash
            audio_status = _clean_audio_status(existing_data.get("audio_status"))
            audio_error = str(existing_data.get("audio_error") or "")
            audio_generated_at = str(existing_data.get("audio_generated_at") or "")
        conn.execute(
            """
            UPDATE english_sentences
            SET text = ?,
                word_translations_json = ?,
                word_tips_json = ?,
                word_play_counts_json = ?,
                word_play_total = ?,
                sentence_translation = ?,
                sentence_segments_json = ?,
                translation_segments_json = ?,
                audio_provider = ?,
                audio_voice = ?,
                audio_hash = ?,
                audio_status = ?,
                audio_error = ?,
                audio_generated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                text,
                _json_dumps(word_translations or {}, {}),
                _json_dumps(word_tips or {}, {}),
                _json_dumps(word_counts, {}),
                _calculate_word_total(word_counts),
                sentence_translation,
                _json_dumps(_normalize_segments(sentence_segments or []), []),
                _json_dumps(_normalize_segments(translation_segments or []), []),
                next_provider,
                next_voice,
                next_hash,
                audio_status,
                audio_error,
                audio_generated_at,
                now,
                sentence_id,
            ),
        )
        row = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (sentence_id,)).fetchone()
    return serialize_sentence(dict(row), audio_settings=audio_settings) if row else None


def delete_sentence(*, sentence_id: int) -> bool:
    now = _now()
    with get_connection() as conn:
        before = conn.total_changes
        conn.execute(
            """
            UPDATE english_sentences
            SET deleted_at = ?,
                updated_at = ?
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (now, now, sentence_id),
        )
        return conn.total_changes > before


def _focus_word_display(value: str) -> str:
    match = _WORD_PATTERN.search(str(value or ""))
    return match.group(0) if match else str(value or "").strip()


def _remove_map_key_by_normalized(mapping: dict, normalized_word: str) -> dict:
    return {
        str(key): value
        for key, value in (mapping or {}).items()
        if _normalize_focus_word(key) != normalized_word
    }


def _find_map_key_by_normalized(mapping: dict, normalized_word: str) -> str:
    for key in (mapping or {}).keys():
        if _normalize_focus_word(key) == normalized_word:
            return str(key)
    return ""


def toggle_focus_word(*, user_id: int, sentence_id: int, word: str, action: str = "toggle") -> dict | None:
    clean_word = _focus_word_display(word)
    normalized = _normalize_focus_word(clean_word)
    if not normalized:
        raise ValueError("word is required")
    action = action if action in {"toggle", "mark", "unmark"} else "toggle"
    now = _now()

    with get_connection() as conn:
        begin_immediate(conn)
        row = conn.execute(
            "SELECT * FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (sentence_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        source = str(data.get("text") or "")
        already_marked = any(_normalize_focus_word(match.group(1)) == normalized for match in _BOLD_PATTERN.finditer(source))
        should_mark = True if action == "mark" else False if action == "unmark" else not already_marked

        if should_mark and not already_marked:
            pattern = re.compile(rf"\b({re.escape(clean_word)})\b", re.IGNORECASE)
            updated_text = pattern.sub(r"**\1**", source, count=1)
        elif not should_mark and already_marked:
            def unmark(match: re.Match) -> str:
                inner = match.group(1)
                return inner if _normalize_focus_word(inner) == normalized else match.group(0)

            updated_text = _BOLD_PATTERN.sub(unmark, source)
        else:
            updated_text = source

        translations = _normalize_dict(data.get("word_translations_json"))
        tips = _normalize_dict(data.get("word_tips_json"))
        counts = _normalize_dict(data.get("word_play_counts_json"))
        if should_mark:
            key = _find_map_key_by_normalized(translations, normalized) or clean_word
            translations.setdefault(key, "")
        else:
            translations = _remove_map_key_by_normalized(translations, normalized)
            tips = _remove_map_key_by_normalized(tips, normalized)
            counts = _remove_map_key_by_normalized(counts, normalized)

        conn.execute(
            """
            UPDATE english_sentences
            SET text = ?,
                word_translations_json = ?,
                word_tips_json = ?,
                word_play_counts_json = ?,
                word_play_total = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                updated_text,
                _json_dumps(translations, {}),
                _json_dumps(tips, {}),
                _json_dumps(counts, {}),
                _calculate_word_total(counts),
                now,
                sentence_id,
            ),
        )
        _record_event(
            conn,
            user_id=user_id,
            event_type="focus_word_toggle",
            sentence_id=sentence_id,
            word=clean_word,
            metadata={"action": "mark" if should_mark else "unmark"},
        )
        updated = conn.execute("SELECT * FROM english_sentences WHERE id = ?", (sentence_id,)).fetchone()
    return serialize_sentence(dict(updated)) if updated else None


def audio_file_for_sentence(sentence_id: int) -> Path | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (sentence_id,),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    audio_file = _audio_file(data)
    if not _sentence_audio_is_current(
        data,
        audio_file=audio_file,
        settings=get_sentence_audio_settings(),
    ):
        return None
    return audio_file


def pronunciation_file(sentence_id: int, filename: str) -> Path | None:
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename:
        return None
    folder = ENGLISH_PRONUNCIATION_DIR / f"sentence_{sentence_id}"
    path = folder / safe_name
    if not path.exists() or not path.is_file():
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (sentence_id,),
        ).fetchone()
    return path if row else None
