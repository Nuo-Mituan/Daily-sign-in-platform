"""Micro-benchmarks for contract-guarded hot paths."""

from __future__ import annotations

import itertools

import pytest

from app import main
from app.module_loader import get_pool_metrics_snapshot


@pytest.mark.benchmark
def test_bench_db_log_rate_limiter_emit(benchmark) -> None:
    main.reset_db_log_rate_limits()
    counter = itertools.count()
    result = benchmark(
        lambda: main._should_emit_db_log(f"evt_{next(counter)}")
    )
    assert result is True
    assert benchmark.stats.stats.mean < 10e-6


@pytest.mark.benchmark
def test_bench_db_log_rate_limiter_suppress(benchmark) -> None:
    main.reset_db_log_rate_limits()
    main._should_emit_db_log("hot")
    result = benchmark(lambda: main._should_emit_db_log("hot"))
    assert result is False
    assert benchmark.stats.stats.mean < 10e-6


@pytest.mark.benchmark
def test_bench_pool_metrics_snapshot(benchmark) -> None:
    snapshot = benchmark(get_pool_metrics_snapshot)
    assert set(snapshot) == frozenset({
        "pool_connect", "pool_checkout", "pool_checkin",
        "pool_disconnect", "pool_error", "pool_invalidate",
    })
    assert benchmark.stats.stats.mean < 10e-6
