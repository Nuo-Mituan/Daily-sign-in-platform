"""Module execution pipeline: multi-account serial runs, logs and notifications."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime

from ..config import settings
from ..crypto import EncryptionContext, ParameterDecryptionError, parameter_cipher
from ..database import SessionLocal
from ..models import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULE,
    TRIGGER_TEST,
    ExecutionLog,
    Module,
)
from ..module_loader import (
    get_module_physical_path,
    ModuleConfig,
    ModuleConfigError,
    account_display,
    account_identity,
    load_runner,
    normalize_accounts,
    parse_config_file,
    unload_runner,
    validate_and_normalize_params,
)
from ..timeutils import utcnow
from .ownership import owner_user_id
from .preferences import developer_mode_enabled
from .redaction import collect_sensitive_values, redact_text, sensitive_values
from .capture import OutputCapture, capture_output
from .hub import hub
from .lock_registry import KeyLockRegistry
from .push import send_independent_module
from .push_pool import record_unified_result

logger = logging.getLogger(__name__)

_module_locks = KeyLockRegistry[int](max_unlocked=256)
_background_tasks: set[asyncio.Task] = set()


class ExecutionError(RuntimeError):
    pass


class DeveloperModeDisabledError(ExecutionError):
    """Raised when a test execution is attempted without developer mode."""


class ExecutionBusyError(ExecutionError):
    pass


class ExecutionRejectedError(ExecutionError):
    pass


@dataclass
class AccountResult:
    index: int
    account_id: str
    display: str
    success: bool
    message: str
    duration_ms: int
    error: str = ""


@dataclass
class ExecutionOutcome:
    status: str
    message: str
    cancelled: bool = False
    total_accounts: int = 0
    success_accounts: int = 0
    failed_accounts: int = 0
    account_results: list[AccountResult] = field(default_factory=list)


def _lock_for(module_id: int) -> asyncio.Lock:
    return _module_locks.get(module_id)


def is_module_running(module_id: int) -> bool:
    lock = _module_locks.get(module_id)
    return bool(lock and lock.locked())


def running_module_count() -> int:
    return sum(1 for lock in _module_locks.values() if lock.locked())


def active_task_count() -> int:
    return len(_background_tasks)


async def shutdown_background_tasks(timeout: float = 5.0) -> None:
    tasks = [task for task in _background_tasks if not task.done()]
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    await asyncio.wait(tasks, timeout=timeout)


def _track_task(task: asyncio.Task) -> None:
    _background_tasks.add(task)

    def on_done(completed: asyncio.Task) -> None:
        _background_tasks.discard(completed)
        if completed.cancelled():
            return
        try:
            error = completed.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "后台执行任务异常退出",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(on_done)


async def _create_log(module: Module, trigger: str) -> ExecutionLog:
    now = utcnow()
    log = ExecutionLog(
        module_id=module.id,
        module_key=module.key,
        module_name=f"[TEST] {module.name}" if trigger == TRIGGER_TEST else module.name,
        trigger=trigger,
        status=STATUS_RUNNING,
        started_at=now,
    )
    module.last_run_at = now
    module.last_status = STATUS_RUNNING
    return log


async def launch_manual_execution(module_id: int) -> int:
    """Start a manual run in the background and return the execution log id."""
    return await _launch_execution(module_id, TRIGGER_MANUAL)


async def launch_test_execution(module_id: int, user_id: int) -> int:
    """Start a developer-mode test run; permission is enforced server-side."""
    async with SessionLocal() as db:
        if not await developer_mode_enabled(db, user_id):
            raise DeveloperModeDisabledError("请先在设置中开启开发者选项")
    return await _launch_execution(module_id, TRIGGER_TEST)


async def _launch_execution(module_id: int, trigger: str) -> int:
    lock = _lock_for(module_id)
    if lock.locked():
        raise ExecutionBusyError("该模块正在执行中，请等待本次执行结束")
    await lock.acquire()
    handed_off = False
    try:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None:
                raise ExecutionRejectedError("模块不存在或已被删除")
            if module.load_error:
                raise ExecutionRejectedError(
                    f"模块当前不可执行：{module.load_error}。请修复模块文件后重新扫描。"
                )
            log = await _create_log(module, trigger)
            db.add(log)
            await db.commit()
            await db.refresh(log)
            log_id = log.id
            started_at = log.started_at

        hub.begin(log_id)
        task = asyncio.create_task(
            _execute(module_id, log_id, started_at, trigger, module.key)
        )
        _track_task(task)
        handed_off = True
        return log_id
    finally:
        if not handed_off and lock.locked():
            lock.release()


async def run_scheduled(module_id: int) -> int | None:
    """Scheduled entry point. Skips when the module is disabled or already running."""
    lock = _lock_for(module_id)
    if lock.locked():
        logger.info("模块 %s 仍在执行，跳过本次定时触发", module_id)
        return None
    await lock.acquire()
    handed_off = False
    try:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None or not module.enabled or module.load_error:
                return None
            log = await _create_log(module, TRIGGER_SCHEDULE)
            db.add(log)
            await db.commit()
            await db.refresh(log)
            log_id = log.id
            started_at = log.started_at

        hub.begin(log_id)
        handed_off = True
        await _execute(module_id, log_id, started_at, TRIGGER_SCHEDULE, module.key)
        return log_id
    finally:
        if not handed_off and lock.locked():
            lock.release()


async def _invoke_run(run: object, params: dict[str, object]) -> object:
    if inspect.iscoroutinefunction(run):
        return await run(params)
    result = await asyncio.to_thread(run, params)  # type: ignore[arg-type, var-annotated]  # TODO(v1.0.3): fix typing
    if inspect.isawaitable(result):
        return await result
    return result


def _coerce_success(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "ok"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        raise ExecutionRejectedError("success 字段必须是布尔值")
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ExecutionRejectedError("success 字段必须是布尔值")


def _normalize_message(result: dict[str, object], success: bool) -> str:
    message = result.get("message") or result.get("msg") or (
        "执行成功" if success else "执行失败"
    )
    message = str(message).strip() or ("执行成功" if success else "执行失败")
    return message[:4000] + "…" if len(message) > 4000 else message


def _extras_text(result: dict[str, object]) -> str | None:
    extras = {
        key: value
        for key, value in result.items()
        if key not in {"success", "message", "msg"}
    }
    if not extras:
        return None
    try:
        text = json.dumps(extras, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str covers most
        text = str(extras)
    return text[:8000] + "…" if len(text) > 8000 else text


def _normalize_result(result: object) -> tuple[bool, str, str | None]:
    if not isinstance(result, dict):
        raise ExecutionRejectedError(
            "run(params) 必须返回 dict，例如 {'success': True, 'message': '签到成功'}"
        )
    if "success" not in result:
        raise ExecutionRejectedError("run(params) 的返回值缺少必需字段 success")
    success = _coerce_success(result.get("success"))
    return success, _normalize_message(result, success), _extras_text(result)

def _load_accounts(
    config: ModuleConfig, module: Module, encryption_context: EncryptionContext
) -> list[dict[str, object]]:
    if config.multi_account:
        if module.accounts_encrypted:
            raw, _ = parameter_cipher.decrypt_accounts(
                module.accounts_encrypted, encryption_context
            )
        elif module.params_encrypted:
            raw = [
                {
                    "id": f"legacy-{module.id}",
                    "label": "",
                    "params": parameter_cipher.decrypt(
                        module.params_encrypted, encryption_context
                    ),
                }
            ]
        else:
            raw = []
        if not isinstance(raw, list) or not raw:
            raise ExecutionRejectedError("多账号模块尚未配置账号，请先在配置页添加账号")
        normalized = normalize_accounts(config, raw)
        for entry in normalized:
            entry["display"] = account_display(config, entry)
        return normalized

    params = validate_and_normalize_params(
        config,
        parameter_cipher.decrypt(module.params_encrypted, encryption_context),
    )
    return [
        {
            "id": "single",
            "label": "",
            "params": params,
            "display": account_identity(config, params),
        }
    ]


def _aggregate(results: list[AccountResult]) -> tuple[str, str, int, int]:
    total = len(results)
    success_count = sum(1 for item in results if item.success)
    failed_count = total - success_count

    if total == 1:
        message = results[0].message
    elif success_count == total:
        message = f"全部 {total} 个账号签到成功"
    elif success_count == 0:
        message = f"全部 {total} 个账号签到失败"
    else:
        message = f"{total} 个账号中 {success_count} 个成功、{failed_count} 个失败"

    status = STATUS_SUCCESS if total > 0 and success_count == total else STATUS_FAILED
    return status, message, success_count, failed_count



async def _load_execution_module(
    module_id: int,
) -> tuple[Module, EncryptionContext]:
    """Load a module and lazily upgrade v1 ciphertext before execution."""
    async with SessionLocal() as db:
        module = await db.get(Module, module_id)
        if module is None:
            raise ExecutionRejectedError("模块不存在或已被删除")
        context = EncryptionContext(
            user_id=await owner_user_id(db),
            module_key=module.key,
            account_index=-1,
        )
        upgraded = False
        if module.params_encrypted and not parameter_cipher.is_v2(
            module.params_encrypted
        ):
            params = parameter_cipher.decrypt(module.params_encrypted, context)
            module.params_encrypted = parameter_cipher.encrypt(params, context)
            upgraded = True
        if module.accounts_encrypted:
            accounts, accounts_upgraded = parameter_cipher.decrypt_accounts(
                module.accounts_encrypted, context
            )
            if accounts_upgraded:
                module.accounts_encrypted = parameter_cipher.encrypt_accounts(
                    accounts, context
                )
                upgraded = True
        if upgraded:
            await db.commit()
        # All fields used after the session closes are loaded.
        return module, context


def _write_execution_header(
    module_name: str, trigger: str, capture: OutputCapture
) -> None:
    trigger_label = {
        TRIGGER_MANUAL: "手动执行",
        TRIGGER_SCHEDULE: "定时执行",
        TRIGGER_TEST: "手动测试",
    }.get(trigger, "执行")
    capture.writeline("=" * 68)
    capture.writeline(f"{module_name}  ·  {trigger_label}")
    capture.writeline(
        f"开始时间：{datetime.now(settings.timezone_info):%Y-%m-%d %H:%M:%S}"
    )
    capture.writeline("=" * 68)


async def _run_one_account(
    *,
    module_key: str,
    module_directory: str | None,
    index: int,
    total: int,
    account: dict[str, object],
    capture: OutputCapture,
) -> tuple[AccountResult, bool]:
    display = str(account.get("display") or "未提供账号标识")
    capture.writeline("-" * 68)
    capture.writeline(
        f"[账号 {index}/{total}] {display} · 开始执行 "
        f"{datetime.now(settings.timezone_info):%H:%M:%S}"
    )
    account_started = time.perf_counter()
    success = False
    message = "执行失败"
    error_text = ""
    runner = None
    cancelled = False
    try:
        runner = load_runner(module_key, module_directory)
        raw_result = await asyncio.wait_for(
            _invoke_run(runner.run, account["params"]),  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            timeout=settings.module_timeout,
        )
        success, message, extra = _normalize_result(raw_result)
        if extra:
            capture.writeline(f"[返回数据] {extra}")
    except asyncio.TimeoutError:
        message = f"账号执行超时（超过 {settings.module_timeout} 秒）"
        error_text = message
        capture.writeline(f"[错误] {message}")
    except asyncio.CancelledError:
        cancelled = True
        message = "执行被取消"
        error_text = message
    except (ModuleConfigError, ParameterDecryptionError) as exc:
        message = str(exc) or exc.__class__.__name__
        error_text = message
        capture.writeline(f"[错误] {message}")
    except ExecutionRejectedError as exc:
        message = str(exc)
        error_text = message
        capture.writeline(f"[错误] {message}")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        error_text = message
        capture.writeline("[异常] 账号执行过程中发生未处理错误：")
        capture.writeline(traceback.format_exc())
    finally:
        if runner is not None:
            unload_runner(runner)
    duration_ms = int((time.perf_counter() - account_started) * 1000)
    if cancelled:
        message = "执行被取消"
    capture.writeline(
        f"[账号 {index}/{total}] {'成功' if success else '失败'} · "
        f"{message}（{duration_ms} ms）"
    )
    return (
        AccountResult(
            index=index,
            account_id=str(account.get("id") or ""),
            display=display,
            success=success,
            message=message,
            duration_ms=duration_ms,
            error=error_text,
        ),
        cancelled,
    )


async def _run_accounts(
    module_key: str,
    module_directory: str | None,
    accounts: list[dict[str, object]],
    capture: OutputCapture,
) -> tuple[list[AccountResult], bool]:
    results: list[AccountResult] = []
    total = len(accounts)
    for index, account in enumerate(accounts, start=1):
        result, cancelled = await _run_one_account(
            module_key=module_key,
            module_directory=module_directory,
            index=index,
            total=total,
            account=account,
            capture=capture,
        )
        results.append(result)
        if cancelled:
            return results, True
        if index < total:
            delay = random.SystemRandom().uniform(
                settings.account_interval_min_seconds,
                settings.account_interval_max_seconds,
            )
            if delay > 0:
                capture.writeline(f"等待 {delay:.0f} 秒后执行下一个账号 …")
                await asyncio.sleep(delay)
    return results, False


def _cancelled_outcome(results: list[AccountResult], total: int) -> ExecutionOutcome:
    return ExecutionOutcome(
        status=STATUS_FAILED,
        message="执行被取消（服务可能正在关闭）",
        cancelled=True,
        total_accounts=total,
        account_results=results,
        success_accounts=sum(1 for item in results if item.success),
        failed_accounts=sum(1 for item in results if not item.success),
    )


async def _perform(
    module_id: int, trigger: str, capture: OutputCapture
) -> ExecutionOutcome:
    module, context = await _load_execution_module(module_id)
    module_key, module_name = module.key, module.name
    module_directory = module.directory_name or module.key
    _write_execution_header(module_name, trigger, capture)
    results: list[AccountResult] = []
    total = 0
    try:
        config = parse_config_file(
            get_module_physical_path(module) / "config.json"
        )
        accounts = _load_accounts(config, module, context)
        sensitive = collect_sensitive_values(
            [spec.model_dump(mode="json") for spec in config.params],
            None,
            accounts,
        )
        with sensitive_values(sensitive), capture_output(capture):
            total = len(accounts)
            if config.multi_account:
                capture.writeline(
                    f"模式：多账号串行（{total} 个），"
                    f"账号间隔 {settings.account_interval_min_seconds}-"
                    f"{settings.account_interval_max_seconds} 秒"
                )
            else:
                capture.writeline(f"模式：单账号 · {accounts[0]['display']}")
            capture.writeline("")
            results, cancelled = await _run_accounts(module_key, module_directory, accounts, capture)
            if cancelled:
                return _cancelled_outcome(results, total)
            status, message, ok_count, failed_count = _aggregate(results)
            capture.writeline("")
            capture.writeline("=" * 68)
            capture.writeline(f"汇总：{message}")
            capture.writeline("=" * 68)
            return ExecutionOutcome(
                status=status,
                message=message,
                total_accounts=total,
                success_accounts=ok_count,
                failed_accounts=failed_count,
                account_results=results,
            )
    except asyncio.CancelledError:
        message = "执行被取消（服务可能正在关闭）"
        capture.writeline(f"\n[错误] {message}")
        return _cancelled_outcome(results, total)
    except (ModuleConfigError, ParameterDecryptionError, ExecutionRejectedError) as exc:
        message = str(exc) or exc.__class__.__name__
        capture.writeline(f"\n[错误] {message}")
        return ExecutionOutcome(
            status=STATUS_FAILED, message=message, account_results=results
        )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        capture.writeline("\n[异常] 模块执行过程中发生未处理错误：")
        capture.writeline(traceback.format_exc())
        return ExecutionOutcome(
            status=STATUS_FAILED, message=message[:4000], account_results=results
        )


def _push_payload(outcome: ExecutionOutcome) -> dict[str, object]:
    total = outcome.total_accounts
    if total > 1:
        event = (
            "success"
            if outcome.failed_accounts == 0
            else ("partial_failure" if outcome.success_accounts > 0 else "failure")
        )
        account = f"{total} 个账号"
    else:
        event = "success" if outcome.status == STATUS_SUCCESS else "failure"
        account = (
            outcome.account_results[0].display if outcome.account_results else "—"
        )
    details_lines = [
        f"- 第 {item.index} 个（{item.display}）："
        f"{'成功' if item.success else '失败'} · {item.message}"
        for item in outcome.account_results
    ]
    failed = [item for item in outcome.account_results if not item.success]
    error = "; ".join(item.error or item.message for item in failed)[:1500]
    status_text = (
        "成功"
        if outcome.status == STATUS_SUCCESS
        else ("部分失败" if outcome.success_accounts > 0 else "失败")
    )
    return {
        "event": event,
        "status_text": status_text,
        "result": outcome.message,
        "account": account,
        "error": error,
        "summary": outcome.message,
        "details": "\n".join(details_lines),
    }


async def _send_execution_notification(
    module_id: int, outcome: ExecutionOutcome, duration_ms: int, trigger: str
) -> None:
    payload = {
        key: redact_text(value) for key, value in _push_payload(outcome).items()
    }
    duration = f"{duration_ms / 1000:.1f} 秒"
    payload["duration"] = duration
    try:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None:
                return
            push_unified = bool(module.push_unified)
            push_independent = bool(module.push_independent)
            legacy_enabled = bool(module.push_enabled)
        if trigger == TRIGGER_TEST:
            payload["result"] = f"[测试推送] {payload['result']}"
            payload["summary"] = f"[测试推送] {payload['summary']}"
            payload["details"] = f"[测试推送]\n{payload['details']}"
            await send_independent_module(module_id, **payload, trigger=trigger)
            return
        if push_unified:
            if push_independent:
                logger.info("模块 %s 同时开启两种推送，统一推送优先", module_id)
            await record_unified_result(
                module_id,
                status=outcome.status,
                message=outcome.message,
                details=payload.get("details", ""),
                trigger=trigger,
            )
            return
        if push_independent or legacy_enabled:
            result = await send_independent_module(
                module_id, **payload, trigger=trigger
            )
            if result.get("sent"):
                logger.info("独立推送已发送（模块 %s）", module_id)
            elif result.get("reason"):
                logger.debug("未发送独立推送：%s", result["reason"])
    except Exception:
        logger.exception("发送执行结果推送失败（模块 %s）", module_id)


async def _execute(
    module_id: int,
    log_id: int,
    started_at: datetime,
    trigger: str,
    module_key: str = "unknown",
) -> None:
    capture = OutputCapture(hub, log_id, settings.log_max_chars, module_key)
    started_perf = time.perf_counter()
    outcome = ExecutionOutcome(STATUS_FAILED, "执行异常终止")
    cancelled = False
    try:
        outcome = await _perform(module_id, trigger, capture)
        cancelled = outcome.cancelled
    except asyncio.CancelledError:
        outcome = ExecutionOutcome(STATUS_FAILED, "执行被取消（服务正在关闭）", True)
        cancelled = True
        capture.writeline(f"\n[错误] {outcome.message}")
    except Exception as exc:
        outcome = ExecutionOutcome(STATUS_FAILED, f"{type(exc).__name__}: {exc}")
        capture.writeline("\n[异常] 执行器发生未处理错误：")
        capture.writeline(traceback.format_exc())
    finally:
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        capture.writeline("\n" + "-" * 68)
        capture.writeline(
            f"结束时间：{datetime.now(settings.timezone_info):%Y-%m-%d %H:%M:%S}  ·  用时 {duration_ms} ms"
        )
        finished_at = utcnow()
        # A ring write can fail while SQLite is under extreme lock pressure.
        # Preserve the in-memory capture as an emergency legacy fallback rather
        # than silently losing the only copy of the execution body.
        fallback_output = (
            redact_text(capture.getvalue()) if capture.ring_failed else ""
        )
        try:
            await _finalize(
                log_id=log_id,
                module_id=module_id,
                status=outcome.status,
                message=outcome.message,
                output=fallback_output,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        except asyncio.CancelledError:
            cancelled = True
            logger.warning("保存执行结果时任务被取消（log_id=%s）", log_id)
        except Exception:
            logger.exception("保存执行结果失败（log_id=%s）", log_id)
        try:
            hub.finish(
                log_id, outcome.status, redact_text(outcome.message), duration_ms
            )
            if not cancelled:
                await _send_execution_notification(
                    module_id, outcome, duration_ms, trigger
                )
        finally:
            lock = _module_locks.get(module_id)
            if lock.locked():
                lock.release()
    if cancelled:
        raise asyncio.CancelledError


async def _finalize(
    log_id: int,
    module_id: int,
    status: str,
    message: str,
    output: str,
    finished_at: datetime,
    duration_ms: int,
) -> str:
    async with SessionLocal() as db:
        log = await db.get(ExecutionLog, log_id)
        module_key = "unknown"
        if log is not None:
            module_key = log.module_key
            log.status = status
            log.message = redact_text(message)
            # Full execution output lives in ring_logs keyed by ref_id.  Only
            # the emergency fallback path above ever writes execution_logs.
            log.output = redact_text(output) if output else None
            log.finished_at = finished_at
            log.duration_ms = duration_ms
        module = await db.get(Module, module_id)
        if module is not None:
            module.last_status = status
            module.last_message = redact_text((message or "")[:2000])
        await db.commit()
        return module_key
