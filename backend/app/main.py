"""FastAPI application entry point and SPA hosting."""

from __future__ import annotations

import logging
import os
import socket
import re
import time
from threading import Lock
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles

from .config import settings
from .module_loader import DatabaseUnavailableError, flush_decay_state_on_shutdown
from .database import SessionLocal, dispose_db, init_db
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from .routers import auth, dashboard, logs, metrics, modules, push, system
from .services.bootstrap import initialize_modules, load_all_modules, seed_admin
from .services.legacy_wash import wash_legacy_admin_credentials
from .services.capture import install_stdout_router
from .services.execution import shutdown_background_tasks
from .services.hub import hub
from .services.maintenance import mark_stale_running_logs, purge_old_logs
from .services.redaction import install_redaction
from .services.ring_log import ring_log
from .services.schedules import mark_stale_running_schedules
from .services.scheduler import scheduler_service
from .services.push_pool import ensure_batch
from .services.push_outbox import drain as drain_push_outbox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
# HTTP client libraries can log request URLs (including push keys / signed URLs).
# Keep their INFO logs out of the captured execution output.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
install_redaction()
logger = logging.getLogger(__name__)


async def patch_schema() -> None:
    from .database import engine

    def _patch(conn):
        inspector = inspect(conn)
        if "users" not in inspector.get_table_names():
            return
        columns = [col["name"] for col in inspector.get_columns("users")]
        if "password_must_change" not in columns:
            logging.info("Patching schema: Adding password_must_change to users")
            conn.execute(text("SAVEPOINT sp_password_must_change"))
            try:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN password_must_change BOOLEAN NOT NULL DEFAULT FALSE"
                ))
                conn.execute(text("RELEASE SAVEPOINT sp_password_must_change"))
            except (OperationalError, ProgrammingError) as exc:
                conn.execute(text("ROLLBACK TO SAVEPOINT sp_password_must_change"))
                conn.execute(text("RELEASE SAVEPOINT sp_password_must_change"))
                message = str(exc).lower()
                if "duplicate column" in message or "already exists" in message:
                    logging.info("Column password_must_change already exists; skipping DDL")
                else:
                    raise

    async with engine.begin() as conn:
        await conn.run_sync(_patch)


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_redaction()
    hub.bind_loop()
    if not settings.cookie_secure:
        logger.info("当前为内网 HTTP 模式，登录 Cookie 未启用 Secure")

    await init_db()
    await patch_schema()
    ring_log.initialize()
    # Install the unified stdout/app-log router only after the ring store has
    # opened its tables.  Every logging handler and print() now has one path.
    install_stdout_router()
    async with SessionLocal() as wash_db:
        await wash_legacy_admin_credentials(wash_db)
    admin_created = await seed_admin()
    await mark_stale_running_logs()
    await mark_stale_running_schedules()

    scheduler_service.start()
    try:
        sync_result = await initialize_modules()
        await ensure_batch()
        await scheduler_service.plan_unified_batch()
        await drain_push_outbox()
        logger.info(
            "模块同步完成：新增 %s，更新 %s，异常 %s",
            sync_result.added,
            sync_result.updated,
            len(sync_result.invalid),
        )
        for key, error in sync_result.invalid:
            logger.warning("模块 %s 异常：%s", key, error)
    except Exception:
        logger.exception("启动时同步模块失败，仍继续启动服务；可在网页端重新扫描")

    try:
        await purge_old_logs()
    except Exception:
        logger.exception("启动时清理过期日志失败")

    all_modules = await load_all_modules()
    scheduled_count = await scheduler_service.reconcile(all_modules)
    logger.info(
        "%s v%s 启动完成 | 模块 %s | 已排程 %s | 时区 %s",
        settings.app_name,
        settings.app_version,
        len(all_modules),
        scheduled_count,
        settings.timezone,
    )
    if admin_created:
        logger.warning(
            "默认管理员账号 %s 已就绪，请登录后立即在「用户设置」中修改账号凭据",
            settings.admin_user,
        )
    try:
        yield
    finally:
        modules.shutdown_icon_decode_pool()
        flush_decay_state_on_shutdown()
        scheduler_service.shutdown()
        await shutdown_background_tasks()
        hub.close_all()
        ring_log.close()
        await dispose_db()
        logger.info("服务已关闭")


app = FastAPI(
    title=f"{settings.app_name} API",
    description="每日自动签到平台：模块热插拔、多账号串行、随机时间调度与实时日志。",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "认证", "description": "登录与账号安全"},
        {"name": "签到模块", "description": "模块安装、账号、随机时间与执行"},
        {"name": "推送通知", "description": "全局推送渠道与消息模板"},
        {"name": "执行日志", "description": "历史记录与 SSE 实时日志"},
        {"name": "仪表盘", "description": "运行统计"},
        {"name": "系统", "description": "健康检查与元信息"},
    ],
)

