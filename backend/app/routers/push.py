"""Global push notification settings."""

from __future__ import annotations

import asyncio
import logging
import math

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import AuthContext, get_auth_context, get_current_user
from ..schemas import (
    PushConfigOut,
    PushConfigUpdate,
    PushUnifiedSettingsOut,
    PushUnifiedSettingsUpdate,
    PushRevealResponse,
    PushTestResponse,
    RevealSensitiveRequest,
    DriverRollbackRequest,
    PushBatchOut,
    PushBatchPage,
    PushRecordOut,
    PushRecordPage,
)
from ..models import User
from ..security import verify_password
from ..services.auth_guard import lock_for_user, sensitive_limiter
from ..push_drivers.base import DriverError
from ..push_drivers.registry import driver_registry
from ..services.push_pool import list_batches, list_records
from ..services.auth_sessions import invalidate_all_sessions
from ..services.push import (
    PushConfigError,
    load_push_config,
    public_push_config,
    save_push_config,
    load_unified_settings,
    save_unified_settings,
    send_test_notification,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/push",
    tags=["推送通知"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/config", response_model=PushConfigOut, summary="读取全局推送配置")
async def get_push_config(db: AsyncSession = Depends(get_db)) -> PushConfigOut:
    try:
        data = await load_push_config(db)
    except PushConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PushConfigOut(**public_push_config(data))  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing


@router.get(
    "/unified-settings",
    response_model=PushUnifiedSettingsOut,
    summary="读取统一推送兜底设置",
)
async def get_unified_settings(db: AsyncSession = Depends(get_db)) -> PushUnifiedSettingsOut:
    data = await load_unified_settings(db)
    return PushUnifiedSettingsOut(**data)


@router.put(
    "/unified-settings",
    response_model=PushUnifiedSettingsOut,
    summary="保存统一推送兜底设置",
)
async def update_unified_settings(
    payload: PushUnifiedSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> PushUnifiedSettingsOut:
    data = await save_unified_settings(
        db,
        timeout_enabled=payload.timeout_enabled,
        timeout_time=payload.timeout_time,
    )
    return PushUnifiedSettingsOut(**data)


@router.put("/config", response_model=PushConfigOut, summary="保存全局推送配置")
async def update_push_config(
    payload: PushConfigUpdate,
    current_user=Depends(get_current_user),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> PushConfigOut:
    try:
        data = await save_push_config(
            db,
            payload.channel,
            payload.config,
            payload.title_template,
            payload.body_template,
        )
    except PushConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await invalidate_all_sessions(db, current_user.id, exclude_session_id=context.session.id)
    await db.commit()
    return PushConfigOut(**public_push_config(data))


@router.post(
    "/reveal",
    response_model=PushRevealResponse,
    summary="二次密码校验后显示推送凭据明文",
)
async def reveal_push_config(
    payload: RevealSensitiveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushRevealResponse:
    user_id = current_user.id
    lock = lock_for_user(user_id)
    async with lock:
        wait = sensitive_limiter.retry_after(user_id)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail="尝试次数过多，请稍后再试",
                headers={"Retry-After": str(wait)},
            )
        await db.rollback()
        stored_user = await db.get(User, user_id)
        if stored_user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if not verify_password(payload.current_password, stored_user.password_hash):
            sensitive_limiter.record_failure(user_id)
            raise HTTPException(status_code=400, detail="当前密码不正确")
        sensitive_limiter.reset(user_id)
        try:
            data = await load_push_config(db)
        except PushConfigError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PushRevealResponse(config=data.get("config", {}))


@router.post("/test", response_model=PushTestResponse, summary="发送推送测试消息")
async def test_push() -> PushTestResponse:
    try:
        result = await send_test_notification()
    except PushConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("推送测试失败")
        raise HTTPException(
            status_code=500, detail=f"推送测试失败：{type(exc).__name__}"
        ) from exc
    sent = bool(result.get("sent"))
    message = "测试消息已发送，请检查接收端" if sent else (
        result.get("error") or result.get("reason") or "测试消息发送失败"
    )
    return PushTestResponse(
        success=sent,
        sent=sent,
        channel=str(result.get("channel") or ""),
        message=message,
        response=result.get("response"),
    )


@router.get("/drivers", summary="推送驱动列表")
async def list_push_drivers() -> list[dict]:
    return driver_registry.list_drivers()


@router.post("/drivers/upload", summary="上传并热加载自定义推送驱动")
async def upload_push_driver(
    file: UploadFile = File(...),
    key: str | None = Form(default=None),
    name: str | None = Form(default=None),
    version: str | None = Form(default=None),
) -> dict:
    data = await file.read()
    try:
        record = await asyncio.to_thread(
            driver_registry.install,
            data,
            filename=file.filename or "driver.py",
            key=key,
            name=name,
            version=version,
        )
    except DriverError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "驱动已校验并热加载", "driver": record.public()}


@router.post("/drivers/{key}/rollback", summary="回滚自定义驱动")
async def rollback_push_driver(
    key: str, payload: DriverRollbackRequest
) -> dict:
    try:
        record = await asyncio.to_thread(
            driver_registry.rollback, key, payload.version
        )
    except DriverError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": f"驱动已回滚到 {record.version}", "driver": record.public()}


@router.delete("/drivers/{key}", summary="删除自定义推送驱动")
async def delete_push_driver(
    key: str, db: AsyncSession = Depends(get_db)
) -> dict:
    if any(item["key"] == key and item["builtin"] for item in driver_registry.list_drivers()):
        raise HTTPException(status_code=400, detail="内置驱动不可删除")
    if not any(item["key"] == key for item in driver_registry.list_drivers()):
        raise HTTPException(status_code=404, detail="驱动不存在")
    try:
        config = await load_push_config(db)
    except PushConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if config.get("channel") == key:
        raise HTTPException(
            status_code=409,
            detail="该驱动仍是当前全局推送渠道，请先切换渠道再删除",
        )
    await asyncio.to_thread(driver_registry.delete, key)
    return {"message": "驱动已卸载并删除"}


@router.get("/records", response_model=PushRecordPage, summary="推送历史记录")
async def push_records(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PushRecordPage:
    rows, total = await list_records(
        page=page, page_size=page_size, kind=kind, status=status
    )
    return PushRecordPage(
        items=[PushRecordOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)) if total else 0,
    )


@router.get("/batches", response_model=PushBatchPage, summary="统一推送批次摘要")
async def push_batches(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PushBatchPage:
    rows, total = await list_batches(
        page=page, page_size=page_size, status=status
    )
    return PushBatchPage(
        items=[PushBatchOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)) if total else 0,
    )
