from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.english import audio_generation, repository  # noqa: E402


def generate_previews(*, provider: str = "kokoro", overwrite: bool = False) -> dict:
    voices = [
        item
        for item in repository.sentence_audio_voice_catalog()
        if provider == "all" or item["provider"] == provider
    ]
    unavailable = [item["voice"] for item in voices if not item["available"]]
    if unavailable:
        raise RuntimeError(f"unavailable voices: {', '.join(unavailable)}")

    generated: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    kokoro_model = None
    kokoro_pipelines = {}

    for item in voices:
        voice_provider = item["provider"]
        voice = item["voice"]
        path = audio_generation._voice_preview_path(provider=voice_provider, voice=voice)
        if not overwrite and path.is_file() and path.stat().st_size > 0:
            skipped.append(voice)
            print(f"cached {voice}", flush=True)
            continue
        try:
            if voice_provider == "kokoro":
                if kokoro_model is None:
                    kokoro_model = audio_generation._kokoro_model()
                lang_code = audio_generation._kokoro_language_code(voice)
                if lang_code not in kokoro_pipelines:
                    kokoro_pipelines[lang_code] = audio_generation._kokoro_pipeline(
                        lang_code=lang_code,
                        model=kokoro_model,
                    )
                audio_generation._kokoro_generate_audio(
                    repository.SENTENCE_AUDIO_PREVIEW_TEXT,
                    path,
                    voice=voice,
                    pipeline=kokoro_pipelines[lang_code],
                )
            else:
                audio_generation.generate_voice_preview(provider=voice_provider, voice=voice)
            generated.append(voice)
            print(f"generated {voice}", flush=True)
        except Exception as exc:  # noqa: BLE001 - report every failed voice in one batch.
            failed.append({"voice": voice, "error": str(exc)[:240]})
            print(f"failed {voice}: {exc}", flush=True)

    return {
        "provider": provider,
        "voices": len(voices),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-generate English voice preview audio.")
    parser.add_argument("--provider", choices=("kokoro", "edge", "all"), default="kokoro")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = generate_previews(provider=args.provider, overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
