"""Public Prometheus text-format metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()

PROMETHEUS_METRIC_NAMES = frozenset({
    "db_log_active_event_types",
    "db_log_suppressed_total",
    "db_log_overflow_evictions_total",
})


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    from ..main import get_db_log_rate_limiter_snapshot

    snapshot = get_db_log_rate_limiter_snapshot()
    lines = [
        "# HELP db_log_active_event_types Active event types in rate limiter",
        "# TYPE db_log_active_event_types gauge",
        f"db_log_active_event_types {snapshot['db_log_active_event_types']}",
        "# HELP db_log_suppressed_total Total suppressed DB log events",
        "# TYPE db_log_suppressed_total counter",
        f"db_log_suppressed_total {snapshot['db_log_suppressed_total']}",
        "# HELP db_log_overflow_evictions_total Total capacity overflow evictions",
        "# TYPE db_log_overflow_evictions_total counter",
        f"db_log_overflow_evictions_total {snapshot['db_log_overflow_evictions']}",
    ]
    return "\n".join(lines) + "\n"
