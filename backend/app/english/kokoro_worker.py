"""Kokoro 合成的独立子进程。

存在的理由是内存，不是架构洁癖：torch 一旦 import 进 uvicorn 进程就再也不出去。
实测把 Kokoro 生成放在 API 进程里跑一次，后端常驻 RSS 从 78MB 涨到 700MB 并且
不再回落——其中 671MB 是匿名内存，OOM 时不可回收，glibc 也不会把释放的 arena
还给系统。这台机器 3.9G 内存、swap=0，白占 620MB 是要命的。

放进子进程后，父进程全程不 import torch；子进程一退出，内核把整块地址空间收回，
常驻增量归零。代价是每批多一次模型加载（约 3 秒），所以按批复用同一个子进程，
而不是每句起一个。

协议：stdin 每行一个 JSON 作业 {"text","path","voice"}，stdout 每行一个 JSON 结果
{"ok":true} 或 {"ok":false,"error":"..."}。一行一句，顺序对应。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .audio_generation import (
    DEFAULT_KOKORO_SAMPLE_RATE,
    _kokoro_language_code,
    _kokoro_model,
    _kokoro_pipeline,
    _kokoro_voice_source,
    _make_audio_readable,
    _plain_text,
)


def _synthesize(pipeline: Any, text: str, path: Path, voice: str) -> None:
    import numpy as np
    import soundfile as sf

    cleaned = _plain_text(text)
    if not cleaned:
        raise ValueError("empty TTS text")
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [audio for _, _, audio in pipeline(cleaned, voice=_kokoro_voice_source(voice))]
    if not chunks:
        raise RuntimeError("kokoro produced no audio")
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    # 先写同目录临时文件再 replace：父进程读到的文件要么不存在，要么是完整的。
    # 后缀必须保留 .wav——soundfile 从扩展名推格式，命名成 .part 会直接 TypeError。
    tmp_path = path.with_name(f".{path.stem}.part{path.suffix or '.wav'}")
    try:
        sf.write(tmp_path, audio, DEFAULT_KOKORO_SAMPLE_RATE, format="WAV")
        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise RuntimeError("kokoro wrote an empty audio file")
        tmp_path.replace(path)
        _make_audio_readable(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    model = None
    pipelines: dict[str, Any] = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            voice = str(job.get("voice") or "")
            lang_code = _kokoro_language_code(voice)
            if lang_code not in pipelines:
                # 模型只在第一句真正到来时才建，空批次不付加载成本。
                if model is None:
                    model = _kokoro_model()
                pipelines[lang_code] = _kokoro_pipeline(lang_code=lang_code, model=model)
            _synthesize(pipelines[lang_code], str(job.get("text") or ""), Path(str(job["path"])), voice)
            result = {"ok": True}
        except BaseException as exc:  # noqa: BLE001 - 每句独立记账，一句失败不该带走整批。
            # 抓 BaseException 而不是 Exception：MemoryError 和 KeyboardInterrupt 都不是
            # Exception 的子类，而内存不足恰恰是这里最可能出的事。让它静默退出的话，
            # 父进程只能看到一个"没有回复"，查不出任何原因。
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:240]}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
