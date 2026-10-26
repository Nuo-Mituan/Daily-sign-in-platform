"""v1.0.1 developer-mode and manual-test execution regression tests."""

from __future__ import annotations

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import SessionLocal, init_db
from app.main import app
from app.models import User
from app.security import hash_password
from app.services.bootstrap import initialize_modules


async def _client_for_new_user(suffix: str) -> tuple[AsyncClient, str]:
    await init_db()
    await initialize_modules()
    username = f"devmode-{suffix}"
    password = "Dev-Mode-Pass-123"
    async with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password(password)))
        await db.commit()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return client, response.json()["csrf_token"]


async def _first_module(client: AsyncClient) -> int:
    response = await client.get("/api/modules")
    assert response.status_code == 200
    modules = response.json()
    assert modules
    return int(modules[0]["id"])


@pytest.mark.asyncio
async def test_developer_mode_false_blocks_test_execution() -> None:
    client, csrf = await _client_for_new_user("blocked")
    try:
        module_id = await _first_module(client)
        preference = await client.get("/api/settings/developer")
        assert preference.status_code == 200
        assert preference.json()["enabled"] is False
        session_payload = (await client.get("/api/auth/session")).json()
        assert session_payload["user"]["developer_mode_enabled"] is False
        response = await client.post(
            f"/api/modules/{module_id}/test",
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 403, response.text
        assert "开发者选项" in response.json()["detail"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_developer_mode_true_executes_and_marks_test_log() -> None:
    client, csrf = await _client_for_new_user("enabled")
    try:
        module_id = await _first_module(client)
        enabled = await client.put(
            "/api/settings/developer",
            json={"enabled": True},
            headers={"X-CSRF-Token": csrf},
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["enabled"] is True
        relogin = await client.post(
            "/api/auth/login",
            json={"username": "devmode-enabled", "password": "Dev-Mode-Pass-123"},
        )
        assert relogin.status_code == 200, relogin.text
        csrf = relogin.json()["csrf_token"]
        preference = await client.get("/api/settings/developer")
        assert preference.status_code == 200
        assert preference.json()["enabled"] is True
        session_payload = (await client.get("/api/auth/session")).json()
        assert session_payload["user"]["developer_mode_enabled"] is True

        response = await client.post(
            f"/api/modules/{module_id}/test",
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text
        log_id = int(response.json()["log_id"])

        deadline = time.monotonic() + 40
        detail: dict = {}
        while time.monotonic() < deadline:
            detail_response = await client.get(f"/api/logs/{log_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            if detail["status"] != "running":
                break
            await asyncio.sleep(0.2)
        assert detail["trigger"] == "test"
        assert detail["module_name"].startswith("[TEST]")
        assert detail["status"] in {"success", "failed"}
    finally:
        await client.aclose()
