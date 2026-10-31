"""Application configuration, loaded from environment variables / .env."""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- basics
    app_name: str = "签到云台"
    app_version: str = "1.0.6"
    api_prefix: str = "/api"
    timezone: str = "Asia/Shanghai"

    # ------------------------------------------------------------ filesystem
    data_dir: Path = PROJECT_ROOT / "data"
    modules_dir: Path = PROJECT_ROOT / "modules"
    logs_dir: Path = PROJECT_ROOT / "logs"
    frontend_dir: Path = PROJECT_ROOT / "frontend" / "dist"
    database_url: str | None = None

    # ---------------------------------------------------------------- auth
    secret_key: str | None = None
    admin_user: str = "admin"
    admin_pass: str = ""

    # ---------------------------------------------------------- cookie auth
    cookie_name: str = "checkin_session"
    cookie_secure: bool = False
    cookie_max_age_seconds: int = 604_800  # 7 days
    session_renew_interval_seconds: int = 300
    csrf_enabled: bool = True

    # ------------------------------------------------------------ execution
    module_timeout: int = 300
    account_interval_min_seconds: int = 120
    account_interval_max_seconds: int = 300
    schedule_min_lead_seconds: int = 5
    log_retention_days: int = 31
    log_max_chars: int = 512_000
    # Ring-buffer quotas.  Modules get their own independent quota in addition
    # to these system/push and global limits.
    ring_log_max_rows: int = 200_000
    ring_log_max_bytes: int = 128 * 1024 * 1024
    ring_system_max_rows: int = 50_000
    ring_system_max_bytes: int = 32 * 1024 * 1024
    ring_module_max_rows: int = 20_000
    ring_module_max_bytes: int = 16 * 1024 * 1024
    ring_push_max_rows: int = 50_000
    ring_push_max_bytes: int = 32 * 1024 * 1024
    ring_trim_batch_size: int = 1_000
    ring_queue_max: int = 10_000
    ring_busy_timeout_seconds: float = 15.0
    ring_write_retries: int = 6
    ring_trim_max_loops: int = 10_000
    sse_keepalive_seconds: int = 15
    sse_queue_max: int = 2_000
    upload_max_mb: int = 10

    # --------------------------------------------------------------- push
    push_skip_notice: bool = True
    push_after_flush_mode: str = "single"
    push_retry_attempts: int = 3
    push_retry_base_seconds: float = 1.0
    push_http_timeout_seconds: float = 10.0
    push_connect_timeout_seconds: float = 5.0
    push_request_retry_seconds: float = 0.8
    push_response_max_chars: int = 4000
    push_driver_max_versions: int = 5

    # --------------------------------------------------------------- network
    cors_origins: str = ""
    trust_proxy_headers: bool = True

    def prepare(self) -> None:
        """Create runtime directories and resolve a persistent secret key."""
        # New DB/WAL/log/secret files must not be world-readable.
        os.umask(0o077)
        self.data_dir = self.data_dir.expanduser().resolve()
        self.modules_dir = self.modules_dir.expanduser().resolve()
        self.logs_dir = self.logs_dir.expanduser().resolve()
        self.frontend_dir = self.frontend_dir.expanduser().resolve()

        for directory in (
            self.data_dir,
            self.modules_dir,
            self.logs_dir,
            self.logs_dir / "executions",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        # Sensitive runtime state must not be world-readable on a shared host.
        for private_dir in (self.data_dir, self.logs_dir):
            try:
                private_dir.chmod(0o700)
            except OSError:  # pragma: no cover - non-POSIX filesystems
                pass

        if self.secret_key and self.secret_key.strip():
            self.secret_key = self.secret_key.strip()
        else:
            key_file = self.data_dir / ".secret_key"
            if key_file.exists():
                self.secret_key = key_file.read_text(encoding="utf-8").strip()
            if not self.secret_key:
                self.secret_key = secrets.token_urlsafe(48)
                key_file.write_text(self.secret_key, encoding="utf-8")
                try:
                    key_file.chmod(0o600)
                except OSError:  # pragma: no cover - non-POSIX filesystems
                    pass
                logger.warning(
                    "SECRET_KEY 未配置，已在 %s 生成持久化密钥。请勿删除该文件，"
                    "否则已保存的模块参数将无法解密。",
                    key_file,
                )

        self.cookie_max_age_seconds = max(3600, int(self.cookie_max_age_seconds))
        self.session_renew_interval_seconds = max(
            0, int(self.session_renew_interval_seconds)
        )
        self.module_timeout = max(10, int(self.module_timeout))
        self.account_interval_min_seconds = max(
            0, int(self.account_interval_min_seconds)
        )
        self.account_interval_max_seconds = max(
            self.account_interval_min_seconds,
            int(self.account_interval_max_seconds),
        )
        self.schedule_min_lead_seconds = max(0, int(self.schedule_min_lead_seconds))
        self.log_retention_days = min(365, max(1, int(self.log_retention_days)))
        self.log_max_chars = max(16_000, int(self.log_max_chars))
        for name in (
            "ring_log_max_rows",
            "ring_log_max_bytes",
            "ring_system_max_rows",
            "ring_system_max_bytes",
            "ring_module_max_rows",
            "ring_module_max_bytes",
            "ring_push_max_rows",
            "ring_push_max_bytes",
            "ring_trim_batch_size",
            "ring_queue_max",
            "ring_trim_max_loops",
            "sse_queue_max",
        ):
            setattr(self, name, max(10, int(getattr(self, name))))
        self.ring_write_retries = max(1, min(20, int(self.ring_write_retries)))
        self.ring_busy_timeout_seconds = max(
            1.0, min(120.0, float(self.ring_busy_timeout_seconds))
        )
        self.sse_keepalive_seconds = max(5, min(120, int(self.sse_keepalive_seconds)))
        self.upload_max_mb = max(1, int(self.upload_max_mb))
        self.push_retry_attempts = max(0, min(10, int(self.push_retry_attempts)))
        self.push_retry_base_seconds = max(
            0.0, min(30.0, float(self.push_retry_base_seconds))
        )
        self.push_http_timeout_seconds = max(
            1.0, min(120.0, float(self.push_http_timeout_seconds))
        )
        self.push_connect_timeout_seconds = max(
            0.5, min(60.0, float(self.push_connect_timeout_seconds))
        )
        self.push_request_retry_seconds = max(
            0.0, min(30.0, float(self.push_request_retry_seconds))
        )
        self.push_response_max_chars = max(200, int(self.push_response_max_chars))
        self.push_driver_max_versions = max(1, int(self.push_driver_max_versions))
        mode = str(self.push_after_flush_mode or "single").strip().lower()
        if mode not in {"single", "none"}:
            mode = "single"
        self.push_after_flush_mode = mode

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'checkin.db').as_posix()}"

    @property
    def timezone_info(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("时区 %s 无效，已回退到 UTC", self.timezone)
            return ZoneInfo("UTC")

    @property
    def static_dir(self) -> Path | None:
        if (self.frontend_dir / "index.html").is_file():
            return self.frontend_dir
        return None

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    instance = Settings()
    instance.prepare()
    return instance


settings = get_settings()
