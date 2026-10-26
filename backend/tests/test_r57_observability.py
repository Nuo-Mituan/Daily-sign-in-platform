"""Regression tests for R57 pool and rate-limiter state boundaries."""

from __future__ import annotations

import concurrent.futures
import time

import app.module_loader as loader
from app import main


def test_pool_metrics_reregister_after_pool_recreation(monkeypatch) -> None:
    calls = {"count": 0}

    def register() -> None:
        calls["count"] += 1

    monkeypatch.setattr(loader, "_POOL_EVENTS_FULLY_REGISTERED", True)
    monkeypatch.setattr(loader, "_REGISTERED_POOL_ID", -1)
    monkeypatch.setattr(loader, "_POOL_EVENTS_LAST_ATTEMPT", 0.0)
    monkeypatch.setattr(loader, "_register_pool_events", register)

    loader.get_pool_metrics_snapshot()

    assert calls["count"] == 1


def test_active_event_types_decays_without_new_errors() -> None:
    main.reset_db_log_rate_limits()
    old = time.monotonic() - 1000.0
    main._db_log_last_emit["stale"] = old
    main._db_log_suppressed_count["stale"] = 0

    snapshot = main.get_db_log_rate_limiter_snapshot()

    assert snapshot["db_log_active_event_types"] == 0
    assert "stale" not in main._db_log_last_emit
    assert "stale" not in main._db_log_suppressed_count


def test_pool_cache_reset_is_atomic_under_concurrency() -> None:
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(100):
                loader._reset_pool_metrics()
                loader._get_pool_instant_metrics()
        except BaseException as exc:  # noqa: BLE001 - captured for assertion
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(8)))

    assert not errors
    assert loader._get_pool_instant_metrics()
