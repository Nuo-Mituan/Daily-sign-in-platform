"""In-process guards for sensitive account changes.

A single admin instance makes an in-memory limiter sufficient. Multi-replica
deployments should additionally rate-limit at the reverse proxy.
"""

from __future__ import annotations

from .lock_registry import KeyLockRegistry

import asyncio
import time
from collections import deque
import logging
import os

try:
    import redis.asyncio as aioredis  # type: ignore[import-untyped]
except ImportError:
    aioredis = None
    logging.warning("redis package not installed; login rate limiter uses local memory")

logger = logging.getLogger(__name__)


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

# Login-specific limiters: known users are keyed by user id; unknown users
# fall back to the client IP.  Separate buckets prevent one dimension from
# masking the other.


class AsyncAttemptLimiter:
    """Async limiter protocol implemented by Redis and memory backends."""

    async def retry_after(self, key: int) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    async def record_failure(self, key: int) -> None:  # pragma: no cover
        raise NotImplementedError

    async def reset(self, key: int) -> None:  # pragma: no cover
        raise NotImplementedError


class LoginAttemptLimiter(AsyncAttemptLimiter):
    """Login limiter with async Redis counters and local-memory fallback."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300,
                 redis_url: str | None = None, key_prefix: str = "user") -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._prefix = f"login:{key_prefix}"
        self._attempts: dict[int, deque[float]] = {}
        self._fail_counts: dict[int, int] = {}
        self._fail_last: dict[int, float] = {}
        self._redis = None
        url = redis_url or os.getenv("REDIS_URL")
        if aioredis is not None and url:
            try:
                self._redis = aioredis.from_url(
                    url, decode_responses=True,
                    socket_connect_timeout=0.5, socket_timeout=0.5,
                )
                logger.info("Login rate limiter initialized with Redis")
            except Exception as exc:
                logger.warning("Redis unavailable (%s); using local memory", exc)
                self._redis = None
        if self._redis is None:
            logger.warning(
                "WARNING: Login rate limiter running in local-memory mode. "
                "Not suitable for multi-worker deployments."
            )

    def _key(self, key: int) -> str:
        return f"{self._prefix}:{key}"

    def _active_count(self, key: int) -> int:
        last = self._fail_last.get(key)
        if last is not None and time.monotonic() - last > self.window_seconds * 2:
            self._fail_counts.pop(key, None)
            self._fail_last.pop(key, None)
            return 0
        return self._fail_counts.get(key, 0)

    def _window(self, key: int) -> int:
        count = self._active_count(key)
        if count >= 10:
            return 1200
        if count >= 5:
            return 600
        return 300

    async def retry_after(self, key: int) -> int:
        if self._redis is not None:
            try:
                raw = await self._redis.get(self._key(key))
                if raw is not None and int(raw) >= self.max_attempts:
                    ttl = int(await self._redis.ttl(self._key(key)) or 0)
                    return max(1, ttl, self._window(key))
            except Exception as exc:
                logger.warning("Redis retry_after failed: %s", exc)
        now = time.monotonic()
        bucket = self._attempts.setdefault(key, deque())
        while bucket and bucket[0] < now - self.window_seconds:
            bucket.popleft()
        if len(bucket) < self.max_attempts:
            return 0
        wait = int(self.window_seconds - (now - bucket[0])) + 1
        return max(1, wait, self._window(key))

    async def record_failure(self, key: int) -> None:
        now = time.monotonic()
        self._attempts.setdefault(key, deque()).append(now)
        self._fail_counts[key] = self._active_count(key) + 1
        self._fail_last[key] = now
        if self._redis is not None:
            try:
                redis_key = self._key(key)
                count = int(await self._redis.incr(redis_key))
                ttl = 300 if count <= 5 else 600 if count <= 10 else 1200
                await self._redis.expire(redis_key, ttl)
            except Exception as exc:
                logger.warning("Redis record_failure failed: %s", exc)

    async def reset(self, key: int) -> None:
        self._attempts.pop(key, None)
        self._fail_counts.pop(key, None)
        self._fail_last.pop(key, None)
        if self._redis is not None:
            try:
                await self._redis.delete(self._key(key))
            except Exception:
                pass

login_user_limiter = LoginAttemptLimiter(max_attempts=5, window_seconds=300, key_prefix="user")
login_ip_limiter = LoginAttemptLimiter(max_attempts=10, window_seconds=300, key_prefix="ip")
