"""Reusable FastAPI dependencies: cookie sessions and CSRF validation."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .models import AuthSession, User
from .services.auth_sessions import (
    COOKIE_NAME,
    csrf_token_for,
    decode_cookie,
    hash_session_id,
    new_payload,
    session_expiry,
    set_session_cookie,
)

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
session_scheme = APIKeyCookie(name=COOKIE_NAME, auto_error=False)


@dataclass
class AuthContext:
    user: User
    session: AuthSession
    csrf_token: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态已失效，请重新登录",
    )


async def get_auth_context(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _cookie: str | None = Depends(session_scheme),
) -> AuthContext:
    payload = decode_cookie(request.cookies.get(COOKIE_NAME))
    if payload is None:
        raise _unauthorized()

    session_id = str(payload["sid"])
    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.session_hash == hash_session_id(session_id),
            AuthSession.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    if session is None or session.expires_at <= now:
        raise _unauthorized()

    user = await db.get(User, session.user_id)
    if user is None:
        raise _unauthorized()

    csrf = csrf_token_for(session_id)
    if settings.csrf_enabled and request.method not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not hmac.compare_digest(supplied, csrf):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF 校验失败，请刷新页面后重试",
            )

    # Sliding renewal: refresh both the DB whitelist and the signed cookie at
    # most once per configured interval (default five minutes).  Endpoints that
    # delete the session/cookie must not emit a renewal header first.
    no_renew_paths = (
        "/auth/logout",
        "/auth/logout-all",
        "/auth/change-password",
    )
    if request.url.path.endswith(no_renew_paths):
        return AuthContext(user=user, session=session, csrf_token=csrf)
    elapsed = (now - session.last_renewed_at).total_seconds()
    if elapsed >= settings.session_renew_interval_seconds:
        session.last_renewed_at = now
        session.expires_at = session_expiry(now)
        await db.commit()
        set_session_cookie(response, new_payload(user.id, session_id))

    return AuthContext(user=user, session=session, csrf_token=csrf)


async def get_current_user(
    context: AuthContext = Depends(get_auth_context),
) -> User:
    return context.user
