"""Public health check and authenticated system metadata."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..database import SessionLocal
from ..deps import get_current_user
from ..schemas import (
    HealthOut,
    LogSettingsOut,
    LogSettingsUpdate,
    LogSettingsUpdateOut,
    DeveloperModeOut,
    DeveloperModeUpdate,
    MetaOut,
    RuntimeMetricsOut,
    SystemLogOut,
    SystemLogPage,
)
from ..scheduling import CYCLE_LABELS, REPEAT_CYCLES
from ..services.maintenance import purge_old_logs
from ..services.ring_log import ring_log
from ..services.push_outbox import pending_count as outbox_pending_count
from ..services.preferences import set_developer_mode
from ..services.hub import hub
from ..services.scheduler import scheduler_service
from ..timeutils import utcnow

health_router = APIRouter(tags=["系统"])


@health_router.get("/health", response_model=HealthOut, summary="健康检查")
async def health() -> HealthOut:
    return HealthOut(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        scheduler_running=scheduler_service.running,
        time=utcnow(),
    )


meta_router = APIRouter(
    prefix="/meta",
    tags=["系统"],
    dependencies=[Depends(get_current_user)],
)


@meta_router.get("", response_model=MetaOut, summary="系统信息")
async def meta() -> MetaOut:
    return MetaOut(
        app_name=settings.app_name,
        version=settings.app_version,
        timezone=settings.timezone,
        module_timeout=settings.module_timeout,
        account_interval_min_seconds=settings.account_interval_min_seconds,
        account_interval_max_seconds=settings.account_interval_max_seconds,
        log_retention_days=ring_log.get_retention_days(),
        repeat_cycles=[
            {"value": cycle, "label": CYCLE_LABELS[cycle]}
            for cycle in REPEAT_CYCLES
        ],
        modules_dir=str(settings.modules_dir),
    )


settings_router = APIRouter(
    prefix="/settings",
    tags=["系统"],
    dependencies=[Depends(get_current_user)],
)


def _log_settings() -> LogSettingsOut:
    stats = ring_log.stats()
    return LogSettingsOut(
        retention_days=ring_log.get_retention_days(),
        total_rows=int(stats.get("total_rows", 0)),
        total_bytes=int(stats.get("total_bytes", 0)),
    )


@settings_router.get("/logs", response_model=LogSettingsOut, summary="读取日志保留设置")
async def get_log_settings() -> LogSettingsOut:
    return _log_settings()


@settings_router.get(
    "/developer", response_model=DeveloperModeOut, summary="读取开发者模式"
)
async def get_developer_mode(
    current_user=Depends(get_current_user),
) -> DeveloperModeOut:
    return DeveloperModeOut(enabled=bool(current_user.developer_mode_enabled))


@settings_router.put(
    "/developer", response_model=DeveloperModeOut, summary="开启或关闭开发者模式"
)
async def update_developer_mode(
    payload: DeveloperModeUpdate,
    current_user=Depends(get_current_user),
) -> DeveloperModeOut:
    async with SessionLocal() as db:
        updated = await set_developer_mode(db, current_user.id, payload.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")
    return DeveloperModeOut(enabled=payload.enabled)


@settings_router.put(
    "/logs", response_model=LogSettingsUpdateOut, summary="修改日志保留天数并立即裁剪"
)
async def update_log_settings(payload: LogSettingsUpdate) -> LogSettingsUpdateOut:
    removed_ring = await asyncio.to_thread(
        ring_log.set_retention_days, payload.retention_days
    )
    removed_history, removed_files = await purge_old_logs(payload.retention_days)
    current = _log_settings()
    return LogSettingsUpdateOut(
        **current.model_dump(),
        removed_ring=removed_ring,
        removed_history=removed_history,
        removed_files=removed_files,
        message=(
            f"已保存 {payload.retention_days} 天保留策略，"
            f"清理环形日志 {removed_ring} 条、历史记录 {removed_history} 条、"
            f"旧文件 {removed_files} 个"
        ),
    )



system_router = APIRouter(
    prefix="/system",
    tags=["系统"],
    dependencies=[Depends(get_current_user)],
)


@system_router.get(
    "/logs", response_model=SystemLogPage, summary="只读系统/应用日志"
)
async def system_logs(
    scope_type: str | None = None,
    level: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> SystemLogPage:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    rows, total = ring_log.read_page(
        page=page,
        page_size=page_size,
        scope_type=scope_type,
        level=level,
    )
    return SystemLogPage(
        items=[SystemLogOut(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size) if total else 0,
    )


@system_router.get(
    "/metrics", response_model=RuntimeMetricsOut, summary="只读运行时指标"
)
async def runtime_metrics() -> RuntimeMetricsOut:
    return RuntimeMetricsOut(
        ring=ring_log.stats(),
        sse=hub.metrics(),
        push_outbox_pending=await outbox_pending_count(),
    )
