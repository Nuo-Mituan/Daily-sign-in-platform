"""Stable owner identity for at-rest encryption AAD.

The platform is single-admin.  Background scheduler jobs have no authenticated
request, so all field encryption uses the first (and normally only) user id.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


async def owner_user_id(db: AsyncSession) -> int:
    user_id = await db.scalar(select(User.id).order_by(User.id).limit(1))
    if user_id is None:
        raise RuntimeError("尚未创建管理员用户，无法进行字段加密")
    return int(user_id)
