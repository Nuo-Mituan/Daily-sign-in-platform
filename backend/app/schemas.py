"""Pydantic request / response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    developer_mode_enabled: bool = False
    created_at: datetime


class LoginResponse(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime
    force_change_password: bool = False


class SessionResponse(LoginResponse):
    pass


class DeveloperModeOut(BaseModel):
    enabled: bool


class DeveloperModeUpdate(BaseModel):
    enabled: bool


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class UsernameUpdateRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_username: str = Field(min_length=3, max_length=64)


class MessageResponse(BaseModel):
    message: str


class AccountOut(BaseModel):
    id: str
    label: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class AccountInput(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class ModuleOut(BaseModel):
    id: int
    key: str
    name: str
    description: str
    author: str
    version: str
    icon: str
    icon_source: str = "url"
    icon_data: str | None = None

    start_time: str
    end_time: str
    repeat_cycle: str
    repeat_sub_value: str = ""
    default_start_time: str
    default_end_time: str
    default_repeat_cycle: str
    default_repeat_sub_value: str = ""

    enabled: bool
    push_enabled: bool = False
    push_independent: bool = False
    push_unified: bool = False
    multi_account: bool = False
    load_error: str | None = None

    last_run_at: datetime | None = None
    last_status: str | None = None
    last_message: str | None = None

    current_schedule_at: datetime | None = None
    schedule_period_start: date | None = None
    schedule_status: str | None = None
    schedule_source: str | None = None
    schedule_fallback_used: bool = False
    schedule_note: str | None = None

    has_params: bool = False
    param_count: int = 0
    account_count: int = 0

    created_at: datetime
    updated_at: datetime


class ModuleDetail(ModuleOut):
    param_schema: list[dict[str, Any]] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    accounts: list[AccountOut] = Field(default_factory=list)


class RevealSensitiveRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)


class RevealSensitiveResponse(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    accounts: list[AccountOut] = Field(default_factory=list)


class ModuleUpdateRequest(BaseModel):
    start_time: str | None = Field(default=None, max_length=5)
    end_time: str | None = Field(default=None, max_length=5)
    repeat_cycle: str | None = Field(default=None, max_length=20)
    repeat_sub_value: str | None = Field(default=None, max_length=10)
    push_enabled: bool | None = None
    push_independent: bool | None = None
    push_unified: bool | None = None
    enabled: bool | None = None
    params: dict[str, Any] | None = None
    accounts: list[AccountInput] | None = None


class ToggleRequest(BaseModel):
    enabled: bool


class SchedulePreviewRequest(BaseModel):
    start_time: str = Field(max_length=5)
    end_time: str = Field(max_length=5)
    repeat_cycle: str = Field(max_length=20)
    repeat_sub_value: str | None = Field(default=None, max_length=10)


class SchedulePreviewResponse(BaseModel):
    start_time: str
    end_time: str
    repeat_cycle: str
    repeat_sub_value: str
    label: str
    next_occurrence: date | None = None


class ScheduleOut(BaseModel):
    id: int
    period_start: date
    scheduled_at: datetime
    status: str
    source: str
    fallback_used: bool = False
    generated_at: datetime
    executed_at: datetime | None = None
    note: str | None = None


class RegenerateScheduleResponse(BaseModel):
    message: str
    schedule: ScheduleOut
    module: ModuleOut


class RunResponse(BaseModel):
    log_id: int
    status: str = "running"
    message: str = "任务已开始执行"


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module_id: int
    module_key: str
    module_name: str
    trigger: str
    status: str
    message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None


class LogDetail(LogOut):
    output: str | None = None
    last_seq: int = 0


class LogPage(BaseModel):
    items: list[LogOut]
    total: int
    page: int
    page_size: int
    pages: int


class DashboardStats(BaseModel):
    total_modules: int
    enabled_modules: int
    today_runs: int
    today_success: int
    today_failed: int
    today_running: int
    success_rate: float
    running_modules: int


class DashboardOut(BaseModel):
    stats: DashboardStats
    recent: list[LogOut]


class ScanError(BaseModel):
    key: str
    error: str


class ScanResponse(BaseModel):
    added: int
    updated: int
    total: int
    invalid: list[ScanError] = Field(default_factory=list)
    message: str


class UploadResponse(BaseModel):
    message: str
    module: ModuleOut


class PushConfigUpdate(BaseModel):
    channel: str = Field(default="none", max_length=40)
    config: dict[str, Any] = Field(default_factory=dict)
    title_template: str = Field(default="", max_length=300)
    body_template: str = Field(default="", max_length=8000)


class DriverRollbackRequest(BaseModel):
    version: str | None = Field(default=None, max_length=40)


class PushUnifiedSettingsOut(BaseModel):
    timeout_enabled: bool
    timeout_time: str


class PushUnifiedSettingsUpdate(BaseModel):
    timeout_enabled: bool
    timeout_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class PushConfigOut(BaseModel):
    channel: str
    config: dict[str, Any] = Field(default_factory=dict)
    title_template: str
    body_template: str
    updated_at: datetime | None = None
    available_variables: list[str] = Field(default_factory=list)
    channels: list[dict[str, Any]] = Field(default_factory=list)
    default_title_template: str = ""
    default_body_template: str = ""


class PushRevealResponse(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class PushTestResponse(BaseModel):
    success: bool
    sent: bool
    channel: str
    message: str
    response: str | None = None


class LogSettingsOut(BaseModel):
    retention_days: int
    min_days: int = 1
    max_days: int = 365
    total_rows: int = 0
    total_bytes: int = 0


class LogSettingsUpdate(BaseModel):
    retention_days: int = Field(ge=1, le=365)


class LogSettingsUpdateOut(LogSettingsOut):
    removed_ring: int = 0
    removed_history: int = 0
    removed_files: int = 0
    message: str


class MetaOut(BaseModel):
    app_name: str
    version: str
    timezone: str
    module_timeout: int
    account_interval_min_seconds: int
    account_interval_max_seconds: int
    log_retention_days: int
    repeat_cycles: list[dict[str, str]]
    modules_dir: str


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    scheduler_running: bool
    time: datetime



class PushRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    channel: str
    module_id: int | None = None
    module_key: str | None = None
    module_name: str | None = None
    cycle_id: str | None = None
    batch_id: int | None = None
    status: str
    title: str | None = None
    body: str | None = None
    response: str | None = None
    error: str | None = None
    created_at: datetime


class PushRecordPage(BaseModel):
    items: list[PushRecordOut]
    total: int
    page: int
    page_size: int
    pages: int


class PushBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cycle_id: str
    status: str
    expected_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    pending_count: int
    timeout_count: int = 0
    summary: str | None = None
    error: str | None = None
    details_cleared: bool = False
    retry_count: int = 0
    created_at: datetime
    trigger_at: datetime | None = None
    timeout_at: datetime | None = None
    timeout_attempted_at: datetime | None = None
    last_attempt_at: datetime | None = None
    flushed_at: datetime | None = None


class PushBatchPage(BaseModel):
    items: list[PushBatchOut]
    total: int
    page: int
    page_size: int
    pages: int



class SystemLogOut(BaseModel):
    seq: int
    scope_type: str
    scope_key: str
    category: str
    level: str
    text: str
    created_at: str


class SystemLogPage(BaseModel):
    items: list[SystemLogOut]
    total: int
    page: int
    page_size: int
    pages: int


class RuntimeMetricsOut(BaseModel):
    ring: dict[str, object]
    sse: dict[str, object]
    push_outbox_pending: int
