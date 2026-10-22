"""Shared per-cycle lock registry for all unified-push modules."""

from __future__ import annotations

import asyncio

from .lock_registry import KeyLockRegistry

_locks = KeyLockRegistry[str](max_unlocked=256)


def get_cycle_lock(cycle_id: str) -> asyncio.Lock:
    return _locks.get(cycle_id)
