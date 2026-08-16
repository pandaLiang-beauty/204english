from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .auth import (
    SESSION_COOKIE,
    DEFAULT_USERNAME,
    authenticate_user,
    clear_login_failures,
    clear_session,
    create_session,
    get_current_user,
    login_retry_after,
    record_login_failure,
)
from .security import client_ip, verify_write_origin


router = APIRouter(tags=["platform"])


class LoginRequest(BaseModel):
    password: str


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/api/auth/login")
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    csrf: None = Depends(verify_write_origin),
) -> dict:
    ip = client_ip(request)
    retry_after = login_retry_after(DEFAULT_USERNAME, ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )
    user = authenticate_user(DEFAULT_USERNAME, payload.password)
    if not user:
        record_login_failure(DEFAULT_USERNAME, ip)
        raise HTTPException(status_code=401, detail="密码错误")
    clear_login_failures(DEFAULT_USERNAME, ip)
    create_session(response, int(user["id"]))
    return {"user": user}


@router.post("/api/auth/logout")
def logout(
    response: Response,
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    csrf: None = Depends(verify_write_origin),
) -> dict:
    clear_session(response, session_id)
    return {"ok": True}


@router.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"user": user}
