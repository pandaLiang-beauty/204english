from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.schema import initialize_schema as initialize_english_schema  # noqa: E402
from app.platform.db import DATA_DIR, get_connection, initialize_database  # noqa: E402


DEFAULT_SOURCE_DB = DATA_DIR / "english" / "source" / "sentences.db"
DEFAULT_SOURCE_AUDIO = DATA_DIR / "english" / "source" / "audio"
TARGET_AUDIO = DATA_DIR / "english" / "audio"


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
    parsed = _json_loads(value, fallback)
    if not isinstance(parsed, type(fallback)):
        parsed = fallback
    return json.dumps(parsed, ensure_ascii=False)


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _copy_audio(source_audio: Path) -> tuple[int, int]:
    if not source_audio.exists():
        return 0, 0
    TARGET_AUDIO.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for source in source_audio.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_audio)
        target = TARGET_AUDIO / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size == source.stat().st_size:
            skipped += 1
            continue
        shutil.copy2(source, target)
        copied += 1
    return copied, skipped


def _rows(source_db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM sentences ORDER BY id"))
    finally:
        conn.close()


def _import_rows(rows: list[sqlite3.Row]) -> int:
    initialize_database()
    initialize_english_schema()
    with get_connection() as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO english_sentences(
                    id,
                    text,
                    word_translations_json,
                    word_tips_json,
                    word_play_counts_json,
                    audio_path,
                    audio_provider,
                    audio_voice,
                    audio_hash,
                    audio_status,
                    audio_error,
                    audio_generated_at,
                    review_count,
                    word_play_total,
                    sentence_translation,
                    deleted_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    word_translations_json = excluded.word_translations_json,
                    word_tips_json = excluded.word_tips_json,
                    word_play_counts_json = excluded.word_play_counts_json,
                    audio_path = excluded.audio_path,
                    audio_provider = excluded.audio_provider,
                    audio_voice = excluded.audio_voice,
                    audio_hash = excluded.audio_hash,
                    audio_status = excluded.audio_status,
                    audio_error = excluded.audio_error,
                    audio_generated_at = excluded.audio_generated_at,
                    review_count = excluded.review_count,
                    word_play_total = excluded.word_play_total,
                    sentence_translation = excluded.sentence_translation,
                    deleted_at = excluded.deleted_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    int(row["id"]),
                    str(row["text"] or ""),
                    _json_dumps(row["word_translations"], {}),
                    _json_dumps(row["word_tips"], {}),
                    _json_dumps(row["word_pronunciation_counts"], {}),
                    str(row["audio_path"] or ""),
                    "legacy" if str(row["audio_path"] or "").strip() else "",
                    "",
                    "",
                    "ready" if str(row["audio_path"] or "").strip() else "missing",
                    "",
                    str(row["updated_at"] or "") if str(row["audio_path"] or "").strip() else "",
                    _safe_int(row["review_count"]),
                    _safe_int(row["word_review_total"]),
                    str(row["sentence_translation"] or ""),
                    str(row["deleted_at"] or ""),
                    str(row["created_at"] or ""),
                    str(row["updated_at"] or ""),
                ),
            )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy TTS Review sentences into the English vertical.")
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--source-audio", type=Path, default=DEFAULT_SOURCE_AUDIO)
    parser.add_argument("--skip-audio", action="store_true")
    args = parser.parse_args()

    source_db = args.source_db.expanduser().resolve()
    if not source_db.exists():
        raise SystemExit(f"source db not found: {source_db}")

    source_audio = args.source_audio.expanduser().resolve()
    copied = skipped = 0
    if not args.skip_audio:
        copied, skipped = _copy_audio(source_audio)

    count = _import_rows(_rows(source_db))
    print(json.dumps({"sentences": count, "audio_copied": copied, "audio_skipped": skipped}, ensure_ascii=False))


if __name__ == "__main__":
    main()
