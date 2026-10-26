"""End-to-end backend tests: cookie sessions, CSRF, masking, modules and runs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import zipfile
import stat
import time
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, dispose_db, init_db
from app.main import app
from app.migrations import migrate_schema
from app.models import AuthSession, ExecutionLog, Module, PushConfig
from app.services.bootstrap import initialize_modules, seed_admin
from app.services.ring_log import ring_log

FULL_DAY = {"start_time": "00:00", "end_time": "23:59", "repeat_cycle": "daily"}
ADMIN = {"username": "admin", "password": "test-admin-pass"}
CSRF = "X-CSRF-Token"


def csrf_headers(token: str) -> dict[str, str]:
    return {CSRF: token}


async def login(
    client: AsyncClient, username: str = "admin", password: str = "test-admin-pass"
) -> dict:
    client.cookies.clear()
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" not in data
    assert data["user"]["username"] == username
    assert data["csrf_token"]
    assert data["expires_at"]
    return data


async def wait_for_log(client: AsyncClient, log_id: int) -> dict:
    deadline = time.monotonic() + 40
    payload: dict = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/api/logs/{log_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] != "running":
            return payload
        await asyncio.sleep(0.4)
    raise AssertionError(f"执行未在超时内结束：{payload}")


@pytest.mark.asyncio
async def test_cookie_auth_security_and_modules() -> None:
    await init_db()
    await seed_admin()
    await initialize_modules()
    assert stat.S_IMODE(settings.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(settings.logs_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((settings.data_dir / "checkin.db").stat().st_mode) == 0o600

    transport = ASGITransport(app=app)
    old_secure = settings.cookie_secure
    old_csrf = settings.csrf_enabled
    try:
        # Unauthenticated surface: no cookie => 401 on every protected API.
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as anonymous:
            assert (await anonymous.get("/api/health")).status_code == 200
            assert (
                await anonymous.get(
                    "/api/modules",
                    headers={"Authorization": "Bearer obsolete-jwt-token"},
                )
            ).status_code == 401
            for method, path in [
                ("GET", "/api/modules"),
                ("GET", "/api/dashboard"),
                ("GET", "/api/push/config"),
                ("GET", "/api/logs"),
                ("GET", "/api/auth/session"),
                ("GET", "/api/system/logs"),
                ("GET", "/api/system/metrics"),
                ("POST", "/api/modules/1/run"),
            ]:
                response = await anonymous.request(method, path)
                assert response.status_code == 401, (method, path, response.text)

            for payload in [
                {"username": "missing-user", "password": "wrong"},
                {"username": "admin", "password": "wrong"},
            ]:
                response = await anonymous.post("/api/auth/login", json=payload)
                assert response.status_code == 401
                assert response.json()["detail"] == "用户名或密码错误"

        # Secure=true must add the Secure attribute; default HTTP mode must not.
        from app.services.auth_guard import login_ip_limiter, login_user_limiter
        await login_user_limiter.reset(1)
        await login_ip_limiter.reset(1)
        settings.cookie_secure = True
        try:
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as secure_client:
                response = await secure_client.post("/api/auth/login", json=ADMIN)
                assert response.status_code == 200
                secure_cookie = "\n".join(response.headers.get_list("set-cookie"))
                assert "secure" in secure_cookie.lower()
        finally:
            settings.cookie_secure = old_secure

        # CSRF_ENABLED=false disables only the header check, never the cookie.
        settings.csrf_enabled = False
        try:
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as no_csrf_client:
                data = await login(no_csrf_client)
                response = await no_csrf_client.put(
                    "/api/auth/username",
                    json={
                        "current_password": "test-admin-pass",
                        "new_username": "admin",
                    },
                )
                assert response.status_code == 200, response.text
                assert data["csrf_token"]
        finally:
            settings.csrf_enabled = old_csrf

        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            data = await login(client)
            csrf = data["csrf_token"]
            headers = csrf_headers(csrf)

            cookie_headers = "\n".join(
                (await client.get("/api/auth/session")).headers.get_list(
                    "set-cookie"
                )
            )
            # Login is the place where the initial cookie is issued; verify all
            # attributes from the login response itself.
            login_response = await client.post("/api/auth/login", json=ADMIN)
            assert login_response.status_code == 200
            cookie_headers = "\n".join(
                login_response.headers.get_list("set-cookie")
            )
            lower_cookie = cookie_headers.lower()
            assert "httponly" in lower_cookie
            assert "samesite=strict" in lower_cookie
            assert "max-age=604800" in lower_cookie
            assert "expires=" in lower_cookie
            assert "path=/" in lower_cookie
            assert "secure" not in lower_cookie

            # Login created a second session; the client now holds its cookie.
            data = await login(client)
            csrf = data["csrf_token"]
            headers = csrf_headers(csrf)

            # A write without the CSRF header must be rejected.
            response = await client.put(
                "/api/auth/username",
                json={"current_password": "test-admin-pass", "new_username": "admin"},
            )
            assert response.status_code == 403
            response = await client.put(
                "/api/auth/username",
                headers=headers,
                json={"current_password": "test-admin-pass", "new_username": "admin"},
            )
            assert response.status_code == 200

            # Session renewal only after the five-minute throttle.
            async with SessionLocal() as db:
                session_row = await db.scalar(
                    select(AuthSession)
                    .where(AuthSession.revoked_at.is_(None))
                    .order_by(AuthSession.id.desc())
                )
                assert session_row is not None
                session_row.last_renewed_at = datetime.now(timezone.utc) - timedelta(
                    minutes=6
                )
                await db.commit()
            renewal = await client.get("/api/auth/session")
            assert renewal.status_code == 200
            renewal_headers = "\n".join(
                renewal.headers.get_list("set-cookie")
            ).lower()
            assert "max-age=604800" in renewal_headers
            again = await client.get("/api/auth/session")
            assert again.status_code == 200
            assert not again.headers.get_list("set-cookie")

            meta = (await client.get("/api/meta")).json()
            assert len(meta["repeat_cycles"]) == 5
            assert meta["account_interval_min_seconds"] == 1

            modules = (await client.get("/api/modules")).json()
            demo = next(item for item in modules if item["key"] == "demo_checkin")
            multi = next(item for item in modules if item["key"] == "moyu_energy")
            module_id = demo["id"]

            params = {
                "account": "demo@example.com",
                "password": "supersecret-password",
                "server": "cn",
                "mode": "success",
                "retries": 1,
                "verbose": False,
            }
            response = await client.put(
                f"/api/modules/{module_id}",
                headers=headers,
                json={
                    **FULL_DAY,
                    "repeat_sub_value": "",
                    "params": params,
                    "enabled": True,
                    "push_enabled": False,
                },
            )
            assert response.status_code == 200, response.text
            masked_detail = response.json()
            assert masked_detail["params"]["password"] != params["password"]
            assert "****" in masked_detail["params"]["password"]
            assert masked_detail["params"]["account"] == params["account"]
            assert "supersecret-password" not in response.text

            wrong = await client.post(
                f"/api/modules/{module_id}/reveal-sensitive",
                headers=headers,
                json={"current_password": "wrong-password"},
            )
            assert wrong.status_code == 400
            reveal = await client.post(
                f"/api/modules/{module_id}/reveal-sensitive",
                headers=headers,
                json={"current_password": "test-admin-pass"},
            )
            assert reveal.status_code == 200, reveal.text
            assert reveal.json()["params"]["password"] == params["password"]

            async with SessionLocal() as db:
                module = await db.get(Module, module_id)
                assert module is not None
                assert module.params_encrypted.startswith("v2:")
                assert "supersecret-password" not in module.params_encrypted
                # Inject a v1 Fernet token; GET must transparently read and
                # rewrite it to v2.
                legacy_key = base64.urlsafe_b64encode(
                    hashlib.sha256(settings.secret_key.encode()).digest()  # type: ignore[union-attr]  # TODO(v1.0.3): fix typing
                )
                module.params_encrypted = Fernet(legacy_key).encrypt(
                    json.dumps(params, ensure_ascii=False).encode()
                ).decode()
                await db.commit()
            upgraded = await client.get(f"/api/modules/{module_id}")
            assert upgraded.status_code == 200
            assert "****" in upgraded.json()["params"]["password"]
            async with SessionLocal() as db:
                module = await db.get(Module, module_id)
                assert module.params_encrypted.startswith("v2:")

            # Saving the masked response must preserve the stored secret.
            response = await client.put(
                f"/api/modules/{module_id}",
                headers=headers,
                json={
                    **FULL_DAY,
                    "repeat_sub_value": "",
                    "params": masked_detail["params"],
                    "enabled": True,
                    "push_enabled": False,
                },
            )
            assert response.status_code == 200, response.text
            run = await client.post(
                f"/api/modules/{module_id}/run", headers=headers
            )
            assert run.status_code == 200, run.text
            single_log = await wait_for_log(client, run.json()["log_id"])
            assert single_log["status"] == "success", single_log
            assert "演示签到成功" in single_log["message"]

            # Schedule combinations.
            cycle_cases = [
                ("daily", ""),
                ("weekly", "5"),
                ("monthly_15", ""),
                ("monthly", "28"),
                ("yearly", "2-29"),
            ]
            for cycle, sub_value in cycle_cases:
                response = await client.put(
                    f"/api/modules/{module_id}",
                    headers=headers,
                    json={
                        **FULL_DAY,
                        "repeat_cycle": cycle,
                        "repeat_sub_value": sub_value,
                        "params": params,
                        "enabled": False,
                    },
                )
                assert response.status_code == 200, response.text
                assert response.json()["repeat_cycle"] == cycle
                assert response.json()["repeat_sub_value"] == sub_value
            for payload in [  # type: ignore[assignment]  # TODO(v1.0.3): fix typing
                {**FULL_DAY, "repeat_cycle": "fortnightly", "params": params},
                {
                    **FULL_DAY,
                    "start_time": "23:00",
                    "end_time": "01:00",
                    "params": params,
                },
                {
                    **FULL_DAY,
                    "repeat_cycle": "weekly",
                    "repeat_sub_value": "8",
                    "params": params,
                },
                {
                    **FULL_DAY,
                    "repeat_cycle": "monthly",
                    "repeat_sub_value": "29",
                    "params": params,
                },
                {
                    **FULL_DAY,
                    "repeat_cycle": "yearly",
                    "repeat_sub_value": "2-30",
                    "params": params,
                },
            ]:
                response = await client.put(
                    f"/api/modules/{module_id}", headers=headers, json=payload
                )
                assert response.status_code == 400, response.text

            # Enable daily and generate/regenerate the current occurrence.
            response = await client.put(
                f"/api/modules/{module_id}",
                headers=headers,
                json={
                    **FULL_DAY,
                    "repeat_cycle": "daily",
                    "repeat_sub_value": "",
                    "params": params,
                    "enabled": True,
                    "push_enabled": False,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["current_schedule_at"]
            regenerated = await client.post(
                f"/api/modules/{module_id}/schedule/regenerate",
                headers=headers,
            )
            assert regenerated.status_code == 200, regenerated.text
            assert regenerated.json()["schedule"]["source"] == "manual"
            disabled = await client.patch(
                f"/api/modules/{module_id}/enabled",
                headers=headers,
                json={"enabled": False},
            )
            assert disabled.status_code == 200

            # Multi-account masking, save and serial execution.
            multi_id = multi["id"]
            first = {
                "id": "api-main",
                "label": "",
                "params": {
                    "cookie": "SESSDATA=API_COOKIE_ONE_123456; bili_jct=one",
                    "target_level": 3,
                    "verbose": False,
                    "simulate_failure": False,
                },
            }
            second = {
                "id": "api-alt",
                "label": "",
                "params": {
                    "cookie": "SESSDATA=API_COOKIE_TWO_654321; bili_jct=two",
                    "target_level": 5,
                    "verbose": False,
                    "simulate_failure": False,
                },
            }
            response = await client.put(
                f"/api/modules/{multi_id}",
                headers=headers,
                json={
                    **FULL_DAY,
                    "repeat_sub_value": "",
                    "accounts": [first, second],
                    "enabled": True,
                    "push_enabled": False,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["account_count"] == 2
            multi_detail = response.json()
            assert first["params"]["cookie"] not in response.text  # type: ignore[index]  # TODO(v1.0.3): fix typing
            assert "****" in multi_detail["accounts"][0]["params"]["cookie"]
            async with SessionLocal() as db:
                module = await db.get(Module, multi_id)
                assert module is not None
                assert module.accounts_encrypted.startswith("v2:")
                assert first["params"]["cookie"] not in module.accounts_encrypted  # type: ignore[index]  # TODO(v1.0.3): fix typing
            revealed_accounts = await client.post(
                f"/api/modules/{multi_id}/reveal-sensitive",
                headers=headers,
                json={"current_password": "test-admin-pass"},
            )
            assert revealed_accounts.status_code == 200
            assert (
                revealed_accounts.json()["accounts"][0]["params"]["cookie"]
                == first["params"]["cookie"]  # type: ignore[index]  # TODO(v1.0.3): fix typing
            )
            await client.patch(
                f"/api/modules/{multi_id}/enabled",
                headers=headers,
                json={"enabled": False},
            )
            run = await client.post(
                f"/api/modules/{multi_id}/run", headers=headers
            )
            multi_log = await wait_for_log(client, run.json()["log_id"])
            assert multi_log["status"] == "success", multi_log
            output = multi_log["output"] or ""
            assert "[账号 1/2]" in output and "[账号 2/2]" in output
            assert first["params"]["cookie"] not in output  # type: ignore[index]  # TODO(v1.0.3): fix typing
            assert second["params"]["cookie"] not in output  # type: ignore[index]  # TODO(v1.0.3): fix typing

            # Custom driver upload, AST rejection, hot reload, rollback and delete.
            await client.delete("/api/push/drivers/driver_test", headers=headers)
            driver_source = (
                "async def send(config, title, body):\n"
                "    return {'sent': True, 'channel': 'driver-test', "
                "'response': 'ok'}\n"
            )
            upload = await client.post(
                "/api/push/drivers/upload",
                headers=headers,
                files={"file": ("driver_test.py", driver_source)},
                data={
                    "key": "driver_test",
                    "name": "Driver Test",
                    "version": "1.0.0",
                },
            )
            assert upload.status_code == 200, upload.text
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            drivers = (await client.get("/api/push/drivers")).json()
            assert any(item["key"] == "driver_test" for item in drivers)
            dangerous = await client.post(
                "/api/push/drivers/upload",
                headers=headers,
                files={
                    "file": (
                        "danger.py",
                        "import os\ndef send(config, title, body):\n"
                        "    os.system('echo unsafe')\n",
                    )
                },
                data={"key": "danger_test", "version": "1.0.0"},
            )
            assert dangerous.status_code == 400
            assert "禁止" in dangerous.text
            upload2 = await client.post(
                "/api/push/drivers/upload",
                headers=headers,
                files={"file": ("driver_test.py", driver_source)},
                data={
                    "key": "driver_test",
                    "name": "Driver Test",
                    "version": "1.0.1",
                },
            )
            assert upload2.status_code == 200, upload2.text
            rolled = await client.post(
                "/api/push/drivers/driver_test/rollback",
                headers=headers,
                json={"version": "1.0.0"},
            )
            assert rolled.status_code == 200, rolled.text
            assert rolled.json()["driver"]["version"] == "1.0.0"
            saved_custom_push = await client.put(
                "/api/push/config",
                headers=headers,
                json={
                    "channel": "driver_test",
                    "config": {},
                    "title_template": "{event}",
                    "body_template": "{result}",
                },
            )
            assert saved_custom_push.status_code == 200, saved_custom_push.text
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            custom_test = await client.post("/api/push/test", headers=headers)
            assert custom_test.status_code == 200, custom_test.text
            assert custom_test.json()["success"] is True
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            blocked_delete = await client.delete(
                "/api/push/drivers/driver_test", headers=headers
            )
            assert blocked_delete.status_code == 409
            await client.put(
                "/api/push/config",
                headers=headers,
                json={"channel": "none", "config": {}},
            )
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            deleted_driver = await client.delete(
                "/api/push/drivers/driver_test", headers=headers
            )
            assert deleted_driver.status_code == 200, deleted_driver.text

            def make_driver_zip(manifest: dict, source: str, extra: str = "") -> bytes:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr("manifest.json", json.dumps(manifest))
                    archive.writestr("driver.py", source)
                    if extra:
                        archive.writestr(extra, "evil")
                return buffer.getvalue()

            zip_manifest = {
                "key": "zip_driver",
                "name": "Zip Driver",
                "version": "1.0.0",
                "entry": "driver.py",
                "fields": [],
            }
            zip_upload = await client.post(
                "/api/push/drivers/upload",
                headers=headers,
                files={
                    "file": (
                        "driver.zip",
                        make_driver_zip(zip_manifest, driver_source),
                    )
                },
            )
            assert zip_upload.status_code == 200, zip_upload.text
            await client.delete("/api/push/drivers/zip_driver", headers=headers)
            slip = await client.post(
                "/api/push/drivers/upload",
                headers=headers,
                files={
                    "file": (
                        "slip.zip",
                        make_driver_zip(zip_manifest, driver_source, "../evil.py"),
                    )
                },
            )
            assert slip.status_code == 400
            assert "路径" in slip.text

            # Push config is masked at rest/API and revealed only with password.
            saved_push = await client.put(
                "/api/push/config",
                headers=headers,
                json={
                    "channel": "bark",
                    "config": {"key": "push-secret-key"},
                    "title_template": "{event}",
                    "body_template": "{result}",
                },
            )
            assert saved_push.status_code == 200, saved_push.text
            assert saved_push.json()["config"]["key"] != "push-secret-key"
            assert "****" in saved_push.json()["config"]["key"]
            async with SessionLocal() as db:
                row = await db.get(PushConfig, 1)
                assert row is not None
                assert row.config_encrypted.startswith("v2:")
                assert "push-secret-key" not in row.config_encrypted
            # Saving the masked API value must not overwrite the credential.
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            masked_push = await client.put(
                "/api/push/config",
                headers=headers,
                json={
                    "channel": "bark",
                    "config": saved_push.json()["config"],
                    "title_template": "{event}",
                    "body_template": "{result}",
                },
            )
            assert masked_push.status_code == 200
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            push_reveal = await client.post(
                "/api/push/reveal",
                headers=headers,
                json={"current_password": "test-admin-pass"},
            )
            assert push_reveal.status_code == 200
            assert push_reveal.json()["config"]["key"] == "push-secret-key"
            system_logs = await client.get("/api/system/logs?page=1&page_size=5")
            assert system_logs.status_code == 200
            assert "items" in system_logs.json()
            metrics = await client.get("/api/system/metrics")
            assert metrics.status_code == 200
            assert "ring" in metrics.json() and "sse" in metrics.json()
            assert (
                await client.post("/api/system/logs")
            ).status_code == 405
            records = await client.get("/api/push/records?page=1&page_size=10")
            assert records.status_code == 200
            assert "items" in records.json()
            batches = await client.get("/api/push/batches?page=1&page_size=10")
            assert batches.status_code == 200
            assert "items" in batches.json()
            await client.put(
                "/api/push/config",
                headers=headers,
                json={"channel": "none", "config": {}},
            )

            # Ring-backed SSE resumption: only rows after last_seq are sent.
            async with SessionLocal() as db:
                stream_log = ExecutionLog(
                    module_id=module_id,
                    module_key=demo["key"],
                    module_name=demo["name"],
                    trigger="manual",
                    status="success",
                    message="sse replay",
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=5,
                )
                db.add(stream_log)
                await db.commit()
                await db.refresh(stream_log)
                stream_log_id = stream_log.id
            replay_seqs = [
                ring_log.append_execution(
                    module_key=demo["key"],
                    log_id=stream_log_id,
                    text=f"replay-line-{index}\n",
                )
                for index in range(3)
            ]
            relogin = await login(client)
            headers = csrf_headers(relogin["csrf_token"])
            replay = await client.get(
                f"/api/logs/{stream_log_id}/stream",
                params={"last_seq": replay_seqs[0]},
            )
            assert replay.status_code == 200
            replay_text = replay.text
            assert "replay-line-0" not in replay_text
            assert "replay-line-1" in replay_text
            assert "replay-line-2" in replay_text
            assert f"id: {replay_seqs[1]}" in replay_text
            assert "event: done" in replay_text
            replay_detail = (
                await client.get(f"/api/logs/{stream_log_id}")
            ).json()
            assert replay_detail["last_seq"] == replay_seqs[-1]

            # Pre-ring execution rows keep their output as a read-only fallback.
            async with SessionLocal() as db:
                legacy_log = ExecutionLog(
                    module_id=module_id,
                    module_key=demo["key"],
                    module_name=demo["name"],
                    trigger="manual",
                    status="success",
                    message="legacy output",
                    output="legacy-output-from-v5\n",
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=1,
                )
                db.add(legacy_log)
                await db.commit()
                await db.refresh(legacy_log)
                legacy_log_id = legacy_log.id
            legacy_detail = (
                await client.get(f"/api/logs/{legacy_log_id}")
            ).json()
            assert legacy_detail["output"] == "legacy-output-from-v5\n"
            assert legacy_detail["last_seq"] == 0

            # A v5 row has push_enabled but NULL new switches.  The migration
            # must map it to independent push before any worker reads the row.
            async with SessionLocal() as db:
                await db.execute(
                    Module.__table__.update()
                    .where(Module.id == module_id)
                    .values(
                        push_enabled=True,
                        push_independent=None,
                        push_unified=None,
                    )
                )
                await db.commit()
            await migrate_schema()
            async with SessionLocal() as db:
                migrated = await db.get(Module, module_id)
                assert migrated is not None
                assert migrated.push_independent is True
                assert migrated.push_unified is False
                migrated.push_enabled = False
                migrated.push_independent = False
                migrated.push_unified = False
                await db.commit()

            log_settings = await client.get("/api/settings/logs")
            assert log_settings.status_code == 200
            invalid_retention = await client.put(
                "/api/settings/logs",
                headers=headers,
                json={"retention_days": 0},
            )
            assert invalid_retention.status_code == 422
            updated_retention = await client.put(
                "/api/settings/logs",
                headers=headers,
                json={"retention_days": 31},
            )
            assert updated_retention.status_code == 200, updated_retention.text
            assert updated_retention.json()["retention_days"] == 31

            dashboard = (await client.get("/api/dashboard")).json()
            assert dashboard["stats"]["today_runs"] >= 2
            logs = (await client.get("/api/logs?page=1&page_size=20")).json()
            assert logs["total"] >= 2

            # A DB/engine restart must preserve the server-side session.
            saved_cookie = client.cookies.get(settings.cookie_name)
            assert saved_cookie
            await dispose_db()
            await init_db()
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as restarted:
                restarted.cookies.set(settings.cookie_name, saved_cookie)
                response = await restarted.get("/api/auth/session")
                assert response.status_code == 200, response.text

            # Username change and idempotency.
            response = await client.put(
                "/api/auth/username",
                headers=headers,
                json={"current_password": "test-admin-pass", "new_username": "admin"},
            )
            assert response.status_code == 200
            response = await client.put(
                "/api/auth/username",
                headers=headers,
                json={"current_password": "test-admin-pass", "new_username": "verify-admin"},
            )
            assert response.status_code == 200
            assert response.json()["username"] == "verify-admin"
            response = await client.put(
                "/api/auth/username",
                headers=headers,
                json={"current_password": "test-admin-pass", "new_username": "verify-admin"},
            )
            assert response.status_code == 200
            response = await client.put(
                "/api/auth/username",
                headers=headers,
                json={"current_password": "test-admin-pass", "new_username": "admin"},
            )
            assert response.status_code == 200

            # Logout invalidates only the current session.
            current_cookie = client.cookies.get(settings.cookie_name)
            response = await client.post("/api/auth/logout", headers=headers)
            assert response.status_code == 200
            assert client.cookies.get(settings.cookie_name) in (None, "")
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as old_session:
                old_session.cookies.set(settings.cookie_name, current_cookie)
                assert (
                    await old_session.get("/api/auth/session")
                ).status_code == 401

            # Logout-all invalidates sessions on every device.
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as first_client, AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as second_client:
                first_data = await login(first_client)
                await login(second_client)
                response = await first_client.post(
                    "/api/auth/logout-all",
                    headers=csrf_headers(first_data["csrf_token"]),
                )
                assert response.status_code == 200
                assert (
                    await second_client.get("/api/auth/session")
                ).status_code == 401

            # Password change deletes all sessions and issues no valid cookie.
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as pw_client:
                pw_data = await login(pw_client)
                changed = await pw_client.post(
                    "/api/auth/change-password",
                    headers=csrf_headers(pw_data["csrf_token"]),
                    json={
                        "old_password": "test-admin-pass",
                        "new_password": "new-admin-pass",
                    },
                )
                assert changed.status_code == 200, changed.text
                assert (
                    await pw_client.get("/api/auth/session")
                ).status_code == 401
                assert (
                    await pw_client.post("/api/auth/login", json=ADMIN)
                ).status_code == 401
                new_login = await pw_client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "new-admin-pass"},
                )
                assert new_login.status_code == 200
    finally:
        settings.cookie_secure = old_secure
        settings.csrf_enabled = old_csrf
        await dispose_db()
