from __future__ import annotations

import os
import runpy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import HTTPException


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.platform import db as platform_db  # noqa: E402
from app.platform import ai_transport  # noqa: E402
from app.platform.auth import (  # noqa: E402
    COOKIE_SECURE,
    LOGIN_MAX_FAILURES,
    clear_login_failures,
    login_retry_after,
    record_login_failure,
)
from app.platform.db import get_connection, initialize_database  # noqa: E402
from app.platform.security import DEFAULT_FRONTEND_PORT, client_ip, verify_write_origin  # noqa: E402


class FakeRequest:
    def __init__(self, headers: dict[str, str], host: str = "127.0.0.1"):
        self.headers = headers
        self.client = SimpleNamespace(host=host)


def check_write_origin_guard() -> None:
    write_header = {"x-study-write": "1"}
    allowed_origin = (
        os.getenv("STUDY_PUBLIC_ORIGIN", "").strip().rstrip("/")
        or f"http://127.0.0.1:{DEFAULT_FRONTEND_PORT}"
    )
    verify_write_origin(FakeRequest(write_header))
    verify_write_origin(FakeRequest({**write_header, "origin": allowed_origin}))
    verify_write_origin(FakeRequest({**write_header, "referer": f"{allowed_origin}/english"}))
    for headers in ({}, {**write_header, "origin": "https://evil.example"}):
        try:
            verify_write_origin(FakeRequest(headers))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError(f"unsafe write request was accepted: {headers}")


def check_client_ip_trust() -> None:
    spoofed = FakeRequest({"x-forwarded-for": "198.51.100.1"}, host="203.0.113.9")
    assert client_ip(spoofed) == "203.0.113.9"
    proxied = FakeRequest({"x-forwarded-for": "198.51.100.1, 172.18.0.4"}, host="172.18.0.4")
    assert client_ip(proxied) == "198.51.100.1"
    prepended_spoof = FakeRequest(
        {"x-forwarded-for": "198.51.100.99, 198.51.100.1, 172.18.0.4"},
        host="127.0.0.1",
    )
    assert client_ip(prepended_spoof) == "198.51.100.1"


def check_frontend_proxy_sanitizes_forwarded_headers() -> None:
    proxy_module = runpy.run_path(str(BACKEND_ROOT.parent / "scripts" / "local_frontend_proxy.py"))
    build_proxy_headers = proxy_module["build_proxy_headers"]
    headers = build_proxy_headers(
        {
            "Host": "study.example",
            "X-Forwarded-For": "198.51.100.99",
            "x-real-ip": "198.51.100.98",
            "X-Forwarded-Proto": "https",
            "X-Study-Write": "1",
        },
        "203.0.113.10",
    )
    assert headers["X-Forwarded-For"] == "203.0.113.10", headers
    assert headers["X-Real-IP"] == "203.0.113.10", headers
    assert headers["X-Forwarded-Proto"] == "http", headers
    assert headers["X-Study-Write"] == "1", headers
    assert not any(key.lower() == "x-forwarded-for" and key != "X-Forwarded-For" for key in headers), headers


def check_malformed_ai_response_is_controlled() -> None:
    original_urlopen = ai_transport.urlopen

    class FakeResponse:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return self.body

    try:
        for body in (b"not-json", b"[]", b'{"choices":["invalid"]}'):
            ai_transport.urlopen = lambda *_args, _body=body, **_kwargs: FakeResponse(_body)
            try:
                ai_transport._chat_completion(
                    [{"role": "user", "content": "test"}],
                    model="test-model",
                    base_url="https://ai.example/v1",
                    api_key="test-key",
                    timeout_seconds=1,
                )
            except ai_transport.AIProviderError as exc:
                assert exc.user_message, exc
            else:
                raise AssertionError(f"malformed AI response escaped validation: {body!r}")
    finally:
        ai_transport.urlopen = original_urlopen


def check_login_rate_limit() -> None:
    assert LOGIN_MAX_FAILURES > 0, "login throttling must be enabled"
    username = "__reliability_check__"
    ip = "203.0.113.10"
    clear_login_failures(username, ip)
    for _ in range(LOGIN_MAX_FAILURES):
        record_login_failure(username, ip)
    assert login_retry_after(username, ip) is not None
    clear_login_failures(username, ip)
    assert login_retry_after(username, ip) is None


def check_public_cookie_security() -> None:
    public_origin = os.getenv("STUDY_PUBLIC_ORIGIN", "").strip()
    if not public_origin:
        return
    parsed = urlsplit(public_origin)
    is_local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not is_local:
        assert parsed.scheme == "https", public_origin
        assert COOKIE_SECURE is True


def check_minimal_sqlite_schema() -> None:
    original_path = platform_db.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            platform_db.DB_PATH = Path(temp_dir) / "study.db"
            initialize_database()
            with get_connection() as conn:
                tables = {
                    str(row["name"])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            assert tables == {"users", "sessions", "sqlite_sequence"}, tables
    finally:
        platform_db.DB_PATH = original_path


def check_openapi_schema() -> None:
    from app.main import app

    paths = app.openapi().get("paths") or {}
    assert "/api/health" in paths, paths
    assert "/api/english/stats" in paths, paths
    assert "/api/study-stats" not in paths, paths
    assert "/api/study-activity" not in paths, paths
    assert "/api/ai/status" not in paths, paths


CHECKS = (
    check_write_origin_guard,
    check_client_ip_trust,
    check_frontend_proxy_sanitizes_forwarded_headers,
    check_malformed_ai_response_is_controlled,
    check_login_rate_limit,
    check_public_cookie_security,
    check_minimal_sqlite_schema,
    check_openapi_schema,
)


def run_checks() -> None:
    initialize_database()
    for check in CHECKS:
        check()
        print(f"OK platform.{check.__name__}")


def main() -> int:
    run_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
