"""Module management API: CRUD, hot-plug, accounts, random schedule and runs."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
# Minimum supported runtime: Python 3.11 (see pyproject requires-python).
import shutil
import time
import uuid
from collections import OrderedDict
from threading import Event, Lock
from weakref import WeakSet
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import EncryptionContext, ParameterDecryptionError, parameter_cipher
from ..database import SessionLocal, get_db
from ..deps import AuthContext, get_auth_context, get_current_user
from ..models import ExecutionLog, Module, ModuleSchedule, PushPool, User
from ..services.module_icon import (
    ModuleIconError,
    load_icon,
)
from ..module_loader import (
    SyncResult,
    get_module_physical_path,
    ModuleConfig,
    ModuleConfigError,
    normalize_accounts,
    parse_config_file,
    sync_modules,
    validate_and_normalize_params,
    validate_module_key,
)
from ..scheduling import (
    ScheduleError,
    next_occurrence,
    repeat_sub_label,
    validate_schedule,
)
from ..schemas import (
    DatabaseUnavailableResponse,
    AccountOut,
    MessageResponse,
    ModuleDetail,
    ModuleOut,
    ModuleUpdateRequest,
    RegenerateScheduleResponse,
    RevealSensitiveRequest,
    RevealSensitiveResponse,
    RunResponse,
    ScanError,
    ScanResponse,
    ScheduleOut,
    SchedulePreviewRequest,
    SchedulePreviewResponse,
    ToggleRequest,
    UploadResponse,
)
from ..security import verify_password
from ..services import execution
from ..services.auth_guard import lock_for_user, sensitive_limiter
from ..services.ownership import owner_user_id
from ..services.module_update import (
    ModuleUpdateError,
    ModuleUpdateHooks,
    plan_module_update,
)
from ..services.module_query_service import (
    _mask_accounts,
    _mask_params,
    _merge_sensitive_accounts,
    _merge_sensitive_params,
    _safe_account_count,
    _sensitive_only,
)
from ..services.module_upload import (
    ModuleUploadError,
    install_module_upload,
)
from ..services.schedules import (
    cancel_pending_for_module,
    current_schedule,
    regenerate_current_schedule,
    schedule_to_dict,
)
from ..services.auth_sessions import invalidate_all_sessions
from ..services.scheduler import scheduler_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/modules",
    tags=["签到模块"],
    dependencies=[Depends(get_current_user)],
)

# Public icon router: browsers load <img> without JS/CSRF and icons are
# non-sensitive, cacheable static resources. Path/traversal checks still apply.
# 此路由故意豁免认证，因为它是 <img> 标签直接加载的静态资源。
# Do NOT merge this route back into the authenticated router.
public_router = APIRouter(prefix="/modules", tags=["签到模块"])


# --------------------------------------------------------------- serializers
def _schedule_fields(module: Module) -> tuple[str, str, str, str]:
    start = module.start_time or module.default_start_time or "08:00"
    end = module.end_time or module.default_end_time or "10:00"
    cycle = module.repeat_cycle or module.default_repeat_cycle or "daily"
    sub = module.repeat_sub_value
    if cycle in {"weekly", "monthly", "yearly"} and not sub:
        sub = module.default_repeat_sub_value or ""
    if cycle in {"daily", "monthly_15"}:
        sub = ""
    return start, end, cycle, sub or ""


def _migration_status(module: Module) -> str:
    physical = module.directory_name or module.key
    if not module.directory_name:
        return "needs_legacy_key"
    if physical != module.key or not (settings.modules_dir / physical).is_dir():
        return "directory_mismatch"
    return "ok"


def _module_out(
    module: Module,
    schedule: ModuleSchedule | None,
    encryption_context: EncryptionContext,
) -> ModuleOut:
    start, end, cycle, sub_value = _schedule_fields(module)
    account_count = _safe_account_count(module, encryption_context)
    has_params = account_count > 0 if module.multi_account else bool(module.params_encrypted)
    return ModuleOut(
        id=module.id,
        key=module.key,
        directory_name=module.directory_name,
        legacy_key=module.legacy_key,
        physical_directory=(module.directory_name or module.key),
        migration_status=_migration_status(module),
        name=module.name,
        description=module.description,
        author=module.author,
        version=module.version,
        icon=module.icon,
        icon_source=module.icon_source or "url",
        icon_data=module.icon_data,
        start_time=start,
        end_time=end,
        repeat_cycle=cycle,
        repeat_sub_value=sub_value,
        default_start_time=module.default_start_time or "08:00",
        default_end_time=module.default_end_time or "10:00",
        default_repeat_cycle=module.default_repeat_cycle or "daily",
        default_repeat_sub_value=module.default_repeat_sub_value or "",
        enabled=module.enabled,
        push_enabled=bool(module.push_enabled),
        push_independent=bool(module.push_independent),
        push_unified=bool(module.push_unified),
        multi_account=bool(module.multi_account),
        load_error=module.load_error,
        last_run_at=module.last_run_at,
        last_status=module.last_status,
        last_message=module.last_message,
        current_schedule_at=schedule.scheduled_at if schedule else None,
        schedule_period_start=schedule.period_start if schedule else None,
        schedule_status=schedule.status if schedule else "none",
        schedule_source=schedule.source if schedule else None,
        schedule_fallback_used=bool(schedule.fallback_used) if schedule else False,
        schedule_note=schedule.note if schedule else None,
        has_params=has_params,
        param_count=len(module.param_schema or []),
        account_count=account_count,
        created_at=module.created_at,
        updated_at=module.updated_at,
    )


def _stored_accounts(
    module: Module, encryption_context: EncryptionContext
) -> list[dict[str, object]]:
    """Expose multi-account data, with a legacy single-account fallback."""
    if not module.multi_account:
        return []
    if module.accounts_encrypted:
        accounts, _ = parameter_cipher.decrypt_accounts(
            module.accounts_encrypted,
            EncryptionContext(
                user_id=encryption_context.user_id,
                module_key=module.key,
                account_index=-1,
            ),
        )
        return accounts
    if module.params_encrypted:
        params = parameter_cipher.decrypt(
            module.params_encrypted, encryption_context
        )
        return [
            {
                "id": f"legacy-{module.id}",
                "label": "",
                "params": params,
            }
        ]
    return []


async def _get_schedule(db: AsyncSession, module: Module) -> ModuleSchedule | None:
    try:
        return await current_schedule(db, module)
    except Exception:
        logger.exception("读取模块 %s 的随机执行时间失败", module.key)
        return None


async def _module_detail(
    db: AsyncSession, module: Module, encryption_context: EncryptionContext
) -> ModuleDetail:
    schedule = await _get_schedule(db, module)
    base = _module_out(module, schedule, encryption_context)
    schema = list(module.param_schema or [])
    try:
        params = parameter_cipher.decrypt(
            module.params_encrypted, encryption_context
        )
        accounts = _stored_accounts(module, encryption_context)
    except ParameterDecryptionError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{exc} 可在配置页重新填写并保存参数。",
        ) from exc

    upgraded = False
    if module.params_encrypted and not parameter_cipher.is_v2(module.params_encrypted):
        module.params_encrypted = parameter_cipher.encrypt(
            params, encryption_context
        )
        upgraded = True
    if module.accounts_encrypted:
        try:
            upgraded_accounts, accounts_upgraded = parameter_cipher.decrypt_accounts(
                module.accounts_encrypted, encryption_context
            )
            if accounts_upgraded:
                module.accounts_encrypted = parameter_cipher.encrypt_accounts(
                    upgraded_accounts, encryption_context
                )
                upgraded = True
        except ParameterDecryptionError:
            logger.warning(
                "模块 %s 的账号密文升级失败，保留原密文以便后续修复",
                module.key,
                exc_info=True,
            )
    if upgraded:
        await db.commit()

    return ModuleDetail(
        **base.model_dump(),
        param_schema=schema,
        params={} if module.multi_account else _mask_params(params, schema),
        accounts=[
            AccountOut(**account)
            for account in _mask_accounts(accounts, schema)
        ],
    )


async def _get_module_or_404(db: AsyncSession, module_id: int) -> Module:
    module = await db.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="模块不存在")
    return module


def _live_config(module: Module) -> ModuleConfig:
    try:
        return parse_config_file(get_module_physical_path(module) / "config.json")
    except ModuleConfigError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"模块配置文件不可用：{exc}。请修复后点击“扫描目录”。",
        ) from exc


def _stored_params(
    module: Module, encryption_context: EncryptionContext
) -> dict[str, object]:
    try:
        return parameter_cipher.decrypt(
            module.params_encrypted, encryption_context
        )
    except ParameterDecryptionError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} 在配置页重新填写参数后保存即可恢复。",
        ) from exc


def _validated_stored_params(
    module: Module,
    config: ModuleConfig,
    encryption_context: EncryptionContext,
) -> dict[str, object]:
    try:
        return validate_and_normalize_params(
            config, _stored_params(module, encryption_context)
        )
    except ModuleConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validated_accounts(
    module: Module,
    config: ModuleConfig,
    encryption_context: EncryptionContext,
    accounts: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    raw = (
        _stored_accounts(module, encryption_context)
        if accounts is None
        else accounts
    )
    try:
        return normalize_accounts(config, raw)
    except ModuleConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _load_modules(db: AsyncSession) -> list[Module]:
    return list((await db.execute(select(Module))).scalars().all())


# ---------------------------------------------------------------------- API
@router.get("", response_model=list[ModuleOut], summary="模块列表")
async def list_modules(db: AsyncSession = Depends(get_db)) -> list[ModuleOut]:
    modules = list(
        (
            await db.execute(
                select(Module).order_by(Module.enabled.desc(), Module.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    result: list[ModuleOut] = []
    owner_id = await owner_user_id(db)
    for module in modules:
        context = EncryptionContext(
            user_id=owner_id, module_key=module.key, account_index=-1
        )
        result.append(_module_out(module, await _get_schedule(db, module), context))
    return result


@router.post(
    "/scan",
    response_model=ScanResponse,
    summary="扫描模块目录并热加载",
    responses={503: {"model": DatabaseUnavailableResponse}},
)
async def scan_modules(db: AsyncSession = Depends(get_db)) -> ScanResponse:
    result = await sync_modules(db)
    if result.session_rebuilt:
        await db.close()
        return await _scan_with_fresh_session(result)

    all_modules = await _load_modules(db)
    await scheduler_service.reconcile(all_modules)
    return _scan_response(result, all_modules)


async def _scan_with_fresh_session(result: SyncResult) -> ScanResponse:
    async with SessionLocal() as fresh_db:
        all_modules = await _load_modules(fresh_db)
        await scheduler_service.reconcile(all_modules)
        return _scan_response(result, all_modules)


def _scan_response(result: SyncResult, all_modules: list[Module]) -> ScanResponse:
    message = (
        f"扫描完成：新增 {result.added} 个，更新 {result.updated} 个，"
        f"异常 {len(result.invalid)} 个"
    )
    return ScanResponse(
        added=result.added,
        updated=result.updated,
        total=len(all_modules),
        invalid=[ScanError(key=key, error=error) for key, error in result.invalid],
        message=message,
    )


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="上传 ZIP 模块并热安装",
    responses={503: {"model": DatabaseUnavailableResponse}},
)
async def upload_module(
    file: UploadFile = File(..., description="ZIP 压缩包"),
    name: str | None = Form(default=None, description="可选：模块标识（目录名）"),
    overwrite: bool = Query(default=False, description="覆盖同名模块"),
    current_user: User = Depends(get_current_user),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    directory_name: str | None = None
    if name:
        try:
            requested_key = validate_module_key(name.strip())
        except ModuleConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = await db.scalar(select(Module).where(Module.key == requested_key))
        directory_name = existing.directory_name if existing else None
        if directory_name:
            conflict = await db.scalar(
                select(Module).where(
                    Module.directory_name == directory_name,
                    Module.key != requested_key,
                )
            )
            if conflict is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"物理目录 {directory_name} 已被模块 {conflict.key} 占用，"
                        "禁止多个模块共享同一目录"
                    ),
                )
    try:
        key, _config = await install_module_upload(
            file, name, overwrite, directory_name
        )
    except (ModuleUploadError, ModuleConfigError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("安装上传模块失败")
        raise HTTPException(status_code=500, detail=f"安装模块失败：{exc}") from exc
    finally:
        await file.close()

    sync_result = await sync_modules(db)
    if sync_result.session_rebuilt:
        await db.close()
        return await _upload_with_fresh_session(
            key, sync_result, current_user, context
        )
    return await _finish_upload(db, key, sync_result, current_user, context)


async def _upload_with_fresh_session(
    key: str,
    sync_result: SyncResult,
    current_user: User,
    context: AuthContext,
) -> UploadResponse:
    async with SessionLocal() as fresh_db:
        return await _finish_upload(
            fresh_db, key, sync_result, current_user, context
        )


async def _finish_upload(
    db: AsyncSession,
    key: str,
    sync_result: SyncResult,
    current_user: User,
    context: AuthContext,
) -> UploadResponse:
    module = await db.scalar(select(Module).where(Module.key == key))
    if module is None:
        errors = "；".join(
            error for error_key, error in sync_result.invalid if error_key == key
        )
        raise HTTPException(
            status_code=400,
            detail=f"模块已解压，但同步失败：{errors or '未知错误'}",
        )
    all_modules = await _load_modules(db)
    await scheduler_service.reconcile(all_modules)
    await invalidate_all_sessions(db, current_user.id, exclude_session_id=context.session.id)
    await db.commit()
    encryption_context = EncryptionContext(
        user_id=await owner_user_id(db), module_key=module.key, account_index=-1
    )
    return UploadResponse(
        message=(
            f"模块「{module.name}」安装成功，已加入模块列表"
            "（默认禁用，请配置账号与随机时间后启用）"
        ),
        module=_module_out(module, await _get_schedule(db, module), encryption_context),
    )


@router.post(
    "/schedule-preview",
    response_model=SchedulePreviewResponse,
    include_in_schema=False,
)
@router.post(
    "/schedule/preview",
    response_model=SchedulePreviewResponse,
    summary="预览周期子选项与下一次执行日期",
)
async def preview_schedule(payload: SchedulePreviewRequest) -> SchedulePreviewResponse:
    try:
        start, end, cycle, sub_value = validate_schedule(
            payload.start_time,
            payload.end_time,
            payload.repeat_cycle,
            payload.repeat_sub_value,
        )
    except ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    today = datetime.now(settings.timezone_info).date()
    try:
        occurrence = next_occurrence(cycle, today, sub_value)
    except ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SchedulePreviewResponse(
        start_time=start,
        end_time=end,
        repeat_cycle=cycle,
        repeat_sub_value=sub_value,
        label=repeat_sub_label(cycle, sub_value),
        next_occurrence=occurrence,
    )


_ICON_RATE: dict[str, list[float]] = {}
_ICON_RATE_WINDOW = 60.0
_ICON_RATE_CLEANUP = 120.0
_ICON_RATE_LIMIT = 120
_ICON_RATE_LAST_CLEANUP = 0.0
_ICON_DECODE_LOCK = asyncio.Lock()
def _safe_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(
            "环境变量 %s=%r 非法，使用默认值 %s", name, raw, default
        )
        return default


def _safe_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning(
            "环境变量 %s=%r 非法，使用默认值 %s", name, raw, default
        )
        return default


# Icon decode configuration is loaded lazily on first icon request so that
# importing this module never validates environment variables. Supported vars:
# ICON_DECODE_POOL_SIZE (4), ICON_DECODE_POOL_MAX (16),
# ICON_DECODE_TIMEOUT (10.0). Runtime changes require a service restart.
# TODO: support hot reload through an explicit settings endpoint.
_ICON_CONFIG_DEFAULTS: dict[str, float] = {
    "ICON_DECODE_POOL_SIZE": 4,
    "ICON_DECODE_POOL_MAX": 16,
    "ICON_DECODE_TIMEOUT": 10.0,
}
_ICON_DECODE_POOL_SIZE = int(_ICON_CONFIG_DEFAULTS["ICON_DECODE_POOL_SIZE"])
_ICON_DECODE_POOL_MAX = int(_ICON_CONFIG_DEFAULTS["ICON_DECODE_POOL_MAX"])
_ICON_DECODE_TIMEOUT = float(_ICON_CONFIG_DEFAULTS["ICON_DECODE_TIMEOUT"])
_ICON_CONFIG_INITIALIZED = False
_ICON_CONFIG_LOCK = Lock()
_ACTIVE_ICON_EVENTS: "WeakSet[Event]" = WeakSet()
_ICON_DECODE_POOL: concurrent.futures.ThreadPoolExecutor | None = None


def _load_icon_config() -> None:
    """Load icon pool env vars once, on first request.

    Environment changes after the first call do not take effect; restart the
    service to apply new values.
    """
    global _ICON_DECODE_POOL_SIZE, _ICON_DECODE_POOL_MAX
    global _ICON_DECODE_TIMEOUT, _ICON_CONFIG_INITIALIZED, _ICON_DECODE_POOL
    if _ICON_CONFIG_INITIALIZED:
        return
    with _ICON_CONFIG_LOCK:
        if _ICON_CONFIG_INITIALIZED:
            return
        size = _safe_int_env(
            "ICON_DECODE_POOL_SIZE",
            int(_ICON_CONFIG_DEFAULTS["ICON_DECODE_POOL_SIZE"]),
        )
        maximum = _safe_int_env(
            "ICON_DECODE_POOL_MAX",
            int(_ICON_CONFIG_DEFAULTS["ICON_DECODE_POOL_MAX"]),
        )
        timeout = _safe_float_env(
            "ICON_DECODE_TIMEOUT",
            _ICON_CONFIG_DEFAULTS["ICON_DECODE_TIMEOUT"],
        )
        new_size = max(1, min(size, maximum))
        if _ICON_DECODE_POOL is None:
            _ICON_DECODE_POOL = concurrent.futures.ThreadPoolExecutor(
                max_workers=new_size
            )
        _ICON_DECODE_POOL_SIZE = new_size
        _ICON_DECODE_POOL_MAX = maximum
        _ICON_DECODE_TIMEOUT = timeout
        _ICON_CONFIG_INITIALIZED = True


def _get_icon_decode_pool() -> concurrent.futures.ThreadPoolExecutor:
    _load_icon_config()
    if _ICON_DECODE_POOL is None:
        raise RuntimeError("图标解码线程池未初始化")
    return _ICON_DECODE_POOL


def _tracked_load_icon(candidate: Path) -> tuple[bytes, str, int]:
    """Run a decode while publishing a completion event for shutdown.

    Event allocation is cheap relative to icon decoding and is bounded by
    concurrent decode requests; no object pooling is needed at this volume.
    """
    event = Event()
    _ACTIVE_ICON_EVENTS.add(event)
    try:
        return load_icon(candidate)
    finally:
        event.set()
        _ACTIVE_ICON_EVENTS.discard(event)


def shutdown_icon_decode_pool() -> None:
    """Stop accepting work and wait for tracked decode events.

    Events are set exclusively by worker threads in _tracked_load_icon;
    shutdown only waits and logs. Timed-out tasks are not forcefully
    terminated because Python ThreadPoolExecutor does not support interruption.
    """
    if _ICON_DECODE_POOL is None:
        return
    try:
        pool = _ICON_DECODE_POOL
        pool.shutdown(wait=False, cancel_futures=True)
        events = list(_ACTIVE_ICON_EVENTS)
        if not events:
            logger.warning("图标解码线程池关闭时没有活动任务")
        for event in events:
            completed = event.wait(timeout=5)
            if not completed:
                logger.warning(
                    "图标解码任务未在5秒内完成，线程可能仍在运行"
                )
        _ACTIVE_ICON_EVENTS.clear()
    except Exception:
        logger.warning("图标解码线程池关闭失败", exc_info=True)


_ICON_CACHE: "OrderedDict[tuple[str, int], tuple[bytes, str, float]]" = OrderedDict()
_ICON_CACHE_TTL = 60.0
_ICON_CACHE_MAX = 128
_ICON_CACHE_LOCK = Lock()


def _cleanup_icon_rate(now: float) -> None:
    global _ICON_RATE_LAST_CLEANUP
    if now - _ICON_RATE_LAST_CLEANUP < 60:
        return
    cutoff = now - _ICON_RATE_CLEANUP
    stale_ips = [
        ip for ip, stamps in list(_ICON_RATE.items())
        if not stamps or stamps[-1] < cutoff
    ]
    for ip in stale_ips:
        _ICON_RATE.pop(ip, None)
    _ICON_RATE_LAST_CLEANUP = now


def _cache_get(cache_key: tuple[str, int]) -> tuple[bytes, str] | None:
    with _ICON_CACHE_LOCK:
        cached = _ICON_CACHE.get(cache_key)
        if cached is None:
            return None
        if time.monotonic() - cached[2] >= _ICON_CACHE_TTL:
            _ICON_CACHE.pop(cache_key, None)
            return None
        _ICON_CACHE.move_to_end(cache_key)
        return cached[0], cached[1]


def _cache_put(cache_key: tuple[str, int], data: bytes, media_type: str) -> None:
    with _ICON_CACHE_LOCK:
        _ICON_CACHE[cache_key] = (data, media_type, time.monotonic())
        _ICON_CACHE.move_to_end(cache_key)
        while len(_ICON_CACHE) > _ICON_CACHE_MAX:
            _ICON_CACHE.popitem(last=False)


def _icon_response(data: bytes, media_type: str) -> Response:
    headers = {"Cache-Control": "public, max-age=86400"}
    if media_type == "image/svg+xml":
        headers.update({
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment",
            "Content-Security-Policy": "default-src 'none'",
        })
    return Response(content=data, media_type=media_type, headers=headers)


@public_router.get("/icon", summary="读取签到模块本地图标")
async def module_icon(
    request: Request,
    key: str = Query(min_length=1, max_length=80),
    path: str = Query(default="icon.ico", min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a module-local icon; directory_name comes from Module metadata."""
    # Process-local limiter. Multi-worker deployments need a shared Redis limiter.
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    _cleanup_icon_rate(now)
    bucket = [stamp for stamp in _ICON_RATE.get(client_ip, []) if now - stamp < _ICON_RATE_WINDOW]
    if len(bucket) >= _ICON_RATE_LIMIT:
        return Response(
            content=json.dumps({"detail": "图标请求过于频繁"}).encode(),
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": "60"},
        )
    bucket.append(now)
    _ICON_RATE[client_ip] = bucket

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
        raise HTTPException(status_code=400, detail="模块标识不合法")
    module = await db.scalar(select(Module).where(Module.key == key))
    directory = module.directory_name if module and module.directory_name else key
    try:
        validate_module_key(directory)
    except ModuleConfigError as exc:
        logger.warning(
            "模块图标目录映射非法：key=%s directory=%r", key, directory
        )
        raise HTTPException(
            status_code=403,
            detail=f"模块 {key} 的 directory_name={directory!r} 不合法：{exc}",
        ) from exc
    if "\x00" in path or "\\" in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="图标路径不合法")
    from pathlib import PurePosixPath

    rel = PurePosixPath(path)
    if rel.is_absolute() or any(part in {"..", ""} for part in rel.parts):
        raise HTTPException(status_code=400, detail="图标路径不合法")
    module_root = (settings.modules_dir / directory).resolve()
    root = settings.modules_dir.resolve()
    if not module_root.is_relative_to(root):
        logger.warning("模块图标目录越界：key=%s directory=%s", key, directory)
        raise HTTPException(status_code=403, detail="图标路径不合法")
    candidate = (module_root / rel).resolve()
    if not candidate.is_relative_to(module_root):
        logger.warning("拒绝模块图标路径越界：%s/%s", key, path)
        raise HTTPException(status_code=403, detail="图标路径不合法")

    try:
        current_mtime = await asyncio.to_thread(
            lambda: candidate.stat().st_mtime_ns
        )
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="图标不存在") from None
    cache_key = (str(candidate.resolve()), current_mtime)
    cached = _cache_get(cache_key)
    if cached is not None:
        data, media_type = cached
        return _icon_response(data, media_type)

    pool = _get_icon_decode_pool()
    try:
        async with _ICON_DECODE_LOCK:
            cached = _cache_get(cache_key)
            if cached is not None:
                data, media_type = cached
            else:
                loop = asyncio.get_running_loop()
                data, media_type, mtime_ns = await asyncio.wait_for(
                    loop.run_in_executor(
                        pool,
                        _tracked_load_icon,
                        candidate,
                    ),
                    timeout=_ICON_DECODE_TIMEOUT,
                )
                cache_key = (str(candidate.resolve()), mtime_ns)
                _cache_put(cache_key, data, media_type)
    except asyncio.TimeoutError:
        return Response(
            content=json.dumps({"detail": "图标解码超时"}).encode(),
            status_code=504,
            media_type="application/json",
            headers={"Retry-After": "1"},
        )
    except ModuleIconError as exc:
        logger.warning(
            "模块图标读取失败：key=%s path=%s resolved=%s detail=%s",
            key, path, candidate, exc.detail,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    logger.info(
        "解析模块图标：key=%s directory=%s path=%s resolved=%s",
        key, directory, path, candidate,
    )
    return _icon_response(data, media_type)


@router.get("/{module_id}", response_model=ModuleDetail, summary="模块详情、账号与执行时间")
async def get_module(module_id: int, db: AsyncSession = Depends(get_db)) -> ModuleDetail:
    module = await _get_module_or_404(db, module_id)
    context = EncryptionContext(
        user_id=await owner_user_id(db), module_key=module.key, account_index=-1
    )
    return await _module_detail(db, module, context)


@router.post(
    "/{module_id}/reveal-sensitive",
    response_model=RevealSensitiveResponse,
    summary="二次密码校验后显示敏感参数明文",
)
async def reveal_sensitive(
    module_id: int,
    payload: RevealSensitiveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevealSensitiveResponse:
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
        # Drop the request's read snapshot before verifying and reloading, so a
        # concurrent password change cannot make us accept a stale hash.
        await db.rollback()
        stored_user = await db.get(User, user_id)
        module = await db.get(Module, module_id)
        if stored_user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if module is None:
            raise HTTPException(status_code=404, detail="模块不存在")
        if not verify_password(payload.current_password, stored_user.password_hash):
            sensitive_limiter.record_failure(user_id)
            raise HTTPException(status_code=400, detail="当前密码不正确")
        sensitive_limiter.reset(user_id)

        context = EncryptionContext(
            user_id=await owner_user_id(db),
            module_key=module.key,
            account_index=-1,
        )
        schema = list(module.param_schema or [])
        try:
            params = parameter_cipher.decrypt(module.params_encrypted, context)
            accounts = _stored_accounts(module, context)
        except ParameterDecryptionError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"{exc} 可在配置页重新填写并保存参数。",
            ) from exc
        sensitive_params = _sensitive_only(cast("dict[str, Any]", params), schema)
        sensitive_accounts = [
            AccountOut(
                id=account.get("id", ""),
                label=account.get("label", ""),
                params=_sensitive_only(cast("dict[str, Any]", account.get("params") or {}), schema),
            )
            for account in accounts
        ]
        return RevealSensitiveResponse(
            params={} if module.multi_account else sensitive_params,
            accounts=sensitive_accounts,
        )


@router.put("/{module_id}", response_model=ModuleDetail, summary="保存账号、随机时间与推送开关")
async def update_module(
    module_id: int,
    payload: ModuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ModuleDetail:
    module = await _get_module_or_404(db, module_id)
    config = _live_config(module)
    context = EncryptionContext(
        user_id=await owner_user_id(db), module_key=module.key, account_index=-1
    )
    hooks = ModuleUpdateHooks(
        schedule_fields=_schedule_fields,
        stored_accounts=_stored_accounts,
        merge_accounts=_merge_sensitive_accounts,
        validate_accounts=_validated_accounts,
        stored_params=_stored_params,
        merge_params=_merge_sensitive_params,
        validate_params=validate_and_normalize_params,
        validate_stored_params=_validated_stored_params,
    )
    try:
        plan = plan_module_update(module, payload, config, context, hooks)
    except ModuleUpdateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    module.start_time = plan.start_time
    module.end_time = plan.end_time
    module.repeat_cycle = plan.repeat_cycle
    module.repeat_sub_value = plan.repeat_sub_value
    module.multi_account = bool(config.multi_account)
    if plan.params_encrypted is not None:
        module.params_encrypted = plan.params_encrypted
    if plan.accounts_encrypted is not None:
        module.accounts_encrypted = plan.accounts_encrypted
    if payload.push_independent is not None or payload.push_unified is not None:
        if payload.push_independent is not None:
            module.push_independent = payload.push_independent
        if payload.push_unified is not None:
            module.push_unified = payload.push_unified
        module.push_enabled = bool(module.push_independent or module.push_unified)
    elif payload.push_enabled is not None:
        module.push_independent = payload.push_enabled
        module.push_unified = False
        module.push_enabled = payload.push_enabled
    module.enabled = plan.target_enabled

    await db.commit()
    await db.refresh(module)
    if plan.schedule_changed:
        await cancel_pending_for_module(module.id)
    if module.enabled:
        await scheduler_service.refresh_module(module.id)
    else:
        scheduler_service.unschedule_module(module.id)
    await db.refresh(module)
    return await _module_detail(db, module, context)


@router.patch("/{module_id}/enabled", response_model=ModuleOut, summary="启用或禁用模块")
async def toggle_module(
    module_id: int,
    payload: ToggleRequest,
    db: AsyncSession = Depends(get_db),
) -> ModuleOut:
    module = await _get_module_or_404(db, module_id)
    config = _live_config(module)
    context = EncryptionContext(
        user_id=await owner_user_id(db), module_key=module.key, account_index=-1
    )
    if payload.enabled:
        if module.load_error:
            raise HTTPException(
                status_code=400,
                detail=f"模块加载异常，无法启用：{module.load_error}",
            )
        if config.multi_account:
            if not _validated_accounts(module, config, context):
                raise HTTPException(status_code=400, detail="请至少添加一个账号")
        else:
            _validated_stored_params(module, config, context)
    module.multi_account = bool(config.multi_account)
    module.enabled = payload.enabled
    await db.commit()
    await db.refresh(module)
    if module.enabled:
        await scheduler_service.refresh_module(module.id)
    else:
        scheduler_service.unschedule_module(module.id)
    await db.refresh(module)
    return _module_out(
        module, await _get_schedule(db, module), context
    )


@router.post(
    "/{module_id}/schedule/regenerate",
    response_model=RegenerateScheduleResponse,
    summary="手动重新生成本期随机时间",
)
async def regenerate_schedule(
    module_id: int, db: AsyncSession = Depends(get_db)
) -> RegenerateScheduleResponse:
    module = await _get_module_or_404(db, module_id)
    context = EncryptionContext(
        user_id=await owner_user_id(db), module_key=module.key, account_index=-1
    )
    if execution.is_module_running(module_id):
        raise HTTPException(status_code=409, detail="模块正在执行，请稍后再生成")
    try:
        schedule = await regenerate_current_schedule(module_id)
    except ScheduleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await scheduler_service.refresh_module(module_id)
    await db.refresh(module)
    schedule = await _get_schedule(db, module) or schedule
    return RegenerateScheduleResponse(
        message="本期随机执行时间已重新生成",
        schedule=ScheduleOut.model_validate(schedule_to_dict(schedule)),
        module=_module_out(module, schedule, context),
    )


@router.post("/{module_id}/run", response_model=RunResponse, summary="立即执行一次")
async def run_module_now(
    module_id: int, db: AsyncSession = Depends(get_db)
) -> RunResponse:
    await _get_module_or_404(db, module_id)
    try:
        log_id = await execution.launch_manual_execution(module_id)
    except execution.ExecutionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except execution.ExecutionRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except execution.ExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunResponse(log_id=log_id)


@router.post("/{module_id}/test", response_model=RunResponse, summary="开发者模式下执行一次测试")
async def test_module_now(
    module_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    await _get_module_or_404(db, module_id)
    try:
        log_id = await execution.launch_test_execution(module_id, current_user.id)
    except execution.DeveloperModeDisabledError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except execution.ExecutionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except execution.ExecutionRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except execution.ExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunResponse(log_id=log_id, message="测试执行已触发，请查看执行日志")


@router.delete("/{module_id}", response_model=MessageResponse, summary="彻底删除模块")
async def delete_module(
    module_id: str,
    delete_files: bool = Query(default=True, description="同时删除模块目录"),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Hard-delete a module, its physical directory and dependent rows.

    The directory is first renamed to a hidden trash path so a DB failure can
    restore it. Soft deletion is intentionally reserved for sync_modules().
    """
    if module_id.isdigit():
        module = await db.get(Module, int(module_id))
    else:
        module = await db.scalar(select(Module).where(Module.key == module_id))
    if module is None:
        raise HTTPException(status_code=404, detail="模块不存在")
    if execution.is_module_running(module.id):
        raise HTTPException(status_code=409, detail="模块正在执行，请等待结束后再删除")

    scheduler_service.unschedule_module(module.id)
    key = module.key
    name = module.name
    trash_path: Path | None = None
    physical_path: Path | None = None

    if delete_files:
        physical = get_module_physical_path(module).resolve()
        physical_path = physical
        root = settings.modules_dir.resolve()
        if not physical.is_relative_to(root) or physical.is_symlink():
            raise HTTPException(status_code=403, detail="模块目录路径不合法")
        if physical.exists():
            trash_path = physical.parent / f".trash-{key}-{uuid.uuid4().hex[:8]}"
            try:
                physical.rename(trash_path)
            except OSError as exc:
                logger.exception("模块目录暂存失败：key=%s", key)
                raise HTTPException(status_code=500, detail="无法移动模块目录，删除已取消") from exc

    try:
        await db.execute(delete(ExecutionLog).where(ExecutionLog.module_id == module.id))
        await db.execute(delete(ModuleSchedule).where(ModuleSchedule.module_id == module.id))
        await db.execute(delete(PushPool).where(PushPool.module_id == module.id))
        await db.delete(module)
        await db.commit()
    except Exception:
        await db.rollback()
        if trash_path is not None and trash_path.exists() and physical_path is not None:
            try:
                trash_path.rename(physical_path)
            except OSError:
                logger.exception("数据库删除失败且无法恢复模块目录：%s", trash_path)
        logger.exception("模块硬删除失败：key=%s", key)
        raise HTTPException(status_code=500, detail="数据库删除失败，模块目录已保留") from None

    cleanup_failed = False
    if trash_path is not None:
        try:
            shutil.rmtree(trash_path)
        except OSError:
            cleanup_failed = True
            logger.exception("模块数据库已删除，但物理目录清理失败：%s", trash_path)

    remaining = await _load_modules(db)
    await scheduler_service.reconcile(remaining)
    message = f"模块「{name}」已彻底删除"
    if cleanup_failed:
        message += "；数据库记录已删除，但临时目录需手动清理，请查看服务日志"
    return MessageResponse(message=message)
