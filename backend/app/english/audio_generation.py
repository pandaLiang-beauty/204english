from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..platform.db import get_connection, rows_to_dicts
from . import repository


# 子进程要以 backend/ 为 cwd 才能 `-m app.english.kokoro_worker`。
BACKEND_ROOT = Path(__file__).resolve().parents[2]


DEFAULT_EDGE_VOICE = repository.DEFAULT_WORD_AUDIO_VOICE
DEFAULT_KOKORO_VOICE = "af_heart"
DEFAULT_KOKORO_SAMPLE_RATE = 24000
KOKORO_TARGET_LOUDNESS_LUFS = -16.0
KOKORO_TARGET_TRUE_PEAK_DBFS = -1.0
KOKORO_TARGET_LRA = 7.0
KOKORO_SILENCE_PEAK = 1e-5
DEFAULT_KOKORO_MODEL_DIR = repository.ENGLISH_DATA_DIR / "kokoro"
VOICE_PREVIEW_DIR = repository.ENGLISH_AUDIO_DIR / "previews"
_SENTENCE_GENERATION_LOCK = threading.Lock()
_KOKORO_LOAD_LOCK = threading.Lock()


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


def _normalize_kokoro_loudness(source_path: Path, output_path: Path) -> None:
    """Normalize a completed Kokoro sentence by perceived loudness.

    Peak normalization alone cannot fix speech with isolated high peaks but a
    low average level. FFmpeg's EBU R128 loudnorm filter brings the integrated
    loudness close to -16 LUFS while its true-peak limiter keeps playback below
    -1 dBFS.
    """
    loudnorm_filter = (
        f"loudnorm=I={KOKORO_TARGET_LOUDNESS_LUFS:g}:"
        f"TP={KOKORO_TARGET_TRUE_PEAK_DBFS:g}:LRA={KOKORO_TARGET_LRA:g}"
    )
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-af",
                loudnorm_filter,
                "-ar",
                str(DEFAULT_KOKORO_SAMPLE_RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required for Kokoro loudness normalization") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Kokoro loudness normalization timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown ffmpeg error").strip()[-240:]
        raise RuntimeError(f"Kokoro loudness normalization failed: {detail}")
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError("Kokoro loudness normalization wrote an empty audio file")


def _write_kokoro_audio(audio: Any, path: Path) -> None:
    """Write one complete Kokoro waveform with loudness normalization."""
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - depends on optional packages.
        raise RuntimeError("numpy and soundfile are required for sentence audio") from exc

    samples = np.asarray(audio)
    if samples.size == 0:
        raise RuntimeError("kokoro produced empty audio")
    path.parent.mkdir(parents=True, exist_ok=True)

    # Both files live beside the destination so the final replace is atomic:
    # readers see either the old file or the fully normalized new one.
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=".raw.wav", delete=False, dir=str(path.parent)
    ) as handle:
        raw_path = Path(handle.name)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=".normalized.wav", delete=False, dir=str(path.parent)
    ) as handle:
        normalized_path = Path(handle.name)
    try:
        sf.write(raw_path, samples, DEFAULT_KOKORO_SAMPLE_RATE, format="WAV")
        if not raw_path.is_file() or raw_path.stat().st_size <= 0:
            raise RuntimeError("kokoro wrote an empty audio file")
        completed_path = raw_path
        if float(np.max(np.abs(samples))) >= KOKORO_SILENCE_PEAK:
            _normalize_kokoro_loudness(raw_path, normalized_path)
            completed_path = normalized_path
        completed_path.replace(path)
        _make_audio_readable(path)
    finally:
        raw_path.unlink(missing_ok=True)
        normalized_path.unlink(missing_ok=True)


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


