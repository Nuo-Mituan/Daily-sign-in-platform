"""Validate that alert rules only reference exposed metrics."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.main import get_db_log_rate_limiter_snapshot
from app.routers.metrics import PROMETHEUS_METRIC_NAMES


ALERT_FILE = (
    Path(__file__).resolve().parents[1]
    / "observability"
    / "alerts"
    / "db_log_rate_limiter.yml"
)


def test_alert_rules_reference_valid_metrics() -> None:
    data = yaml.safe_load(ALERT_FILE.read_text(encoding="utf-8"))
    expressions = [
        rule["expr"]
        for group in data["groups"]
        for rule in group["rules"]
    ]
    referenced = {
        metric
        for expr in expressions
        for metric in re.findall(r"\bdb_log_[a-z_]+\b", str(expr))
    }
    exposed = set(PROMETHEUS_METRIC_NAMES)
    assert referenced
    assert referenced <= exposed, {
        "missing_metrics": sorted(referenced - exposed)
    }


@pytest.mark.asyncio
async def test_runtime_metrics_exposes_pool_and_stripe_fields() -> None:
    from app.database import init_db
    from app.routers.system import runtime_metrics

    await init_db()
    result = await runtime_metrics()

    assert result.pool_metrics
    assert result.stripe_contention
    assert "pool_checkout" in result.pool_metrics
    assert "pool_utilization" in result.stripe_contention


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint_format() -> None:
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "db_log_suppressed_total" in response.text
    assert "db_log_overflow_evictions_total" in response.text


def test_pool_snapshot_lazy_registration_retry(monkeypatch) -> None:
    import app.module_loader as loader

    monkeypatch.setattr(loader, "_POOL_EVENTS_FULLY_REGISTERED", False)
    monkeypatch.setattr(loader, "_POOL_EVENTS_LAST_ATTEMPT", 0.0)
    calls = {"count": 0}

    def retry() -> None:
        calls["count"] += 1
        loader._POOL_EVENTS_FULLY_REGISTERED = True

    monkeypatch.setattr(loader, "_register_pool_events", retry)

    loader.get_pool_metrics_snapshot()

    assert calls["count"] == 1
