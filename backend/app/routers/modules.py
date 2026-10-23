"""Module management API: CRUD, hot-plug, accounts, random schedule and runs."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import EncryptionContext, ParameterDecryptionError, parameter_cipher
from ..database import get_db
from ..deps import AuthContext, get_auth_context, get_current_user
from ..models import ExecutionLog, Module, ModuleSchedule, User
from ..module_loader import (
    ModuleConfig,
    ModuleConfigError,
    normalize_accounts,
    parse_config_file,
    sync_modules,
    validate_and_normalize_params,
)
from ..scheduling import (
    ScheduleError,
    next_occurrence,
    repeat_sub_label,
    validate_schedule,
)
from ..schemas import (
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
    remove_module_directory,
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
        return parse_config_file(settings.modules_dir / module.key / "config.json")
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


@router.post("/scan", response_model=ScanResponse, summary="扫描模块目录并热加载")
async def scan_modules(db: AsyncSession = Depends(get_db)) -> ScanResponse:
    result = await sync_modules(db)
    all_modules = await _load_modules(db)
    await scheduler_service.reconcile(all_modules)
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


@router.post("/upload", response_model=UploadResponse, summary="上传 ZIP 模块并热安装")
async def upload_module(
    file: UploadFile = File(..., description="ZIP 压缩包"),
    name: str | None = Form(default=None, description="可选：模块标识（目录名）"),
    overwrite: bool = Query(default=False, description="覆盖同名模块"),
    current_user: User = Depends(get_current_user),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    try:
        key, _config = await install_module_upload(file, name, overwrite)
    except (ModuleUploadError, ModuleConfigError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("安装上传模块失败")
        raise HTTPException(status_code=500, detail=f"安装模块失败：{exc}") from exc
    finally:
        await file.close()

    sync_result = await sync_modules(db)
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


@router.get("/icon", summary="读取签到模块本地图标")
async def module_icon(
    key: str = Query(min_length=1, max_length=80),
    path: str = Query(default="icon.ico", min_length=1, max_length=255),
) -> Response:
    """Serve an image from one module directory with traversal/symlink checks."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
        raise HTTPException(status_code=400, detail="模块标识不合法")
    if "\x00" in path or "\\" in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="图标路径不合法")
    from pathlib import PurePosixPath

    rel = PurePosixPath(path)
    if rel.is_absolute() or any(part in {"..", ""} for part in rel.parts):
        raise HTTPException(status_code=400, detail="图标路径不合法")
    module_root = (settings.modules_dir / key).resolve()
    root = settings.modules_dir.resolve()
    if not module_root.is_relative_to(root):
        raise HTTPException(status_code=403, detail="图标路径不合法")
    candidate = (module_root / rel).resolve()
    if not candidate.is_relative_to(module_root):
        logger.warning("拒绝模块图标路径越界：%s/%s", key, path)
        raise HTTPException(status_code=403, detail="图标路径不合法")
    try:
        size = candidate.stat().st_size
    except (OSError, ValueError):
        logger.warning("模块图标不存在或不可读：%s/%s", key, path)
        raise HTTPException(status_code=404, detail="图标不存在") from None
    if size > 64 * 1024:
        logger.warning("模块图标超过 64KB：%s/%s", key, path)
        raise HTTPException(status_code=413, detail="图标文件过大")
    try:
        data = candidate.read_bytes()
    except OSError:
        logger.warning("模块图标读取失败：%s/%s", key, path)
        raise HTTPException(status_code=404, detail="图标不存在") from None
    if len(data) < 4 or data[:4] != b"\x00\x00\x01\x00":
        logger.warning("模块图标不是合法 ICO：%s/%s", key, path)
        raise HTTPException(status_code=415, detail="图标格式不合法")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "ICO":
                raise UnidentifiedImageError("not ico")
            if image.width <= 0 or image.height <= 0 or image.width * image.height > 1024 * 1024:
                raise ValueError("icon dimensions too large")
            rgba = image.convert("RGBA")
            output = BytesIO()
            rgba.save(output, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError):
        logger.warning("模块图标 ICO 解码失败：%s/%s", key, path)
        raise HTTPException(status_code=415, detail="图标格式不合法") from None
    return Response(
        content=output.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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


@router.delete("/{module_id}", response_model=MessageResponse, summary="删除模块")
async def delete_module(
    module_id: int,
    delete_files: bool = Query(default=True, description="同时删除模块目录"),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    module = await _get_module_or_404(db, module_id)
    if execution.is_module_running(module_id):
        raise HTTPException(status_code=409, detail="模块正在执行，请等待结束后再删除")

    scheduler_service.unschedule_module(module_id)
    key = module.key
    name = module.name
    if delete_files:
        try:
            remove_module_directory(key)
        except (ModuleUploadError, ModuleConfigError, OSError) as exc:
            raise HTTPException(status_code=500, detail=f"删除模块文件失败：{exc}") from exc

    await db.execute(delete(ExecutionLog).where(ExecutionLog.module_id == module_id))
    await db.execute(delete(ModuleSchedule).where(ModuleSchedule.module_id == module_id))
    await db.delete(module)
    await db.commit()
    remaining = await _load_modules(db)
    await scheduler_service.reconcile(remaining)
    return MessageResponse(message=f"模块「{name}」已删除")
