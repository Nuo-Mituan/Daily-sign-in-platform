"""Property-based tests for the DB log rate limiter invariants."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
import pytest

from app import main


EVENT_TYPES = ["login", "timeout", "checkout", "db", "push"]


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(
    st.tuples(
        st.sampled_from(EVENT_TYPES),
        st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    ),
    max_size=40,
))
@pytest.mark.property
def test_db_log_invariants_under_random_load(monkeypatch, operations) -> None:
    """ADR-INVARIANT: db-log-lru-and-capacity

    Verifies LRU timestamp monotonicity and hard capacity bounds.
    """
    clock = [0.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    main.reset_db_log_rate_limits()

    for event_type, advance in operations:
        clock[0] += advance
        main._should_emit_db_log(event_type)

    # Invariant: suppressed types are a subset of tracked LRU types.
    assert set(main._db_log_suppressed_count) <= set(
        main._db_log_last_emit
    )
    for event_type in main._db_log_suppressed_count:
        assert event_type in main._db_log_last_emit

    # Invariant: hard capacity limit.
    assert len(main._db_log_last_emit) <= main._DB_LOG_MAX_EVENT_TYPES

    # Invariant: LRU dict timestamp order is non-decreasing.
    timestamps = list(main._db_log_last_emit.values())
    assert timestamps == sorted(timestamps)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.sampled_from(EVENT_TYPES), max_size=30))
@pytest.mark.property
def test_db_log_key_set_equality_design_invariant(monkeypatch, events) -> None:
    """ADR-INVARIANT: db-log-key-set-equality

    Verifies last_emit and suppressed_count key sets stay identical.
    """
    clock = [0.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    main.reset_db_log_rate_limits()
    for event in events:
        clock[0] += 1.0
        main._should_emit_db_log(event)
    assert set(main._db_log_last_emit) == set(
        main._db_log_suppressed_count
    )
