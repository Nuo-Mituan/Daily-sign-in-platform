"""Authentication endpoints using persistent signed Cookie sessions."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import AuthContext, get_auth_context, get_current_user
from ..models import AuthSession, User
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    SessionResponse,
    UserOut,
    UsernameUpdateRequest,
)
from ..security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from ..services.auth_guard import (
    lock_for_user,
    login_ip_limiter,
    login_user_limiter,
    sensitive_limiter,
)
from ..services.auth_sessions import (
    clear_session_cookie,
    invalidate_all_sessions,
    csrf_token_for,
    hash_session_id,
    new_payload,
    new_session_id,
    session_expiry,
    set_session_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

_USERNAME_RE = re.compile(r"^[^\s/\\]{3,64}$")


def _too_many_attempts() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="尝试次数过多，请稍后再试",
        headers={"Retry-After": "300"},
    )


def _check_attempt_limit(user_id: int) -> None:
    if sensitive_limiter.retry_after(user_id) > 0:
        raise _too_many_attempts()


def _ip_key(ip: str) -> int:
    return int.from_bytes(hashlib.sha256(ip.encode()).digest()[:4], "big")


async def _login_retry_after(user_id: int | None, ip: str | None) -> int:
    if user_id is not None:
        return await login_user_limiter.retry_after(user_id)
    if ip:
        return await login_ip_limiter.retry_after(_ip_key(ip))
    return 0


async def _login_record_failure(user_id: int | None, ip: str | None) -> None:
    if user_id is not None:
        await login_user_limiter.record_failure(user_id)
    elif ip:
        await login_ip_limiter.record_failure(_ip_key(ip))


async def _login_reset(user_id: int, ip: str | None) -> None:
    await login_user_limiter.reset(user_id)


def _login_too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="尝试次数过多，请稍后再试",
        headers={"Retry-After": str(max(1, retry_after))},
    )


def _verify_current_password(user_id: int, password: str, stored_hash: str) -> None:
    if not verify_password(password, stored_hash):
        sensitive_limiter.record_failure(user_id)
        raise HTTPException(status_code=400, detail="当前密码不正确")
    sensitive_limiter.reset(user_id)


def get_real_client_ip(request: Request) -> str | None:
    """Return the proxy-adjusted client IP, never raw untrusted XFF by default."""
    if request.client and request.client.host:
        return request.client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return None


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("user-agent")
    if user_agent:
        user_agent = user_agent[:255]
    ip_address = request.client.host if request.client else None
    if ip_address:
        ip_address = ip_address[:64]
    return user_agent, ip_address


@router.post("/login", response_model=LoginResponse, summary="账号密码登录")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    username = payload.username.strip()
    ip = get_real_client_ip(request)
    user = await db.scalar(select(User).where(User.username == username))
    user_id = user.id if user is not None else None
    retry_after = await _login_retry_after(user_id, ip)
    if retry_after > 0:
        raise _login_too_many(retry_after)
    if user is None:
        await _login_record_failure(None, ip)
        # Keep the failure path close to a real password verification to reduce
        # username-enumeration through response timing.
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not verify_password(payload.password, user.password_hash):
        await _login_record_failure(user.id, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    await _login_reset(user.id, ip)

    now = datetime.now(timezone.utc)
    await db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.expires_at <= now,
        )
    )
    session_id = new_session_id()
    expires_at = session_expiry(now)
    user_agent, ip_address = _request_meta(request)
    db.add(
        AuthSession(
            session_hash=hash_session_id(session_id),
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
            issued_at=now,
            last_renewed_at=now,
            expires_at=expires_at,
        )
    )
    await db.commit()
    set_session_cookie(response, new_payload(user.id, session_id))
    return LoginResponse(
        user=UserOut.model_validate(user),
        csrf_token=csrf_token_for(session_id),
        expires_at=expires_at,
        force_change_password=bool(user.password_must_change),
    )


@router.get("/session", response_model=SessionResponse, summary="校验并续期当前会话")
async def session(
    context: AuthContext = Depends(get_auth_context),
) -> SessionResponse:
    return SessionResponse(
        user=UserOut.model_validate(context.user),
        csrf_token=context.csrf_token,
        expires_at=context.session.expires_at,
        force_change_password=bool(context.user.password_must_change),
    )


@router.get("/me", response_model=UserOut, summary="当前登录用户")
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/logout", response_model=MessageResponse, summary="退出当前会话")
async def logout(
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await db.delete(context.session)
    await db.commit()
    clear_session_cookie(response)
    return MessageResponse(message="已退出登录")


@router.post("/logout-all", response_model=MessageResponse, summary="注销全部会话")
async def logout_all(
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await db.execute(
        delete(AuthSession).where(AuthSession.user_id == context.user.id)
    )
    await db.commit()
    clear_session_cookie(response)
    return MessageResponse(message="已注销全部登录会话")


@router.put("/username", response_model=UserOut, summary="修改用户名")
async def update_username(
    payload: UsernameUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    new_username = payload.new_username.strip()
    if not _USERNAME_RE.fullmatch(new_username):
        raise HTTPException(
            status_code=400,
            detail="用户名需为 3-64 个字符，且不能包含空格或斜杠",
        )

    user_id = current_user.id
    lock = lock_for_user(user_id)
    async with lock:
        _check_attempt_limit(user_id)
        # End the request's read transaction while waiting for the lock so this
        # request cannot verify a stale password hash after a concurrent change.
        await db.rollback()
        stored_user = await db.get(User, user_id)
        if stored_user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        _verify_current_password(
            stored_user.id, payload.current_password, stored_user.password_hash
        )

        if new_username == stored_user.username:
            # Idempotent: a retried request after a successful change succeeds.
            return UserOut.model_validate(stored_user)

        existing = await db.scalar(
            select(User).where(
                func.lower(User.username) == new_username.lower(),
                User.id != stored_user.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="用户名不可用")

        old_username = stored_user.username
        stored_user.username = new_username
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="用户名不可用") from None
        await db.refresh(stored_user)
        logger.info("管理员用户名已从 %s 修改为 %s", old_username, new_username)
        return UserOut.model_validate(stored_user)


@router.post("/change-password", response_model=MessageResponse, summary="修改密码")
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    user_id = current_user.id
    lock = lock_for_user(user_id)
    async with lock:
        _check_attempt_limit(user_id)
        # See the username endpoint: refresh after acquiring the lock to avoid
        # validating against a pre-lock, stale password hash.
        await db.rollback()
        stored_user = await db.get(User, user_id)
        if stored_user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        _verify_current_password(
            stored_user.id, payload.old_password, stored_user.password_hash
        )

        if payload.old_password == payload.new_password:
            raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
        if payload.new_password.strip() != payload.new_password:
            raise HTTPException(status_code=400, detail="新密码首尾不能包含空格")
        if len(payload.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")

        stored_user.password_hash = hash_password(payload.new_password)
        stored_user.password_must_change = False
        await invalidate_all_sessions(db, stored_user.id)
        await db.commit()
        clear_session_cookie(response)
        logger.info("管理员密码已更新，全部会话已失效")
        return MessageResponse(message="密码修改成功，请使用新密码重新登录")
