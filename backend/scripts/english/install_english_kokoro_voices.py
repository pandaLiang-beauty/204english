from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.english import repository  # noqa: E402


VOICE_SOURCE = "https://cdn.jsdelivr.net/gh/hexgrad/kokoro@main/kokoro.js/voices"
VOICE_SHAPE = (510, 1, 256)
VOICE_BYTES = 510 * 1 * 256 * 4
MODEL_REPOSITORY = "hexgrad/Kokoro-82M"
MODEL_FILES = {
    "config.json": "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f",
    "kokoro-v1_0.pth": "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_base_model(model_dir: Path, *, force: bool = False) -> list[str]:
    pending = [
        filename
        for filename, expected_hash in MODEL_FILES.items()
        if force
        or not (model_dir / filename).is_file()
        or _sha256(model_dir / filename) != expected_hash
    ]
    if not pending:
        return []

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError("huggingface-hub is required to install the Kokoro base model") from exc

    model_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for filename in pending:
        cached_path = Path(
            hf_hub_download(
                repo_id=MODEL_REPOSITORY,
                filename=filename,
            )
        )
        if _sha256(cached_path) != MODEL_FILES[filename]:
            raise RuntimeError(f"invalid Kokoro base model checksum: {filename}")
        temp_path = model_dir / f".{filename}.tmp"
        shutil.copyfile(cached_path, temp_path)
        temp_path.replace(model_dir / filename)
        (model_dir / filename).chmod(0o644)
        installed.append(filename)
        print(f"installed {filename}", flush=True)
    return installed


def _installed_voice_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        import torch

        voice = torch.load(path, map_location="cpu", weights_only=True)
    except Exception:  # noqa: BLE001 - a corrupt voice must be replaced.
        return False
    return tuple(voice.shape) == VOICE_SHAPE and str(voice.dtype) == "torch.float32"


def _download_voice(voice: str, path: Path, *, retries: int = 12) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{VOICE_SOURCE}/{voice}.bin"
    for attempt in range(1, retries + 1):
        current_size = path.stat().st_size if path.exists() else 0
        if current_size == VOICE_BYTES:
            return
        if current_size > VOICE_BYTES:
            path.unlink()
            current_size = 0
        headers = {"User-Agent": "english-study-kokoro-installer/1.0"}
        if current_size:
            headers["Range"] = f"bytes={current_size}-"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed trusted source.
                append = current_size > 0 and getattr(response, "status", 200) == 206
                with path.open("ab" if append else "wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise RuntimeError(f"failed to download Kokoro voice {voice}: {exc}") from exc
            time.sleep(min(attempt * 2, 10))
            continue
        if path.stat().st_size == VOICE_BYTES:
            return
        if attempt < retries:
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"invalid Kokoro voice size for {voice}: {path.stat().st_size}")


def _convert_voice(raw_path: Path, target_path: Path) -> None:
    import numpy as np
    import torch

    raw = np.fromfile(raw_path, dtype="<f4")
    if raw.size != VOICE_SHAPE[0] * VOICE_SHAPE[1] * VOICE_SHAPE[2]:
        raise RuntimeError(f"invalid Kokoro voice tensor: {raw_path.name}")
    voice = torch.from_numpy(raw.copy().reshape(VOICE_SHAPE))
    temp_path = target_path.with_suffix(".pt.tmp")
    torch.save(voice, temp_path)
    temp_path.replace(target_path)
    target_path.chmod(0o644)


def install_voices(*, force: bool = False, workers: int = 4) -> dict:
    configured_dir = os.getenv("STUDY_ENGLISH_KOKORO_MODEL_DIR", "").strip()
    model_dir = Path(configured_dir).expanduser() if configured_dir else repository.ENGLISH_DATA_DIR / "kokoro"
    voices_dir = model_dir / "voices"
    download_dir = voices_dir / ".downloads"
    installed_model_files = _ensure_base_model(model_dir, force=force)
    voices = [item["voice"] for item in repository.SENTENCE_AUDIO_VOICES if item["provider"] == "kokoro"]
    installed: list[str] = []
    skipped: list[str] = []
    pending: list[str] = []
    for voice in voices:
        target_path = voices_dir / f"{voice}.pt"
        if not force and _installed_voice_valid(target_path):
            skipped.append(voice)
            continue
        pending.append(voice)

    def install_one(voice: str) -> str:
        target_path = voices_dir / f"{voice}.pt"
        raw_path = download_dir / f"{voice}.bin.part"
        _download_voice(voice, raw_path)
        _convert_voice(raw_path, target_path)
        raw_path.unlink(missing_ok=True)
        if not _installed_voice_valid(target_path):
            raise RuntimeError(f"installed Kokoro voice failed validation: {voice}")
        return voice

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 8))) as executor:
        futures = {executor.submit(install_one, voice): voice for voice in pending}
        for future in as_completed(futures):
            voice = future.result()
            installed.append(voice)
            print(f"installed {voice}", flush=True)
    try:
        download_dir.rmdir()
    except OSError:
        pass
    return {
        "model_files": len(MODEL_FILES),
        "installed_model_files": installed_model_files,
        "voices": len(voices),
        "installed": [voice for voice in voices if voice in installed],
        "skipped": skipped,
        "directory": str(voices_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install all official English Kokoro voices.")
    parser.add_argument("--force", action="store_true", help="Redownload voices that already pass validation.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel downloads (1-8).")
    args = parser.parse_args()
    print(json.dumps(install_voices(force=args.force, workers=args.workers), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
