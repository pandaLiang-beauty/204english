from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.audio_generation import (  # noqa: E402
    DEFAULT_EDGE_VOICE,
    DEFAULT_KOKORO_VOICE,
    generate_sentence_audio_for_rows,
    generate_word_audio_for_rows,
    load_rows_for_generation,
)


def _parse_ids(value: str) -> list[int]:
    ids: list[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            sentence_id = int(part)
        except ValueError:
            continue
        if sentence_id > 0 and sentence_id not in ids:
            ids.append(sentence_id)
    return ids


def _non_empty_word_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("word_translations_json") or "").strip() not in {"", "{}"}]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate English sentence and word audio files.")
    parser.add_argument("--ids", default="", help="Comma-separated english_sentences ids.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--words", action="store_true", help="Generate Edge TTS word/pronunciation audio.")
    parser.add_argument("--sentences", action="store_true", help="Generate Kokoro sentence audio.")
    parser.add_argument("--edge-voice", default=DEFAULT_EDGE_VOICE)
    parser.add_argument("--kokoro-voice", default=DEFAULT_KOKORO_VOICE)
    parser.add_argument("--edge-sleep", type=float, default=0.0)
    parser.add_argument("--max-words", type=int, default=0)
    parser.add_argument("--max-sentences", type=int, default=0)
    args = parser.parse_args()

    generate_words = args.words or not args.sentences
    generate_sentences = args.sentences
    ids = _parse_ids(args.ids)
    rows = load_rows_for_generation(ids=ids or None, limit=0 if ids else max(int(args.limit or 0), 0))

    result: dict[str, Any] = {
        "selected_rows": len(rows),
        "ids": [int(row["id"]) for row in rows],
    }
    if generate_words:
        word_rows = _non_empty_word_rows(rows)
        result["words"] = asyncio.run(
            generate_word_audio_for_rows(
                word_rows,
                overwrite=args.overwrite,
                voice=args.edge_voice,
                max_words=max(int(args.max_words or 0), 0),
                sleep_seconds=max(float(args.edge_sleep or 0), 0.0),
                dry_run=args.dry_run,
            )
        )
    if generate_sentences:
        result["sentences"] = generate_sentence_audio_for_rows(
            rows,
            overwrite=args.overwrite,
            provider="kokoro",
            voice=args.kokoro_voice,
            max_sentences=max(int(args.max_sentences or 0), 0),
            dry_run=args.dry_run,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
