"""Bootstrap tasks executed once at application startup."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from ..config import settings
from ..database import SessionLocal
from ..models import Module, User
from ..module_loader import SyncResult, sync_modules
from ..security import hash_password

logger = logging.getLogger(__name__)


async def seed_admin() -> bool:
    async with SessionLocal() as db:
        user_count = await db.scalar(select(func.count()).select_from(User))
        if user_count and user_count > 0:
            return False

        username = (settings.admin_user or "admin").strip()[:64] or "admin"
        password = settings.admin_pass or "admin123"
        db.add(User(username=username, password_hash=hash_password(password)))
        await db.commit()
        logger.warning(
            "首次部署：已创建管理员账号 %s。请登录后立即在右上角「用户设置」中修改账号凭据。",
            username,
        )
        if password == "admin123":
            logger.warning("当前仍在使用默认密码 admin123，强烈建议立即在「用户设置」中修改！")
        return True


async def load_all_modules() -> list[Module]:
    async with SessionLocal() as db:
        return list((await db.execute(select(Module))).scalars().all())


async def initialize_modules() -> SyncResult:
    async with SessionLocal() as db:
        return await sync_modules(db)