@contextmanager
def _torch_mmap_load(torch: Any) -> Any:
    """Force torch.load to memory-map checkpoints while KModel is constructed.

    kokoro-v1_0.pth is ~312MB and KModel reads the whole state dict into
    anonymous memory before copying it into the freshly built modules, so the
    load transiently needs ~2x the checkpoint. On a small box that spike is what
    gets the process OOM-killed. mmap=True keeps those pages file-backed and
    evictable, which drops peak anonymous memory by roughly the checkpoint size.

    torch.load is global, so the swap is serialised: two concurrent loads would
    otherwise restore each other's wrapper instead of the original.
    """
    with _KOKORO_LOAD_LOCK:
        original = torch.load

        def load(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("mmap", True)
            return original(*args, **kwargs)

        torch.load = load
        try:
            yield
        finally:
            torch.load = original


def _kokoro_model():
    try:
        import torch

        from kokoro import KModel
    except ImportError as exc:  # pragma: no cover - depends on optional packages.
        raise RuntimeError("kokoro is required for sentence audio") from exc

    model_dir = _kokoro_model_dir()
    config_path = model_dir / "config.json"
    model_path = model_dir / "kokoro-v1_0.pth"
    local_files = (config_path.is_file(), model_path.is_file())
    if any(local_files) and not all(local_files):
        raise RuntimeError(f"incomplete Kokoro model files in {model_dir}")
    with _torch_mmap_load(torch):
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


class _KokoroWorkerDied(RuntimeError):
    """子进程没了（多半是内存不足被内核杀的）。换个新的重试有意义。"""


class _KokoroWorker:
    """把 Kokoro 合成隔离到子进程，批次结束就把 torch 的内存还给系统。

    父进程（uvicorn）绝不能 import torch：实测 import 一次后端常驻 RSS 就从 78MB
    钉在 700MB 不再回落，其中 671MB 是不可回收的匿名内存。子进程退出则整块地址
    空间由内核收回，常驻增量归零。

    一个批次共用一个子进程，模型只加载一次（约 25 秒），之后每句约 8 秒；
    每句一行 JSON 往返。
    """

    def __init__(self) -> None:
        self._proc: Any = None

    def _ensure(self) -> Any:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        # -u 关掉缓冲，否则一行一行的握手会卡在管道缓冲区里互相等。
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "app.english.kokoro_worker"],
            cwd=str(BACKEND_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return self._proc

    def generate(self, text: str, path: Path, *, voice: str) -> None:
        """合成一句。子进程若中途死了就换一个新的再试一次。

        实测子进程内存并不随句子累积，稳定在 1.15GB 左右；但那 1.15GB 里有 976MB
        是合成开始前就产生的固定开销（torch 202 + kokoro 依赖 211 + KModel 453 +
        KPipeline 110），本来就贴着这台机器的可用内存跑。所以它是不是被 kill 取决于
        当时的整机压力（global_oom，同节点其它进程也在抢），是概率事件而非必然。
        不重试的话，撞上的那一句会被判 failed 永久留在库里，而它单独跑完全没问题。
        """
        last_error = ""
        for attempt in (1, 2):
            try:
                return self._generate_once(text, path, voice=voice)
            except _KokoroWorkerDied as exc:
                # 只有进程真死了才值得重试。worker 干净地返回业务错误（空文本之类）
                # 时不能走这里——那种错误重试多少次都一样，白付 25 秒模型重载。
                last_error = str(exc)
                self.close()  # 换一个干净的子进程，顺带把内存还给系统
                if attempt == 2:
                    raise RuntimeError(f"{last_error}（换新子进程重试 1 次仍失败）") from exc
        raise RuntimeError(last_error)

    def _generate_once(self, text: str, path: Path, *, voice: str) -> None:
        proc = self._ensure()
        job = json.dumps({"text": text, "path": str(path), "voice": voice}, ensure_ascii=False)
        try:
            proc.stdin.write(job + "\n")
            proc.stdin.flush()
            reply = proc.stdout.readline()
        except (BrokenPipeError, ValueError) as exc:
            raise _KokoroWorkerDied(f"kokoro worker died: {type(exc).__name__}") from exc
        if not reply:
            raise _KokoroWorkerDied(f"kokoro worker exited without a reply ({self._death_reason(proc)})")
        result = json.loads(reply)
        if not result.get("ok"):
            # 进程还活着，只是这一句合成失败——原样抛出，不重试、不重启 worker。
            raise RuntimeError(str(result.get("error") or "kokoro worker failed"))

    @staticmethod
    def _death_reason(proc: Any) -> str:
        """子进程为什么没了。退出码比 stderr 有用得多——被 OOM killer 端掉时
        stderr 里一个字都没有，只有 returncode=-9 能说明问题。之前这里只取
        stderr 末尾 240 字符，结果截到的是无关的 spaCy 版本警告，真因全被盖住。"""
        try:
            code = proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            code = None
        detail = f"returncode={code}"
        if code == -9:
            detail += " SIGKILL，几乎可以肯定是内存不足被内核杀的"
        elif code == -11:
            detail += " SIGSEGV"
        stderr = ""
        if proc.stderr is not None:
            try:
                raw = proc.stderr.read() or ""
            except Exception:  # noqa: BLE001
                raw = ""
            # 滤掉 torch/spaCy 那些每次都刷的警告，只留真正的报错行。
            lines = [
                ln.strip()
                for ln in raw.splitlines()
                if ln.strip()
                and "Warning" not in ln
                and not ln.startswith(" ")
                and "warnings.warn" not in ln
            ]
            stderr = " | ".join(lines[-3:])[:200]
        return f"{detail}{'; stderr: ' + stderr if stderr else '; stderr 无有效内容'}"

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()  # EOF 让 worker 的 for-loop 自然结束
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001 - 收尾绝不能反过来把调用方带崩。
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        finally:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None and not stream.closed:
                    stream.close()


def _kokoro_generate_audio(text: str, path: Path, *, voice: str = DEFAULT_KOKORO_VOICE, pipeline: Any = None) -> None:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on optional packages.
        raise RuntimeError("numpy is required for sentence audio") from exc

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
    _write_kokoro_audio(audio, path)


def generate_sentence_audio_for_rows(
    rows: list[dict[str, Any]],
    *,
    overwrite: bool = False,
    provider: str | None = None,
    voice: str | None = None,
    max_sentences: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """公开入口。真正的活在 _generate_rows 里，这层只保证 Kokoro 子进程一定被回收——
    它有两个 return（max_sentences 封顶、正常收尾）还可能抛异常，靠在出口处逐个补
    close() 迟早会漏掉一个，漏掉就是一个 700MB 的孤儿进程赖在机器上。"""
    worker = _KokoroWorker()
    try:
        return _generate_rows(
            rows,
            worker,
            overwrite=overwrite,
            provider=provider,
            voice=voice,
            max_sentences=max_sentences,
            dry_run=dry_run,
        )
    finally:
        worker.close()


def _generate_rows(
    rows: list[dict[str, Any]],
    kokoro_worker: _KokoroWorker,
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
                kokoro_worker.generate(
                    str(row.get("text") or ""),
                    path,
                    voice=selected_voice,
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
            # 同样走子进程。这条路由是从设置页点「试听」触发的，跑在 uvicorn 里；
            # 留着进程内合成的话，随手试听一次就把 torch 永久拉进后端，
            # 前面对生成路径做的隔离等于白做。
            worker = _KokoroWorker()
            try:
                worker.generate(
                    repository.SENTENCE_AUDIO_PREVIEW_TEXT,
                    path,
                    voice=clean_voice,
                )
            finally:
                worker.close()
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
    selected_voice = voice or os.getenv("STUDY_ENGLISH_WORD_AUDIO_VOICE", DEFAULT_EDGE_VOICE).strip() or DEFAULT_EDGE_VOICE
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
