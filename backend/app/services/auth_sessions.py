"""Signed persistent session cookies and CSRF token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import settings
from ..contracts import SessionPayload

SESSION_SALT = "daily-checkin-session-cookie-v1"
COOKIE_NAME = settings.cookie_name
_serializer = URLSafeTimedSerializer(
    settings.secret_key or "",
    salt=SESSION_SALT,
    signer_kwargs={"digest_method": hashlib.sha256},
)


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def csrf_token_for(session_id: str) -> str:
    return hmac.new(
        (settings.secret_key or "").encode("utf-8"),
        f"csrf:{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def new_payload(user_id: int, session_id: str) -> SessionPayload:
    now = datetime.now(timezone.utc)
    return {
        "uid": int(user_id),
        "sid": session_id,
        "iat": int(now.timestamp()),
        "jti": secrets.token_hex(8),
    }


def encode_cookie(payload: SessionPayload) -> str:
    return _serializer.dumps(payload)


def decode_cookie(value: str | None) -> SessionPayload | None:
    if not value:
        return None
    try:
        payload = _serializer.loads(
            value, max_age=settings.cookie_max_age_seconds
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        int(payload["uid"])
        str(payload["sid"])
        int(payload["iat"])
        str(payload["jti"])
    except (KeyError, TypeError, ValueError):
        return None
    return payload


def session_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + timedelta(
        seconds=settings.cookie_max_age_seconds
    )


def set_session_cookie(response: Response, payload: SessionPayload) -> None:
    now = datetime.now(timezone.utc)
    response.set_cookie(
        key=COOKIE_NAME,
        value=encode_cookie(payload),
        max_age=settings.cookie_max_age_seconds,
        expires=now + timedelta(seconds=settings.cookie_max_age_seconds),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
