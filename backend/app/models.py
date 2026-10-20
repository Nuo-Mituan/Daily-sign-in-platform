"""SQLAlchemy ORM models and shared column types."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .timeutils import utcnow


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Always bind naive UTC and always return timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )


class AuthSession(Base):
    """Server-side whitelist entry for a signed browser session cookie."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_renewed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    icon: Mapped[str] = mapped_column(String(16), default="🧩")

    # Legacy Cron columns kept for database/backward compatibility. New scheduling
    # uses start_time / end_time / repeat_cycle below.
    default_cron: Mapped[str] = mapped_column(String(100), default="0 8 * * *")
    cron: Mapped[str] = mapped_column(String(100), default="0 8 * * *")

    default_start_time: Mapped[str] = mapped_column(String(5), default="08:00")
    default_end_time: Mapped[str] = mapped_column(String(5), default="10:00")
    default_repeat_cycle: Mapped[str] = mapped_column(String(20), default="daily")
    default_repeat_sub_value: Mapped[str] = mapped_column(String(10), default="")
    start_time: Mapped[str] = mapped_column(String(5), default="08:00")
    end_time: Mapped[str] = mapped_column(String(5), default="10:00")
    repeat_cycle: Mapped[str] = mapped_column(String(20), default="daily")
    repeat_sub_value: Mapped[str] = mapped_column(String(10), default="")

    multi_account: Mapped[bool] = mapped_column(Boolean, default=False)
    # Legacy aggregate kept in sync by the API for older clients.
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Independent = push this run immediately; unified = contribute to the
    # daily batch.  When both are true the unified batch wins.
    # Nullable only for v5 ALTER TABLE compatibility; the migration fills NULL
    # with push_enabled / false and the API always writes booleans.
    push_independent: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    push_unified: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    param_schema: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    params_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    accounts_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    load_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )

    executions: Mapped[list["ExecutionLog"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    schedules: Mapped[list["ModuleSchedule"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    __table_args__ = (
        Index("ix_execution_logs_module_started", "module_id", "started_at"),
        Index("ix_execution_logs_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(80), index=True)
    module_name: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[str] = mapped_column("trigger_type", String(16), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deprecated in rc.2: new output lives in ring_logs (ref_id=ExecutionLog.id).
    # Kept nullable for v5 read-only fallback; removal is a v2.0 migration.
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    module: Mapped[Module] = relationship(back_populates="executions")


STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULE = "schedule"


class ModuleSchedule(Base):
    """One generated random execution time for one recurrence period."""

    __tablename__ = "module_schedules"
    __table_args__ = (
        UniqueConstraint("module_id", "period_start", name="uq_module_schedule_period"),
        Index("ix_module_schedules_module_period", "module_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    source: Mapped[str] = mapped_column(String(16), default="auto")
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    module: Mapped[Module] = relationship(back_populates="schedules")


class PushConfig(Base):
    """Singleton global push-notification configuration."""

    __tablename__ = "push_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    channel: Mapped[str] = mapped_column(String(20), default="none")
    config_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_template: Mapped[str] = mapped_column(Text, default="")
    body_template: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )


class RingLog(Base):
    """Unified append-only ring-buffer record.

    ``seq`` is allocated by :mod:`app.services.ring_log` from a persisted
    counter, not by the database autoincrement.  ``created_at`` is stored in the
    configured application timezone; ``created_at_epoch`` is only used for
    retention comparisons.  Reads always order by ``seq``.
    """

    __tablename__ = "ring_logs"
    __table_args__ = (
        Index("ix_ring_logs_scope_seq", "scope_type", "scope_key", "seq"),
        Index("ix_ring_logs_ref_seq", "ref_type", "ref_id", "seq"),
        Index("ix_ring_logs_created_epoch", "created_at_epoch"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    scope_type: Mapped[str] = mapped_column(String(16), index=True)
    scope_key: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(24), default="app")
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    text: Mapped[str] = mapped_column(Text, default="")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default="")
    created_at_epoch: Mapped[int] = mapped_column(Integer, default=0, index=True)
    ref_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RingState(Base):
    """Singleton counter that guarantees monotonic ``seq`` across restarts."""

    __tablename__ = "ring_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_seq: Mapped[int] = mapped_column(Integer, default=1)


class AppSetting(Base):
    """Runtime-tunable settings persisted independently of the environment."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )



class PushPool(Base):
    """One terminal result per module per business cycle.

    The textual details are deleted immediately after the batch is flushed;
    the durable summary lives in :class:`PushBatch` and :class:`PushRecord`.
    """

    __tablename__ = "push_pool"
    __table_args__ = (
        UniqueConstraint("cycle_id", "module_id", name="uq_push_pool_cycle_module"),
        Index("ix_push_pool_cycle_status", "cycle_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(10), index=True)
    module_id: Mapped[int] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(80))
    module_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )


class PushBatch(Base):
    __tablename__ = "push_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(120), unique=True, index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    expected_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_cleared: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    flushed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PushRecord(Base):
    __tablename__ = "push_records"
    __table_args__ = (
        Index("ix_push_records_kind_created", "kind", "created_at"),
        Index("ix_push_records_cycle", "cycle_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), default="independent", index=True)
    channel: Mapped[str] = mapped_column(String(40), default="none")
    module_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    module_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    module_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(160), unique=True, index=True, nullable=True
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("push_batches.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="failed", index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)



class PushOutbox(Base):
    """Transactional audit outbox for push events.

    The row is inserted in the same local transaction as the business state
    change, then drained to the ring-buffer audit log.  A crash between the
    transaction and the drain leaves a pending row for the next startup/sweep.
    """

    __tablename__ = "push_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(160), unique=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), default="audit")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
