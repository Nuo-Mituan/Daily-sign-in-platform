"""One-shot data washes for upgrades from pre-v1.0.3 deployments."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import User

logger = logging.getLogger(__name__)


async def wash_legacy_admin_credentials(db: AsyncSession) -> None:
    """Force existing legacy admin accounts to change password on next login.

    Runs before seed_admin so a fresh database is untouched (no admin yet),
    while an upgraded database always repairs the old admin flag.
    """
    try:
        admin_usernames = list({"admin", (settings.admin_user or "admin").strip()})
        legacy_admins = list(
            (
                await db.execute(
                    select(User).where(
                        User.username.in_(admin_usernames),
                        User.password_must_change.is_(False),
                    )
                )
            ).scalars()
        )
        if legacy_admins:
            for admin in legacy_admins:
                admin.password_must_change = True
            await db.commit()
            logger.warning(
                "Forced password change for legacy admins: %s",
                [admin.username for admin in legacy_admins],
            )
        else:
            logger.info("No legacy admin requires forced password change")
    except Exception:
        await db.rollback()
        logger.exception("Legacy admin credential wash failed")
        raise
