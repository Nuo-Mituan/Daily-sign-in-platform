"""Property-based tests for connection pool metric contracts."""

from __future__ import annotations

import concurrent.futures

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import app.module_loader as loader


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.dictionaries(st.text(), st.integers()))
@pytest.mark.property
def test_pool_snapshot_keys_strict_contract(monkeypatch, dirty) -> None:
    """ADR-INVARIANT: pool-snapshot-strict-contract

    Verifies snapshots expose exactly POOL_METRIC_KEYS with int values.
    """
    monkeypatch.setattr(loader, "_POOL_EVENT_COUNTERS", dict(dirty))
    snapshot = loader.get_pool_metrics_snapshot()
    assert set(snapshot) == loader.POOL_METRIC_KEYS
    assert all(isinstance(value, int) for value in snapshot.values())


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.integers(min_value=100, max_value=500))
@pytest.mark.property
def test_pool_counter_thread_safety(monkeypatch, calls_per_thread) -> None:
    """ADR-INVARIANT: pool-counter-atomicity

    Verifies locked checkout counters are exact under concurrency.
    """
    monkeypatch.setattr(loader, "_is_current_pool", lambda record: True)
    with loader._POOL_EVENT_LOCK:
        loader._POOL_EVENT_COUNTERS["checkout"] = 0

    def worker() -> None:
        for _ in range(calls_per_thread):
            loader._on_checkout()

    threads = 10
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=threads
    ) as pool:
        list(pool.map(lambda _: worker(), range(threads)))

    snapshot = loader.get_pool_metrics_snapshot()
    assert snapshot["pool_checkout"] == threads * calls_per_thread
