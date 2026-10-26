"""Pytest bootstrap: isolate runtime data and make ``app`` importable."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="checkin-tests-"))

os.environ.setdefault("DATA_DIR", str(TEMP_ROOT / "data"))
os.environ.setdefault("LOGS_DIR", str(TEMP_ROOT / "logs"))
os.environ.setdefault("MODULES_DIR", str(PROJECT_ROOT / "modules"))
os.environ.setdefault("FRONTEND_DIR", str(PROJECT_ROOT / "frontend" / "dist"))
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-do-not-use-in-production")
os.environ.setdefault("TIMEZONE", "Asia/Shanghai")
os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASS", "test-admin-pass")
os.environ.setdefault("ACCOUNT_INTERVAL_MIN_SECONDS", "1")
os.environ.setdefault("ACCOUNT_INTERVAL_MAX_SECONDS", "1")

backend_path = str(PROJECT_ROOT / "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)


import pytest


@pytest.fixture(autouse=True)
def _reset_login_limiters():
    from app.config import settings
    from app.services.auth_guard import login_ip_limiter, login_user_limiter

    settings.admin_pass = "test-admin-pass"

    login_user_limiter._fail_counts.clear()
    login_user_limiter._attempts.clear()
    login_user_limiter._fail_last.clear()
    login_ip_limiter._attempts.clear()
    login_ip_limiter._fail_last.clear()
    yield
    login_user_limiter._fail_counts.clear()
    login_user_limiter._attempts.clear()
    login_user_limiter._fail_last.clear()
    login_ip_limiter._attempts.clear()
    login_ip_limiter._fail_last.clear()


import asyncio


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