_DB_LOG_RATE_LIMIT_SECONDS: float = 10.0
_DB_LOG_MAX_EVENT_TYPES: int = 256
_db_log_lock = Lock()
_db_log_last_emit: dict[str, float] = {}
_db_log_suppressed_count: dict[str, int] = {}
_db_log_suppressed_total: int = 0
_db_log_overflow_count: int = 0


def get_db_log_suppression_stats() -> dict[str, int]:
    """Return an atomic snapshot of suppressed DB log counts."""
    now = time.monotonic()

    _cleanup_expired_db_log_types(now)

    with _db_log_lock:
        suppressed_snapshot = dict(_db_log_suppressed_count)
        active_types_count = len(_db_log_last_emit)
        overflow_count = _db_log_overflow_count
        suppressed_total = _db_log_suppressed_total

    return {
        "db_logs_suppressed_total": suppressed_total,
        "db_log_active_event_types": active_types_count,
        "db_log_overflow_count": overflow_count,
    }


def _cleanup_expired_db_log_types(now: float) -> None:
    """Remove event types not seen within the rate-limit window."""
    with _db_log_lock:
        expired = [
            key for key, stamp in _db_log_last_emit.items()
            if now - stamp >= _DB_LOG_RATE_LIMIT_SECONDS
        ]
        for key in expired:
            _evict_event_type(key)


def get_db_log_rate_limiter_snapshot() -> dict[str, int]:
    """Expose rate limiter internal pressure metrics for observability."""
    now = time.monotonic()
    _cleanup_expired_db_log_types(now)
    with _db_log_lock:
        return {
            "db_log_active_event_types": len(_db_log_last_emit),
            "db_log_suppressed_total": _db_log_suppressed_total,
            "db_log_overflow_evictions": _db_log_overflow_count,
        }


def reset_db_log_rate_limits() -> None:
    global _db_log_overflow_count, _db_log_suppressed_total
    with _db_log_lock:
        _db_log_last_emit.clear()
        _db_log_suppressed_count.clear()
        _db_log_overflow_count = 0
        _db_log_suppressed_total = 0


def _evict_event_type(key: str) -> None:
    """Remove an event type from both dicts with desync observability."""
    in_last = key in _db_log_last_emit
    in_supp = key in _db_log_suppressed_count
    if in_last != in_supp:
        logger.error(
            "DB log state desync for key %r: in_last_emit=%s, "
            "in_suppressed=%s. Proceeding with best-effort eviction.",
            key,
            in_last,
            in_supp,
        )
    _db_log_last_emit.pop(key, None)
    _db_log_suppressed_count.pop(key, None)


def _should_emit_db_log(event_type: str) -> bool:
    """Return True when a full DB error log should be emitted."""
    global _db_log_overflow_count, _db_log_suppressed_total
    now = time.monotonic()
    with _db_log_lock:
        # 独立过期清理，不依赖容量是否已满；过期项集中在头部。
        for key in list(_db_log_last_emit.keys()):
            if (
                now - _db_log_last_emit[key]
                >= _DB_LOG_RATE_LIMIT_SECONDS
            ):
                _evict_event_type(key)
            else:
                break

        is_existing = event_type in _db_log_last_emit
        last = _db_log_last_emit.get(event_type, 0.0)
        should_emit = now - last >= _DB_LOG_RATE_LIMIT_SECONDS

        if should_emit:
            if is_existing:
                _db_log_last_emit.pop(event_type, None)
            if len(_db_log_last_emit) >= _DB_LOG_MAX_EVENT_TYPES:
                oldest = next(iter(_db_log_last_emit))
                _db_log_last_emit.pop(oldest, None)
                _db_log_suppressed_count.pop(oldest, None)
                _db_log_overflow_count += 1

            suppressed = _db_log_suppressed_count.pop(event_type, 0)
            if suppressed:
                logger.warning(
                    "Suppressed %d duplicate %s logs in last %.0fs",
                    suppressed,
                    event_type,
                    _DB_LOG_RATE_LIMIT_SECONDS,
                )
            _db_log_last_emit[event_type] = now
            _db_log_suppressed_count[event_type] = 0
            return True

        previous_suppressed = _db_log_suppressed_count.get(event_type, 0)
        if is_existing:
            _evict_event_type(event_type)
        _db_log_last_emit[event_type] = now
        _db_log_suppressed_count[event_type] = previous_suppressed + 1
        _db_log_suppressed_total += 1
        return False


_LOG_FIELD_MAX_LEN: int = 4096


_TRUNCATE_SUFFIX: str = "...[truncated]"


