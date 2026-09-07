from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from ..platform.ai_transport import AIProviderError


logger = logging.getLogger(__name__)


class RequestGate:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_request_at = 0.0

    def wait(self, interval: float) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                delay = self.next_request_at - now
                if delay <= 0:
                    self.next_request_at = now + interval
                    return
            time.sleep(delay)

    def defer(self, seconds: float) -> None:
        with self.lock:
            self.next_request_at = max(self.next_request_at, time.monotonic() + seconds)


_gates: dict[tuple[str, str], RequestGate] = {}
_gates_lock = threading.Lock()


def _request_policy() -> tuple[float, int]:
    try:
        rate = float(os.getenv("STUDY_ENGLISH_AI_REQUESTS_PER_MINUTE", "").strip() or "0")
        retries = int(os.getenv("STUDY_ENGLISH_AI_MAX_RETRIES", "").strip() or "2")
    except ValueError as exc:
        raise AIProviderError("英语翻译请求频率或重试次数配置无效") from exc
    if not math.isfinite(rate) or rate < 0 or not 0 <= retries <= 3:
        raise AIProviderError("英语翻译请求频率必须非负，重试次数须在 0 到 3 之间")
    return (60.0 / rate if rate else 0.0), retries


def _retry_details(error: AIProviderError, attempt: int) -> tuple[bool, float, int | None]:
    cause = error.__cause__
    status_match = re.search(r"\bHTTP (\d{3})\b", error.diagnostic)
    status = cause.code if isinstance(cause, HTTPError) else int(status_match[1]) if status_match else None
    if status is None:
        return isinstance(cause, (TimeoutError, URLError)), float(2 ** attempt), None
    if status not in {429, 500, 502, 503, 504}:
        return False, 0.0, status
    delays = [60.0 if status == 429 else float(2 ** attempt)]
    if isinstance(cause, HTTPError) and cause.headers:
        retry_after = cause.headers.get("Retry-After", "")
        try:
            delays.append(float(retry_after))
        except (TypeError, ValueError):
            pass
    try:
        payload = json.loads(error.diagnostic.partition(": ")[2])
        metadata = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(metadata, dict):
            delays.append(float(metadata.get("retryAfterSeconds", 0)))
    except (TypeError, ValueError):
        pass
    delay = max(value for value in delays if math.isfinite(value) and value >= 0)
    return delay <= 180, delay + 0.25, status


def translation_completion(
    messages: list[dict[str, Any]],
    *,
    options: dict[str, Any],
    completion: Callable[..., str],
) -> str:
    interval, retries = _request_policy()
    identity = (str(options.get("base_url") or ""), str(options.get("api_key") or ""))
    with _gates_lock:
        gate = _gates.setdefault(identity, RequestGate())
    for attempt in range(retries + 1):
        gate.wait(interval)
        try:
            return completion(messages, **options)
        except AIProviderError as exc:
            retryable, delay, status = _retry_details(exc, attempt)
            if retryable and attempt < retries:
                logger.warning("English AI retry %s/%s after %.2fs (HTTP %s)", attempt + 1, retries, delay, status)
                gate.defer(delay)
                continue
            diagnostic = exc.diagnostic
            if identity[1]:
                diagnostic = diagnostic.replace(identity[1], "[REDACTED]")
            message = "翻译服务请求过于频繁，请稍后重试。" if status == 429 else exc.user_message
            raise AIProviderError(message, diagnostic) from exc
    raise AssertionError("translation request exhausted without a result")
