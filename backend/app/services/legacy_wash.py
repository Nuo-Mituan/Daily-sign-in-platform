"""One-shot data washes for upgrades from pre-v1.0.3 deployments."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import User
from ..security import verify_password

logger = logging.getLogger(__name__)


def _is_legacy_weak_password(password_hash: str) -> bool:
    return any(
        verify_password(candidate, password_hash)
        for candidate in ("admin123", "admin", "password")
    )


async def wash_legacy_admin_credentials(db: AsyncSession) -> None:
    """Force legacy weak-password admins to change, respecting explicit ADMIN_PASS.

    An explicitly configured, non-default ADMIN_PASS opts out of forced change
    for that configured admin; otherwise only known weak hashes are washed.
    """
    try:
        admin_usernames = list({"admin", (settings.admin_user or "admin").strip()})
        explicit_pass = settings.admin_pass.strip()
        configured_admin = (settings.admin_user or "admin").strip()
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
        washed: list[str] = []
        for admin in legacy_admins:
            if (
                explicit_pass
                and explicit_pass != "admin123"
                and admin.username == configured_admin
            ):
                continue
            if _is_legacy_weak_password(admin.password_hash):
                admin.password_must_change = True
                washed.append(admin.username)
        if washed:
            await db.commit()
            logger.warning(
                "Forced password change for legacy weak admins: %s", washed
            )
        else:
            logger.info("No legacy admin requires forced password change")
    except Exception:
        await db.rollback()
        logger.exception("Legacy admin credential wash failed")
        raise