def _safe_log_field(value: object) -> str:
    """Convert to string, truncate safely, then sanitize credentials."""
    text = str(value) if value is not None else ""
    if len(text) > _LOG_FIELD_MAX_LEN:
        truncated = text[:_LOG_FIELD_MAX_LEN]
        last_safe = max(
            truncated.rfind(" "),
            truncated.rfind(","),
            truncated.rfind(";"),
            truncated.rfind("\n"),
        )
        if last_safe > _LOG_FIELD_MAX_LEN // 2:
            truncated = truncated[:last_safe]
        text = truncated + _TRUNCATE_SUFFIX
    return _sanitize_db_error(text)


def _truncate_log_field(
    value: str, max_len: int = _LOG_FIELD_MAX_LEN
) -> str:
    """Truncate log field to prevent oversized log records."""
    if len(value) <= max_len:
        return value
    return value[:max_len] + "...[truncated]"


def _sanitize_db_error(message: str) -> str:
    """Mask passwords in database connection strings before logging."""
    return re.sub(
        r"(?P<scheme>[a-zA-Z0-9+.-]+://[^:@\s]+:)(?P<password>[^:@\s]+)(?P<rest>@)",
        r"\g<scheme>***\g<rest>",
        message,
    )


@app.exception_handler(OperationalError)
async def sqlalchemy_connection_handler(
    request: Request, exc: OperationalError
) -> JSONResponse:
    """Translate connection-level OperationalError to 503; other errors -> 500."""
    orig = getattr(exc, "orig", None)
    message = str(orig).lower() if orig else ""
    is_connection_error = isinstance(
        orig, (socket.timeout, ConnectionError, OSError)
    )
    is_db_shutdown = any(
        token in message
        for token in (
            "server closed the connection",
            "connection refused",
            "no such file or directory",
            "admin shutdown",
        )
    )
    if not (is_connection_error or is_db_shutdown):
        safe_warning_stmt = _safe_log_field(exc.statement)
        if _should_emit_db_log("db_non_connection_error"):
            logger.warning(
                "Non-connection OperationalError re-raised as 500",
                extra={
                    "db_stmt": safe_warning_stmt,
                    "db_orig_type": type(orig).__name__,
                    "event": "db_non_connection_error",
                },
            )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Full DB error traceback (may contain secrets):",
                exc_info=True,
            )
        raise HTTPException(
            status_code=500, detail="Internal Server Error"
        ) from exc
    safe_stmt = _safe_log_field(exc.statement)
    safe_params = _safe_log_field(exc.params)
    if _should_emit_db_log("db_connection_error"):
        logger.error(
            "Database connection failed",
            extra={
                "db_stmt": safe_stmt,
                "db_params": safe_params,
                "db_orig_type": type(orig).__name__,
                "event": "db_connection_error",
            },
            exc_info=False,
        )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Full DB error traceback (may contain secrets):",
            exc_info=True,
        )
    return JSONResponse(
        status_code=503,
        content={"detail": "数据库服务暂时不可用，请稍后重试"},
    )


@app.exception_handler(DatabaseUnavailableError)
async def database_unavailable_handler(
    request: Request, exc: DatabaseUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "数据库连接异常，请稍后重试"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Never let auth/HTTP errors inherit an image or stream content type."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

api = settings.api_prefix.rstrip("/")
app.include_router(auth.router, prefix=api)
app.include_router(modules.public_router, prefix=api)
app.include_router(modules.router, prefix=api)
app.include_router(logs.router, prefix=api)
app.include_router(dashboard.router, prefix=api)
app.include_router(push.router, prefix=api)
app.include_router(system.meta_router, prefix=api)
app.include_router(system.settings_router, prefix=api)
app.include_router(system.system_router, prefix=api)
app.include_router(system.health_router, prefix=api)
app.include_router(metrics.router)


@app.get("/api", include_in_schema=False)
async def api_root() -> JSONResponse:
    return JSONResponse(
        {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": f"{api}/health",
        }
    )


static_dir = settings.static_dir
if static_dir is not None:
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="接口不存在")
        candidate = (static_dir / full_path).resolve()  # type: ignore[operator]  # TODO(v1.0.3): fix typing
        try:
            candidate.relative_to(static_dir)  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
        except ValueError:
            raise HTTPException(status_code=404, detail="文件不存在") from None
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(
            Path(static_dir) / "index.html",  # type: ignore[arg-type]  # TODO(v1.0.3): fix typing
            headers={"Cache-Control": "no-cache"},
        )

else:

    @app.get("/", include_in_schema=False)
    async def frontend_not_built() -> JSONResponse:
        return JSONResponse(
            {
                "message": "后端已启动，但尚未找到前端构建产物。",
                "frontend_dir": str(settings.frontend_dir),
                "docs": "/docs",
                "hint": "开发模式请运行 pnpm dev；生产模式请先构建前端或使用 Docker。",
            }
        )
