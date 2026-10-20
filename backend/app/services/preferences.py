"""User-level runtime preferences (developer mode)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


async def developer_mode_enabled(db: AsyncSession, user_id: int) -> bool:
    user = await db.get(User, user_id)
    return bool(user and user.developer_mode_enabled)


async def set_developer_mode(db: AsyncSession, user_id: int, enabled: bool) -> bool:
    user = await db.get(User, user_id)
    if user is None:
        return False
    user.developer_mode_enabled = enabled
    await db.commit()
    return True
