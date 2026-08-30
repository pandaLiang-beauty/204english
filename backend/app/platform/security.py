from __future__ import annotations

import os
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

DEFAULT_FRONTEND_PORT = "5204"
WRITE_HEADER = "x-study-write"
WRITE_HEADER_VALUE = "1"
DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.1/32", "::1/128", "172.16.0.0/12")


def allowed_write_origins() -> set[str]:
    port = os.getenv("STUDY_FRONTEND_PORT", DEFAULT_FRONTEND_PORT)
    defaults = {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}
    configured = {
        origin.strip().rstrip("/")
        for origin in os.getenv("STUDY_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    }
    public_origin = os.getenv("STUDY_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if public_origin:
        configured.add(public_origin)
    return defaults | configured


def trusted_proxy_networks():
    raw = os.getenv("STUDY_TRUSTED_PROXY_CIDRS", ",".join(DEFAULT_TRUSTED_PROXY_CIDRS))
    return [ip_network(item.strip(), strict=False) for item in raw.split(",") if item.strip()]


def is_trusted_proxy(host: str) -> bool:
    if not host:
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in trusted_proxy_networks())


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for and is_trusted_proxy(peer):
        candidates = []
        for raw_candidate in forwarded_for.split(","):
            candidate = raw_candidate.strip()
            try:
                candidates.append(str(ip_address(candidate)))
            except ValueError:
                continue
        for candidate in reversed(candidates):
            if not is_trusted_proxy(candidate):
                return candidate
    return peer


def origin_from_referer(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def verify_write_origin(request: Request) -> None:
    if request.headers.get(WRITE_HEADER, "") != WRITE_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="Missing write protection header")
    origin = (request.headers.get("origin") or "").rstrip("/")
    referer_origin = origin_from_referer(request.headers.get("referer") or "")
    candidate = origin or referer_origin
    if not candidate:
        return
    if candidate not in allowed_write_origins():
        raise HTTPException(status_code=403, detail="Cross-site write blocked")
