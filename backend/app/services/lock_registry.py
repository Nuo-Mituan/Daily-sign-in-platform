"""Bounded keyed asyncio.Lock registry.

A plain ``dict[key, Lock]`` grows forever when keys are module ids, user ids or
daily cycle ids.  This registry keeps a bounded LRU of *unlocked* locks and
never evicts a held lock, so two callers can still never receive different
locks for the same key while the first holder is active.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)


class KeyLockRegistry(Generic[K]):
    def __init__(self, max_unlocked: int = 256) -> None:
        self._max_unlocked = max(16, int(max_unlocked))
        self._locks: OrderedDict[K, asyncio.Lock] = OrderedDict()

    def get(self, key: K) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        else:
            self._locks.move_to_end(key)
        self._prune()
        return lock

    def _prune(self) -> None:
        if len(self._locks) <= self._max_unlocked:
            return
        for key, lock in list(self._locks.items()):
            if len(self._locks) <= self._max_unlocked:
                return
            if lock.locked():
                continue
            self._locks.pop(key, None)

    def size(self) -> int:
        return len(self._locks)

    def values(self):
        return self._locks.values()
