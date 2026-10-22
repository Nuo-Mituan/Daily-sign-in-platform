"""Dashboard statistics and recent activity."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    ExecutionLog,
    Module,
)
from ..schemas import DashboardOut, DashboardStats, LogOut
from ..services.execution import running_module_count
from ..timeutils import today_bounds_utc

router = APIRouter(
    prefix="/dashboard",
    tags=["仪表盘"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=DashboardOut, summary="仪表盘统计与最近执行")
async def get_dashboard(
    recent_limit: int = Query(default=8, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
) -> DashboardOut:
    start_utc, end_utc = today_bounds_utc(settings.timezone_info)
    today_condition = (ExecutionLog.started_at >= start_utc) & (
        ExecutionLog.started_at <= end_utc
    )

    total_modules = int(
        await db.scalar(select(func.count()).select_from(Module)) or 0
    )
    enabled_modules = int(
        await db.scalar(
            select(func.count()).select_from(Module).where(Module.enabled.is_(True))
        )
        or 0
    )
    today_runs = int(
        await db.scalar(
            select(func.count()).select_from(ExecutionLog).where(today_condition)
        )
        or 0
    )
    today_success = int(
        await db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .where(today_condition, ExecutionLog.status == STATUS_SUCCESS)
        )
        or 0
    )
    today_failed = int(
        await db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .where(today_condition, ExecutionLog.status == STATUS_FAILED)
        )
        or 0
    )
    today_running = int(
        await db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .where(today_condition, ExecutionLog.status == STATUS_RUNNING)
        )
        or 0
    )

    completed = today_success + today_failed
    success_rate = round(today_success / completed * 100, 1) if completed else 0.0

    recent_rows = (
        (
            await db.execute(
                select(ExecutionLog)
                .order_by(ExecutionLog.started_at.desc(), ExecutionLog.id.desc())
                .limit(recent_limit)
            )
        )
        .scalars()
        .all()
    )

    return DashboardOut(
        stats=DashboardStats(
            total_modules=total_modules,
            enabled_modules=enabled_modules,
            today_runs=today_runs,
            today_success=today_success,
            today_failed=today_failed,
            today_running=today_running,
            success_rate=success_rate,
            running_modules=running_module_count(),
        ),
        recent=[LogOut.model_validate(row) for row in recent_rows],
    )
