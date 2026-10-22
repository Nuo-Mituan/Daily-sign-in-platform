"""Dynamic random-schedule integration with APScheduler.

Each enabled module has up to three one-shot DateTrigger jobs:

* ``module:<id>:plan``     -> local midnight on the next cycle start
* ``module:<id>:exec``     -> the generated random execution moment
* ``module:<id>:fallback`` -> window midpoint, only acts if no schedule exists

A global hourly safety job retries missing current-period generation, and a
daily maintenance job prunes old logs.  There are no per-module CronTriggers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import settings
from ..database import SessionLocal
from ..models import Module
from ..scheduling import (
    ScheduleError,
    midpoint_scheduled_at,
    next_plan_at,
    period_start_for,
    repeat_sub_label,
    validate_schedule,
)
from .execution import run_scheduled
from .maintenance import purge_old_logs
from .push import notify_module
from .push_delivery import recover_pending_supplements
from .push_pool import configure_daily_batch, ensure_batch, flush_due_batches
from .schedules import (
    SCHEDULE_CANCELLED,
    SCHEDULE_EXECUTED,
    SCHEDULE_FALLBACK,
    SCHEDULE_MISFIRE_GRACE_SECONDS,
    SCHEDULE_MISSED,
    SCHEDULE_PENDING,
    apply_fallback,
    ensure_current_schedule,
    mark_schedule_finished,
    claim_schedule_for_execution,
)

logger = logging.getLogger(__name__)

MODULE_JOB_PREFIX = "module:"
MAINTENANCE_JOB_ID = "system:log-retention"
RETRY_JOB_ID = "system:schedule-retry"


class SchedulerService:
    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    @property
    def scheduler(self) -> AsyncIOScheduler | None:
        return self._scheduler

    @property
    def running(self) -> bool:
        return bool(self._scheduler and self._scheduler.running)

    def start(self) -> None:
        if self._scheduler is not None:
            return
        scheduler = AsyncIOScheduler(
            timezone=settings.timezone_info,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )
        scheduler.start()
        self._scheduler = scheduler
        self._scheduler.add_job(
            self._cleanup_logs,
            trigger=CronTrigger(hour=3, minute=10, timezone=settings.timezone_info),
            id=MAINTENANCE_JOB_ID,
            name="清理过期执行日志",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._ensure_unified_batch,
            trigger=CronTrigger(hour=0, minute=5, timezone=settings.timezone_info),
            id="system:unified-batch-init",
            name="初始化统一推送批次",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._plan_unified_batch,
            trigger=CronTrigger(hour=1, minute=0, timezone=settings.timezone_info),
            id="system:unified-batch-plan",
            name="计算统一推送时间",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self._scheduler.add_job(
            self._sweep_unified_batches,
            trigger=IntervalTrigger(minutes=1),
            id="system:unified-batch-sweep",
            name="统一推送主触发与超时兜底检查",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        self._scheduler.add_job(
            recover_pending_supplements,
            trigger=IntervalTrigger(minutes=5),
            id="system:supplement-recovery",
            name="补发推送 PENDING 审计补偿",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self._hourly_retry,
            trigger=CronTrigger(minute=0, timezone=settings.timezone_info),
            id=RETRY_JOB_ID,
            name="整点随机时间生成补偿",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        logger.info("调度器已启动，时区=%s（随机时间调度）", settings.timezone)

    def shutdown(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("调度器已停止")
        self._scheduler = None

    # ------------------------------------------------------------------ ids
    def _plan_id(self, module_id: int) -> str:
        return f"{MODULE_JOB_PREFIX}{module_id}:plan"

    def _exec_id(self, module_id: int) -> str:
        return f"{MODULE_JOB_PREFIX}{module_id}:exec"

    def _fallback_id(self, module_id: int) -> str:
        return f"{MODULE_JOB_PREFIX}{module_id}:fallback"

    def _module_job_ids(self, module_id: int) -> tuple[str, str, str]:
        return (
            self._plan_id(module_id),
            self._exec_id(module_id),
            self._fallback_id(module_id),
        )

    def unschedule_module(self, module_id: int) -> None:
        if self._scheduler is None:
            return
        for job_id in self._module_job_ids(module_id):
            if self._scheduler.get_job(job_id) is not None:
                try:
                    self._scheduler.remove_job(job_id)
                except Exception:
                    logger.debug("移除调度任务失败：%s", job_id, exc_info=True)

    def _add_job(self, func, trigger, job_id: str, name: str) -> None:
        if self._scheduler is None:
            return
        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )

    # -------------------------------------------------------------- planning
    async def _load_module(self, module_id: int) -> Module | None:
        async with SessionLocal() as db:
            return await db.get(Module, module_id)

    async def refresh_module(self, module_id: int) -> bool:
        """Recompute jobs for one module. Safe to call after any config change."""
        self.unschedule_module(module_id)
        module = await self._load_module(module_id)
        if module is None or not module.enabled or module.load_error:
            return False
        try:
            start_time, end_time, cycle, sub_value = validate_schedule(
                module.start_time,
                module.end_time,
                module.repeat_cycle,
                module.repeat_sub_value,
            )
        except ScheduleError as exc:
            logger.warning("模块 %s 随机时间配置无效：%s", module.key, exc)
            return False

        if self._scheduler is None:
            # Unit tests and maintenance scripts may call the service without a
            # running APScheduler; still keep the persisted schedule consistent.
            try:
                await ensure_current_schedule(module_id)
            except Exception:
                logger.exception("模块 %s 生成本期随机时间失败", module.key)
                return False
            return True

        # Generate the current period if we're on its start day. Failures are
        # retried by the hourly safety job.
        try:
            schedule = await ensure_current_schedule(module_id)
        except Exception:
            logger.exception("模块 %s 生成本期随机时间失败", module.key)
            schedule = None

        now = datetime.now(timezone.utc)
        local_now = now.astimezone(settings.timezone_info)
        today = local_now.date()
        period = period_start_for(cycle, today, sub_value)

        # Next occurrence job (local midnight).
        plan_at = next_plan_at(
            cycle, settings.timezone_info, now, sub_value
        )
        try:
            self._add_job(
                self._make_plan_job(module_id),
                DateTrigger(run_date=plan_at),
                self._plan_id(module_id),
                f"{module.name} 执行日生成随机时间",
            )
        except Exception:
            logger.exception("模块 %s 注册周期计划任务失败", module.key)

        # Execution job for the current pending schedule.
        if (
            schedule is not None
            and schedule.status in {SCHEDULE_PENDING, SCHEDULE_FALLBACK}
            and schedule.scheduled_at
            > now - timedelta(seconds=SCHEDULE_MISFIRE_GRACE_SECONDS)
        ):
            try:
                run_at = schedule.scheduled_at
                if run_at <= now:
                    # Late recovery within APScheduler's grace window.
                    run_at = now + timedelta(seconds=1)
                self._add_job(
                    self._make_execution_job(module_id, schedule.id),
                    DateTrigger(run_date=run_at),
                    self._exec_id(module_id),
                    f"{module.name} 随机执行",
                )
                logger.info(
                    "模块 %s 已安排本次执行：%s（%s，%s-%s）",
                    module.key,
                    schedule.scheduled_at.astimezone(settings.timezone_info).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    repeat_sub_label(cycle, sub_value),
                    start_time,
                    end_time,
                )
            except Exception:
                logger.exception("模块 %s 注册执行任务失败", module.key)

        # Midpoint watchdog: it only creates a fallback if no schedule exists at
        # midnight/through the retries.  If the midpoint has already passed and no
        # schedule exists, the hourly retry will handle the same situation.
        if today == period:
            midpoint = midpoint_scheduled_at(
                period, start_time, end_time, settings.timezone_info
            )
            needs_watchdog = (
                schedule is None
                or schedule.status in {SCHEDULE_CANCELLED, SCHEDULE_MISSED}
            )
            if needs_watchdog and midpoint > now:
                try:
                    self._add_job(
                        self._make_fallback_job(module_id),
                        DateTrigger(run_date=midpoint),
                        self._fallback_id(module_id),
                        f"{module.name} 随机时间兜底检查",
                    )
                except Exception:
                    logger.exception("模块 %s 注册兜底任务失败", module.key)
        return True

    def _make_plan_job(self, module_id: int):
        async def job() -> None:
            try:
                await self.refresh_module(module_id)
            except Exception:
                logger.exception("模块 %s 周期随机时间生成任务失败", module_id)

        return job

    def _make_execution_job(self, module_id: int, schedule_id: int):
        async def job() -> None:
            await self._execute_schedule(module_id, schedule_id)

        return job

    def _make_fallback_job(self, module_id: int):
        async def job() -> None:
            try:
                await self._run_fallback(module_id)
            except Exception:
                logger.exception("模块 %s 随机时间兜底任务失败", module_id)
                await self._hourly_retry()

        return job

    async def _run_fallback(self, module_id: int) -> None:
        schedule, created = await apply_fallback(module_id)
        if not created or schedule is None:
            return
        module = await self._load_module(module_id)
        if module is None:
            return
        local_time = schedule.scheduled_at.astimezone(settings.timezone_info)
        logger.warning(
            "模块 %s 随机时间生成失败，已使用兜底时间 %s",
            module.key,
            local_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        if module.push_enabled:
            try:
                await notify_module(
                    module_id,
                    event="schedule_failure",
                    status_text="失败",
                    result=(
                        f"随机时间生成失败，已使用时间窗中点兜底："
                        f"{local_time.strftime('%Y-%m-%d %H:%M:%S')}"
                    ),
                    account="—",
                    duration="—",
                    error="本期随机时间未能按时生成",
                    summary="随机时间生成失败",
                )
            except Exception:
                logger.exception("发送随机时间生成失败推送时出错（模块 %s）", module_id)

        # Register the fallback execution and repair any missing plan job.
        await self.refresh_module(module_id)

    async def _execute_schedule(self, module_id: int, schedule_id: int) -> None:
        if not await claim_schedule_for_execution(schedule_id):
            return
        try:
            log_id = await run_scheduled(module_id)
            if log_id is None:
                await mark_schedule_finished(
                    schedule_id,
                    status=SCHEDULE_MISSED,
                    note="模块被禁用、加载异常或正在执行，跳过了本次计划",
                )
                return
            await mark_schedule_finished(
                schedule_id, status=SCHEDULE_EXECUTED, note="定时执行已完成"
            )
        except Exception as exc:
            logger.exception("模块 %s 定时执行失败", module_id)
            await mark_schedule_finished(
                schedule_id,
                status=SCHEDULE_MISSED,
                note=f"调度执行异常：{type(exc).__name__}: {exc}"[:1000],
            )

    async def _hourly_retry(self) -> None:
        """At each hour, repair missing current-period schedules."""
        if self._scheduler is None:
            return
        async with SessionLocal() as db:
            modules = (
                (
                    await db.execute(
                        select(Module).where(
                            Module.enabled.is_(True), Module.load_error.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
        for module in modules:
            try:
                # Only refresh modules that could still need a current schedule or
                # whose jobs are missing. Calling refresh for all modules is cheap
                # and also repairs a scheduler that lost in-memory jobs.
                await self.refresh_module(module.id)
            except Exception:
                logger.exception("整点调度补偿失败（模块 %s）", module.key)

    async def reconcile(self, modules: list[Module]) -> int:
        if self._scheduler is None:
            return 0
        active_ids = {
            module.id for module in modules if module.enabled and not module.load_error
        }
        for job in list(self._scheduler.get_jobs()):
            if not job.id.startswith(MODULE_JOB_PREFIX):
                continue
            try:
                job_module_id = int(job.id[len(MODULE_JOB_PREFIX) :].split(":", 1)[0])
            except ValueError:
                continue
            if job_module_id not in active_ids:
                self.unschedule_module(job_module_id)
        count = 0
        for module in modules:
            if module.enabled and not module.load_error:
                if await self.refresh_module(module.id):
                    count += 1
            else:
                self.unschedule_module(module.id)
        return count

    def remove_unified_main_job(self, cycle_id: str) -> None:
        if self._scheduler is None:
            return
        job_id = f"system:unified-main:{cycle_id}"
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    async def plan_unified_batch(self) -> None:
        try:
            batch = await configure_daily_batch()
            if (
                batch is None
                or batch.trigger_at is None
                or batch.status != "pending"
                or self._scheduler is None
            ):
                return
            run_date = batch.trigger_at.astimezone(settings.timezone_info)
            if run_date <= datetime.now(settings.timezone_info):
                return
            self._scheduler.add_job(
                self._run_unified_main,
                trigger=DateTrigger(run_date=run_date),
                args=[batch.cycle_id],
                id=f"system:unified-main:{batch.cycle_id}",
                name=f"统一推送主触发 {batch.cycle_id}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
            logger.info("已注册统一推送主触发 %s → %s", batch.cycle_id, run_date)
        except Exception:
            logger.exception("计算统一推送时间失败")

    async def _run_unified_main(self, cycle_id: str) -> None:
        try:
            from .push_pool import FLUSH_MAIN, flush_batch

            await flush_batch(cycle_id, mode=FLUSH_MAIN)
        except Exception:
            logger.exception("统一推送主触发失败：%s", cycle_id)

    async def _plan_unified_batch(self) -> None:
        await self.plan_unified_batch()

    async def _ensure_unified_batch(self) -> None:
        try:
            await ensure_batch()
        except Exception:
            logger.exception("初始化统一推送批次失败")

    async def _sweep_unified_batches(self) -> None:
        try:
            await flush_due_batches()
        except Exception:
            logger.exception("统一推送批次超时检查失败")

    async def _cleanup_logs(self) -> None:
        try:
            await purge_old_logs()
        except Exception:
            logger.exception("清理过期日志失败")


scheduler_service = SchedulerService()
