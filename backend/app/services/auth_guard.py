"""In-process guards for sensitive account changes.

A single admin instance makes an in-memory limiter sufficient. Multi-replica
deployments should additionally rate-limit at the reverse proxy.
"""

from __future__ import annotations

from .lock_registry import KeyLockRegistry

import asyncio
import time
from collections import deque


class AttemptLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[int, deque[float]] = {}

    def _recent(self, user_id: int, now: float) -> deque[float]:
        bucket = self._attempts.setdefault(user_id, deque())
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def retry_after(self, user_id: int) -> int:
        now = time.monotonic()
        bucket = self._recent(user_id, now)
        if len(bucket) < self.max_attempts:
            return 0
        wait = int(self.window_seconds - (now - bucket[0])) + 1
        return max(1, wait)

    def record_failure(self, user_id: int) -> None:
        now = time.monotonic()
        bucket = self._recent(user_id, now)
        bucket.append(now)

    def reset(self, user_id: int) -> None:
        self._attempts.pop(user_id, None)


_sensitive_locks = KeyLockRegistry[int](max_unlocked=64)
sensitive_limiter = AttemptLimiter(max_attempts=5, window_seconds=300)


def lock_for_user(user_id: int) -> asyncio.Lock:
    return _sensitive_locks.get(user_id)
