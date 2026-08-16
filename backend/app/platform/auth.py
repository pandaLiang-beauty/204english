from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException, Response

from .db import get_connection


SESSION_COOKIE = os.getenv("STUDY_SESSION_COOKIE", "english_study_session")
SESSION_DAYS = 14
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = os.getenv("STUDY_INITIAL_PASSWORD")
COOKIE_SECURE = os.getenv("STUDY_COOKIE_INSECURE") != "1"
LOGIN_MAX_FAILURES = int(os.getenv("STUDY_LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("STUDY_LOGIN_WINDOW_SECONDS", "600"))
_login_failure_lock = threading.Lock()
_login_failures: dict[tuple[str, str], list[float]] = {}


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    actual = _hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(actual, expected)


def ensure_default_user() -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (DEFAULT_USERNAME,)).fetchone()
        if row:
            return
        if not DEFAULT_PASSWORD:
            raise RuntimeError("STUDY_INITIAL_PASSWORD is required when creating the default admin user")
        conn.execute(
            "INSERT INTO users(username, password_hash, display_name) VALUES (?, ?, ?)",
            (DEFAULT_USERNAME, _hash_password(DEFAULT_PASSWORD), "管理员"),
        )


def authenticate_user(username: str, password: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return None
    user = dict(row)
    if not _verify_password(password, user["password_hash"]):
        return None
    user.pop("password_hash", None)
    return user


def _login_key(username: str, client_ip: str) -> tuple[str, str]:
    return (username.strip().lower() or "<empty>", client_ip or "<unknown>")


def _recent_failures(key: tuple[str, str], now: float) -> list[float]:
    cutoff = now - LOGIN_WINDOW_SECONDS
    failures = [stamp for stamp in _login_failures.get(key, []) if stamp >= cutoff]
    if failures:
        _login_failures[key] = failures
    else:
        _login_failures.pop(key, None)
    return failures


def login_retry_after(username: str, client_ip: str) -> int | None:
    if LOGIN_MAX_FAILURES <= 0:
        return None
    key = _login_key(username, client_ip)
    now = time.monotonic()
    with _login_failure_lock:
        failures = _recent_failures(key, now)
        if len(failures) < LOGIN_MAX_FAILURES:
            return None
        return max(1, int(LOGIN_WINDOW_SECONDS - (now - failures[0])))


def record_login_failure(username: str, client_ip: str) -> None:
    if LOGIN_MAX_FAILURES <= 0:
        return
    key = _login_key(username, client_ip)
    now = time.monotonic()
    with _login_failure_lock:
        failures = _recent_failures(key, now)
        failures.append(now)
        _login_failures[key] = failures[-LOGIN_MAX_FAILURES:]


def clear_login_failures(username: str, client_ip: str) -> None:
    with _login_failure_lock:
        _login_failures.pop(_login_key(username, client_ip), None)


def create_session(response: Response, user_id: int) -> str:
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions(id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at.isoformat()),
        )
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )
    return session_id


def clear_session(response: Response, session_id: str | None = None) -> None:
    if session_id:
        with get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    response.delete_cookie(SESSION_COOKIE, path="/", secure=COOKIE_SECURE, samesite="lax")


def purge_expired_sessions() -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?",
            (datetime.now(timezone.utc).isoformat(),),
        )


def get_current_user(session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict:
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.display_name
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.id = ? AND s.expires_at > ?
            """,
            (session_id, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return dict(row)
