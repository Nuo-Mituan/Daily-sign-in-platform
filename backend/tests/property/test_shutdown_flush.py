"""Property-based test for shutdown flush idempotency."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st
import pytest

import app.module_loader as loader


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.integers(min_value=1, max_value=10))
@pytest.mark.property
def test_flush_idempotency_under_retry(monkeypatch, retries) -> None:
    """ADR-INVARIANT: shutdown-flush-idempotency

    Verifies repeated shutdown flushes invoke the writer exactly once.
    """
    calls = {"count": 0}
    monkeypatch.setattr(
        loader,
        "_save_decay_state",
        lambda: calls.__setitem__("count", calls["count"] + 1),
    )
    monkeypatch.setattr(loader, "_DECAY_FLUSH_IN_PROGRESS", False)

    for _ in range(retries):
        loader.flush_decay_state_on_shutdown()

    assert calls["count"] == 1
