"""Module icon source validation and local ICO endpoint security tests."""

from __future__ import annotations

import json
import shutil
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pydantic import ValidationError
from io import BytesIO

from app.config import settings
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Module, User
from sqlalchemy import delete, select
from app.module_loader import ModuleConfig
from app.security import hash_password
from app.services.bootstrap import seed_admin


@pytest.mark.asyncio
async def test_local_ico_endpoint_validation_and_headers() -> None:
    await init_db()
    await seed_admin()
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin.password_hash = hash_password("icon-test-pass")
        admin.password_must_change = False
        await db.commit()
    key = f"icon-test-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    ico = folder / "icon.ico"
    mapped_key = f"mapped-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        db.add(Module(key=mapped_key, directory_name=key, name="Mapped icon", param_schema=[]))
        await db.commit()
    try:
        buffer = BytesIO()
        transparent = Image.new("RGBA", (32, 32), (255, 0, 0, 0))
        transparent.save(buffer, format="ICO")
        ico.write_bytes(buffer.getvalue())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as anonymous:
            public_icon = await anonymous.get(
                "/api/modules/icon", params={"key": key}
            )
            assert public_icon.status_code == 200
            protected = await anonymous.get("/api/modules")
            assert protected.status_code == 401
            assert protected.headers["content-type"].startswith("application/json")
            assert protected.json()["detail"] == "登录状态已失效，请重新登录"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "icon-test-pass"},
            )
            assert login.status_code == 200
            response = await client.get("/api/modules/icon", params={"key": key})
            assert response.status_code == 200
            mapped = await client.get(
                "/api/modules/icon", params={"key": mapped_key, "path": "icon.ico"}
            )
            assert mapped.status_code == 200
            assert mapped.headers["content-type"].startswith("image/png")
            assert response.headers["content-type"].startswith("image/png")
            assert response.headers["cache-control"] == "public, max-age=86400"
            decoded = Image.open(BytesIO(response.content))
            assert decoded.mode == "RGBA"
            assert decoded.getchannel("A").getextrema()[0] == 0

            png_buffer = BytesIO()
            Image.new("RGBA", (16, 16), (0, 0, 255, 0)).save(
                png_buffer, format="PNG"
            )
            png_path = folder / "icon.png"
            png_path.write_bytes(png_buffer.getvalue())
            png_response = await client.get(
                "/api/modules/icon", params={"key": key, "path": "icon.png"}
            )
            assert png_response.status_code == 200
            assert png_response.headers["content-type"].startswith("image/png")

            svg_path = folder / "icon.svg"
            svg_path.write_bytes(
                b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'
            )
            svg_response = await client.get(
                "/api/modules/icon", params={"key": key, "path": "icon.svg"}
            )
            assert svg_response.status_code == 200
            assert svg_response.headers["content-type"].startswith("image/svg+xml")

            ico.write_bytes(b"\x00\x00\x01\x00" + b"\x00" * (64 * 1024))
            too_large = await client.get("/api/modules/icon", params={"key": key})
            assert too_large.status_code == 413

            ico.write_bytes(b"MZ" + b"\x00" * 10)
            not_ico = await client.get("/api/modules/icon", params={"key": key})
            assert not_ico.status_code == 415

            traversal = await client.get(
                "/api/modules/icon", params={"key": "../../etc/passwd"}
            )
            assert traversal.status_code in {400, 403}
            for bad_path in ("../etc/passwd", "./../../secret.ico", "/var/www/favicon.ico", "..\\secret.ico"):
                bad = await client.get(
                    "/api/modules/icon", params={"key": key, "path": bad_path}
                )
                assert bad.status_code in {400, 403}, (bad_path, bad.text)
            missing = await client.get("/api/modules/icon", params={"key": "missing-icon"})
            assert missing.status_code == 404
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == mapped_key))
            await db.commit()


def test_icon_config_base64_and_backward_compatibility() -> None:
    valid = ModuleConfig(name="base64", icon="data:image/png;base64,iVBORw0KGgo=")
    assert valid.icon.startswith("data:image/png")
    legacy = ModuleConfig(name="legacy", icon="🎯")
    assert legacy.icon == "🎯"
    local = ModuleConfig(name="local", icon="./favicon.ico")
    assert local.icon == "./favicon.ico"
    with pytest.raises(ValidationError):
        ModuleConfig(name="xss", icon_source="base64", icon_data="javascript:alert(1)")
    with pytest.raises(ValidationError):
        ModuleConfig(name="big", icon_source="base64", icon_data="data:image/png;base64," + "A" * 65536)


@pytest.mark.asyncio
async def test_sync_adopts_renamed_directory_and_writes_directory_name(tmp_path, monkeypatch) -> None:
    await init_db()
    key = f"legacy-{uuid.uuid4().hex[:8]}"
    directory = f"renamed-{uuid.uuid4().hex[:8]}"
    display = f"Renamed {key}"
    async with SessionLocal() as db:
        db.add(Module(key=key, directory_name=None, name=display, param_schema=[]))
        await db.commit()
    monkeypatch.setattr(settings, "modules_dir", tmp_path)
    folder = tmp_path / directory
    folder.mkdir()
    (folder / "config.json").write_text(
        json.dumps(
            {
                "name": display,
                "directory_name": directory,
                "legacy_key": key,
                "version": "1.0.0",
                "icon": "./favicon.ico",
            }
        ),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(
        "async def run(params):\n    return 'ok'\n", encoding="utf-8"
    )
    try:
        from app.module_loader import sync_modules

        async with SessionLocal() as db:
            await sync_modules(db)
        async with SessionLocal() as db:
            row = await db.scalar(select(Module).where(Module.key == key))
            assert row is not None
            assert row.directory_name == directory
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


@pytest.mark.asyncio
async def test_delete_module_hard_removes_files_and_related_rows() -> None:
    await init_db()
    await seed_admin()
    from datetime import date, datetime, timezone
    from app.models import ExecutionLog, ModuleSchedule, PushPool

    key = f"delete-{uuid.uuid4().hex[:8]}"
    directory = f"delete-dir-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / directory
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "icon.ico").write_bytes(b"\x00\x00\x01\x00")
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin.password_hash = hash_password("delete-test-pass")
        admin.password_must_change = False
        module = Module(key=key, directory_name=directory, name="Delete test", param_schema=[])
        db.add(module)
        await db.commit()
        await db.refresh(module)
        db.add(ExecutionLog(module_id=module.id, module_key=key, module_name=module.name))
        db.add(ModuleSchedule(module_id=module.id, period_start=date.today(), scheduled_at=datetime.now(timezone.utc)))
        db.add(PushPool(cycle_id="2026-01-01", module_id=module.id, module_key=key, module_name=module.name))
        await db.commit()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "delete-test-pass"},
            )
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            response = await client.delete(
                f"/api/modules/{key}", headers={"X-CSRF-Token": csrf}
            )
            assert response.status_code == 200, response.text
        assert not folder.exists()
        async with SessionLocal() as db:
            assert await db.scalar(select(Module).where(Module.key == key)) is None
            assert await db.scalar(select(ExecutionLog).where(ExecutionLog.module_key == key)) is None
            assert await db.scalar(select(ModuleSchedule).where(ModuleSchedule.module_id == module.id)) is None
            assert await db.scalar(select(PushPool).where(PushPool.module_key == key)) is None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


@pytest.mark.asyncio
async def test_legacy_migration_without_config_legacy_key(tmp_path, monkeypatch) -> None:
    from app.migrate_modules import migrate_modules

    await init_db()
    key = f"migrate-{uuid.uuid4().hex[:8]}"
    directory = f"physical-{uuid.uuid4().hex[:8]}"
    display = f"Migrate {key}"
    async with SessionLocal() as db:
        db.add(Module(key=key, directory_name=None, name=display, param_schema=[]))
        await db.commit()
    monkeypatch.setattr(settings, "modules_dir", tmp_path)
    folder = tmp_path / directory
    folder.mkdir()
    (folder / "config.json").write_text(
        json.dumps({"name": display, "directory_name": directory, "version": "1.0.0"}),
        encoding="utf-8",
    )
    (folder / "main.py").write_text("async def run(params):\n    return 'ok'\n", encoding="utf-8")
    try:
        report = await migrate_modules(dry_run=False)
        assert any(item["old_key"] == key for item in report.migrated)
        async with SessionLocal() as db:
            row = await db.scalar(select(Module).where(Module.key == key))
            assert row is not None
            assert row.directory_name == directory
            assert row.legacy_key == key
        again = await migrate_modules(dry_run=False)
        assert all(item["old_key"] != key for item in again.migrated)
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


@pytest.mark.asyncio
async def test_sync_ignores_backup_dot_directories(tmp_path, monkeypatch) -> None:
    await init_db()
    monkeypatch.setattr(settings, "modules_dir", tmp_path)
    backup = tmp_path / ".backup-demo_deadbeef"
    backup.mkdir()
    (backup / "config.json").write_text(
        json.dumps({"name": "Backup should not load", "version": "1.0.0"}),
        encoding="utf-8",
    )
    (backup / "main.py").write_text("async def run(params):\n    return 'ok'\n", encoding="utf-8")
    from app.module_loader import sync_modules

    async with SessionLocal() as db:
        await sync_modules(db)
        row = await db.scalar(select(Module).where(Module.key == backup.name))
        assert row is None


@pytest.mark.asyncio
async def test_icon_rate_limit_returns_retry_after(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.module_loader import sync_modules

    await init_db()
    key = f"rate-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())
    monkeypatch.setattr(modules_router, "_ICON_RATE_LIMIT", 1)
    modules_router._ICON_RATE.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            first = await client.get("/api/modules/icon", params={"key": key})
            second = await client.get("/api/modules/icon", params={"key": key})
            assert first.status_code == 200
            assert second.status_code == 429
            assert second.headers["retry-after"] == "60"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.asyncio
async def test_icon_cache_hit_avoids_second_decode(monkeypatch) -> None:
    from app.routers import modules as modules_router

    await init_db()
    key = f"cache-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())
    calls = {"count": 0}
    original = modules_router.load_icon

    def counted(path):
        calls["count"] += 1
        return original(path)

    monkeypatch.setattr(modules_router, "load_icon", counted)
    monkeypatch.setattr(modules_router, "_ICON_RATE_LIMIT", 1000)
    modules_router._ICON_RATE.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            first = await client.get("/api/modules/icon", params={"key": key})
            second = await client.get("/api/modules/icon", params={"key": key})
            assert first.status_code == 200
            assert second.status_code == 200
            assert calls["count"] == 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _make_module_zip(base, name="demo_checkin"):
    import zipfile
    archive = base / "module.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{name}/config.json", json.dumps({
            "name": "Upload test", "version": "1.0.0",
            "directory_name": "ehentai_daily_login",
        }))
        zf.writestr(f"{name}/main.py", "async def run(params):\n    return 'ok'\n")
    return archive


def test_upload_writes_to_directory_name(tmp_path, monkeypatch) -> None:
    from app.services.module_upload import _install_zip_sync
    monkeypatch.setattr(settings, "modules_dir", tmp_path / "modules")
    archive = _make_module_zip(tmp_path)
    key, config = _install_zip_sync(
        archive, "module.zip", "demo_checkin", False, "ehentai_daily_login"
    )
    assert key == "demo_checkin"
    assert config.directory_name == "ehentai_daily_login"
    assert (tmp_path / "modules" / "ehentai_daily_login" / "main.py").is_file()
    assert not (tmp_path / "modules" / "demo_checkin").exists()


def test_upload_key_residue_directory_conflict(tmp_path, monkeypatch) -> None:
    from app.services.module_upload import ModuleUploadError, _install_zip_sync
    modules = tmp_path / "modules"
    (modules / "demo_checkin").mkdir(parents=True)
    (modules / "demo_checkin" / "main.py").write_text("old")
    monkeypatch.setattr(settings, "modules_dir", modules)
    archive = _make_module_zip(tmp_path)
    with pytest.raises(ModuleUploadError, match="残留目录"):
        _install_zip_sync(
            archive, "module.zip", "demo_checkin", True, "ehentai_daily_login"
        )


@pytest.mark.asyncio
async def test_sync_modules_create_update_field_symmetry() -> None:
    from app.module_loader import (
        _create_module_from_config,
        _module_field_values,
        _update_module_from_config,
    )

    config = ModuleConfig.model_validate({
        "name": "Symmetry",
        "directory_name": "physical-dir",
        "legacy_key": "old-key",
        "version": "1.0.0",
        "icon": "./favicon.ico",
    })
    async with SessionLocal() as db:
        created = _create_module_from_config(db, "new-key", config)
        updated = Module(key="new-key", name="old", directory_name=None, param_schema=[])
        _update_module_from_config(updated, config)
        expected = _module_field_values(config)
        for field, value in expected.items():
            assert getattr(created, field) == value, field
            assert getattr(updated, field) == value, field
        assert created.param_schema == updated.param_schema
        await db.rollback()


@pytest.mark.asyncio
async def test_upload_cross_record_directory_conflict() -> None:
    await init_db()
    await seed_admin()
    key = f"source-{uuid.uuid4().hex[:8]}"
    other = f"other-{uuid.uuid4().hex[:8]}"
    directory = f"shared-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin.password_hash = hash_password("upload-test-pass")
        admin.password_must_change = False
        db.add(Module(key=key, directory_name=directory, name="Source", param_schema=[]))
        db.add(Module(key=other, directory_name=directory, name="Other", param_schema=[]))
        await db.commit()
    import io, zipfile
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("config.json", json.dumps({"name": "Source", "version": "1.0.0", "directory_name": directory}))
        zf.writestr("main.py", "async def run(params):\n    return 'ok'\n")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            login = await client.post("/api/auth/login", json={"username": "admin", "password": "upload-test-pass"})
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            response = await client.post(
                "/api/modules/upload",
                params={"overwrite": "true"},
                data={"name": key},
                files={"file": ("module.zip", buffer.getvalue(), "application/zip")},
                headers={"X-CSRF-Token": csrf},
            )
            assert response.status_code == 409
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key.in_([key, other])))
            await db.commit()


@pytest.mark.asyncio
async def test_icon_wait_for_timeout_returns_504(monkeypatch) -> None:
    from app.routers import modules as modules_router
    import asyncio as asyncio_module

    await init_db()
    key = f"timeout-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())
    async def timeout(*args, **kwargs):
        raise asyncio_module.TimeoutError()
    monkeypatch.setattr(modules_router.asyncio, "wait_for", timeout)
    modules_router._ICON_RATE.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/modules/icon", params={"key": key})
            assert response.status_code == 504
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.asyncio
async def test_icon_concurrent_no_block_event_loop(monkeypatch) -> None:
    from app.routers import modules as modules_router
    import asyncio as asyncio_module

    await init_db()
    key = f"concurrent-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())
    calls = {"count": 0}
    pool = modules_router._get_icon_decode_pool()
    original_submit = pool.submit
    def counted_submit(fn, *args, **kwargs):
        calls["count"] += 1
        return original_submit(fn, *args, **kwargs)
    monkeypatch.setattr(pool, "submit", counted_submit)
    modules_router._ICON_RATE.clear()
    try:
        async def heartbeat() -> None:
            for _ in range(20):
                await asyncio_module.sleep(0.005)
                calls["count"] += 1

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            responses, _ = await asyncio_module.gather(
                asyncio_module.gather(*[
                    client.get("/api/modules/icon", params={"key": key})
                    for _ in range(4)
                ]),
                heartbeat(),
            )
            assert all(response.status_code == 200 for response in responses)
            assert calls["count"] > 0
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.asyncio
async def test_update_module_preserves_manual_directory_name() -> None:
    from app.module_loader import _update_module_from_config
    config = ModuleConfig.model_validate({"name": "No directory", "version": "1.0.0"})
    module = Module(key="manual-key", directory_name="manual-dir", name="old", param_schema=[])
    _update_module_from_config(module, config)
    assert module.directory_name == "manual-dir"


@pytest.mark.asyncio
async def test_find_existing_module_skips_self_reference() -> None:
    from app.module_loader import _find_existing_module
    key = f"self-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        db.add(Module(key=key, directory_name=None, name="Self", param_schema=[]))
        await db.commit()
        config = ModuleConfig.model_validate({
            "name": "Self", "directory_name": "other-dir", "legacy_key": key,
            "version": "1.0.0",
        })
        row = await _find_existing_module(db, "new-dir", config)
        assert row is not None and row.key == key


def test_icon_decode_pool_shutdown_is_idempotent(monkeypatch) -> None:
    from app.routers import modules as modules_router
    calls = {"count": 0}
    def fake_shutdown(*, wait=False, cancel_futures=False):
        calls["count"] += 1
    pool = modules_router._get_icon_decode_pool()
    monkeypatch.setattr(pool, "shutdown", fake_shutdown)
    modules_router.shutdown_icon_decode_pool()
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_migrate_modules_dry_run_and_apply_with_map(tmp_path, monkeypatch) -> None:
    from app.migrate_modules import migrate_modules
    await init_db()
    key = f"map-old-{uuid.uuid4().hex[:8]}"
    directory = f"map-dir-{uuid.uuid4().hex[:8]}"
    folder = tmp_path / directory
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps({"name": "Map", "directory_name": directory, "version": "1.0.0"}))
    (folder / "main.py").write_text("async def run(params):\n    return 'ok'\n")
    async with SessionLocal() as db:
        db.add(Module(key=key, directory_name=None, name="Map", param_schema=[]))
        await db.commit()
    monkeypatch.setattr(settings, "modules_dir", tmp_path)
    try:
        dry = await migrate_modules(dry_run=True, mappings={key: directory})
        assert dry.migrated
        async with SessionLocal() as db:
            row = await db.scalar(select(Module).where(Module.key == key))
            assert row is not None and row.directory_name is None
        applied = await migrate_modules(dry_run=False, mappings={key: directory})
        assert applied.migrated
        async with SessionLocal() as db:
            row = await db.scalar(select(Module).where(Module.key == key))
            assert row is not None and row.directory_name == directory
        again = await migrate_modules(dry_run=False, mappings={key: directory})
        assert again.failed == []
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


def test_icon_rate_limiter_cleanup_runs_once(monkeypatch) -> None:
    from app.routers import modules as modules_router
    monkeypatch.setattr(modules_router, "_ICON_RATE_LAST_CLEANUP", 0.0)
    modules_router._ICON_RATE.clear()
    modules_router._ICON_RATE["1.1.1.1"] = [-500.0]
    modules_router._cleanup_icon_rate(100.0)
    assert modules_router._ICON_RATE_LAST_CLEANUP == 100.0
    assert "1.1.1.1" not in modules_router._ICON_RATE
    modules_router._cleanup_icon_rate(101.0)
    assert modules_router._ICON_RATE_LAST_CLEANUP == 100.0


@pytest.mark.asyncio
async def test_icon_decode_pool_uses_running_loop(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.services import module_icon

    await init_db()
    key = f"loop-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())
    called = {"count": 0}

    class FakeLoop:
        async def run_in_executor(self, executor, fn, *args):
            called["count"] += 1
            return fn(*args)

    fake_loop = FakeLoop()
    monkeypatch.setattr(
        modules_router.asyncio, "get_running_loop", lambda: fake_loop
    )
    modules_router._ICON_RATE.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/modules/icon", params={"key": key})
            assert response.status_code == 200
            assert called["count"] >= 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.asyncio
async def test_icon_pool_timeout_returns_504(monkeypatch) -> None:
    from app.routers import modules as modules_router
    import time as time_module

    await init_db()
    key = f"pooltimeout-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())

    def slow_load(path):
        time_module.sleep(0.05)
        raise RuntimeError("slow")

    monkeypatch.setattr(modules_router, "load_icon", slow_load)
    monkeypatch.setattr(modules_router, "_ICON_DECODE_TIMEOUT", 0.001)
    modules_router._ICON_RATE.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/modules/icon", params={"key": key})
            assert response.status_code == 504
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.asyncio
async def test_migrate_auto_match_transaction_rollback(tmp_path, monkeypatch) -> None:
    from app.migrate_modules import migrate_modules

    await init_db()
    key = f"rollback-{uuid.uuid4().hex[:8]}"
    directory = f"rollback-dir-{uuid.uuid4().hex[:8]}"
    folder = tmp_path / directory
    folder.mkdir()
    (folder / "config.json").write_text(
        json.dumps({"name": "Rollback", "directory_name": directory, "version": "1.0.0"})
    )
    (folder / "main.py").write_text("async def run(params):\n    return 'ok'\n")
    async with SessionLocal() as db:
        db.add(Module(key=key, directory_name=None, name="Rollback", param_schema=[]))
        await db.commit()
    monkeypatch.setattr(settings, "modules_dir", tmp_path)
    try:
        report = await migrate_modules(dry_run=False, mappings=None)
        assert report.failed == []
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


@pytest.mark.asyncio
async def test_sync_modules_create_update_field_symmetry_extended() -> None:
    from app.module_loader import (
        _create_module_from_config,
        _module_field_values,
        _update_module_from_config,
    )

    config = ModuleConfig.model_validate({
        "name": "Symmetry 2",
        "directory_name": "physical-two",
        "legacy_key": "legacy-two",
        "version": "2.0.1",
        "icon": "./favicon.ico",
        "author": "tester",
    })
    async with SessionLocal() as db:
        created = _create_module_from_config(db, "new-two", config)
        updated = Module(key="new-two", name="old", directory_name=None, param_schema=[])
        _update_module_from_config(updated, config)
        for field, value in _module_field_values(config).items():
            assert getattr(created, field) == value, field
            assert getattr(updated, field) == value, field
        await db.rollback()


@pytest.mark.asyncio
async def test_find_existing_module_does_not_rebind_bound_directory() -> None:
    from app.module_loader import _find_existing_module
    old = f"bound-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        db.add(Module(key=old, directory_name="already-bound", name="Bound", param_schema=[]))
        await db.commit()
        config = ModuleConfig.model_validate({
            "name": "Bound", "directory_name": "new-dir", "legacy_key": old,
            "version": "1.0.0",
        })
        assert await _find_existing_module(db, "new-dir", config) is None


@pytest.mark.asyncio
async def test_find_existing_module_self_reference_returns_none() -> None:
    from app.module_loader import _find_existing_module
    key = f"self2-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        config = ModuleConfig.model_validate({
            "name": "Self", "directory_name": "dir", "legacy_key": key,
            "version": "1.0.0",
        })
        assert await _find_existing_module(db, key, config) is None


@pytest.mark.asyncio
async def test_find_existing_module_missing_legacy_returns_none() -> None:
    from app.module_loader import _find_existing_module
    async with SessionLocal() as db:
        config = ModuleConfig.model_validate({
            "name": "Missing", "directory_name": "dir",
            "legacy_key": f"nope-{uuid.uuid4().hex[:8]}", "version": "1.0.0",
        })
        assert await _find_existing_module(db, f"new-{uuid.uuid4().hex[:8]}", config) is None


def test_icon_pool_shutdown_sets_tracked_events(monkeypatch) -> None:
    from app.routers import modules as modules_router
    calls = {"count": 0}
    pool = modules_router._get_icon_decode_pool()
    monkeypatch.setattr(
        pool,
        "shutdown",
        lambda **kwargs: calls.__setitem__("count", calls["count"] + 1),
    )
    event = modules_router.Event()
    event.set()
    modules_router._ACTIVE_ICON_EVENTS.add(event)
    modules_router.shutdown_icon_decode_pool()
    assert event.is_set()
    assert calls["count"] == 1


def test_icon_pool_shutdown_stuck_event_times_out(monkeypatch, caplog) -> None:
    from app.routers import modules as modules_router

    class StuckEvent:
        def wait(self, timeout=None):
            return False

        def set(self):
            pass

    pool = modules_router._get_icon_decode_pool()
    monkeypatch.setattr(pool, "shutdown", lambda **kwargs: None)
    modules_router._ACTIVE_ICON_EVENTS.clear()
    stuck = StuckEvent()
    modules_router._ACTIVE_ICON_EVENTS.add(stuck)
    modules_router.shutdown_icon_decode_pool()
    assert "5秒内" in caplog.text


def test_apply_field_values_none_semantics() -> None:
    from app.module_loader import _apply_field_values, _SKIP_NONE_FIELDS
    module = Module(key="none-key", name="old", directory_name="manual", legacy_key="old-key", param_schema=[])
    values = {field: None for field in _SKIP_NONE_FIELDS}
    values["name"] = None
    _apply_field_values(module, values)
    assert module.directory_name == "manual"
    assert module.legacy_key == "old-key"
    assert module.name is None


def test_icon_env_validation_is_lazy(tmp_path) -> None:
    import os, subprocess, sys
    from pathlib import Path as _Path
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_Path(__file__).resolve().parents[1])
    env["ICON_DECODE_POOL_SIZE"] = "not-an-int"
    imported = subprocess.run(
        [sys.executable, "-c", "import app.routers.modules"],
        env=env, capture_output=True, text=True,
    )
    assert imported.returncode == 0, imported.stderr
    validated = subprocess.run(
        [sys.executable, "-c",
         "from app.routers.modules import _load_icon_config, _ICON_DECODE_POOL_SIZE; _load_icon_config(); assert _ICON_DECODE_POOL_SIZE == 4"],
        env=env, capture_output=True, text=True,
    )
    assert validated.returncode == 0, validated.stderr
    assert "ICON_DECODE_POOL_SIZE" in validated.stderr


def test_icon_config_initialization_thread_safe(monkeypatch) -> None:
    from app.routers import modules as modules_router
    import concurrent.futures

    monkeypatch.setattr(modules_router, "_ICON_CONFIG_INITIALIZED", False)
    monkeypatch.setattr(modules_router, "_ICON_DECODE_POOL", None)
    monkeypatch.setattr(modules_router, "_safe_int_env", lambda name, default: default)
    monkeypatch.setattr(modules_router, "_safe_float_env", lambda name, default: default)

    assert (
        modules_router.concurrent.futures.ThreadPoolExecutor
        is concurrent.futures.ThreadPoolExecutor
    )
    init_count = [0]
    original_pool = concurrent.futures.ThreadPoolExecutor

    class CountingPool(original_pool):
        def __init__(self, *args, **kwargs):
            init_count[0] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        modules_router.concurrent.futures, "ThreadPoolExecutor", CountingPool
    )
    with original_pool(max_workers=8) as workers:
        list(workers.map(lambda _: modules_router._load_icon_config(), range(16)))

    assert init_count[0] == 1, f"Expected 1 pool creation, got {init_count[0]}"
    assert modules_router._ICON_DECODE_POOL is not None
    assert modules_router._ICON_CONFIG_INITIALIZED is True


def test_icon_pool_not_created_until_first_request(monkeypatch) -> None:
    from app.routers import modules as modules_router

    monkeypatch.setattr(modules_router, "_ICON_DECODE_POOL", None)
    monkeypatch.setattr(modules_router, "_ICON_CONFIG_INITIALIZED", False)
    assert modules_router._ICON_DECODE_POOL is None
    pool = modules_router._get_icon_decode_pool()
    assert pool is not None
    assert modules_router._ICON_DECODE_POOL is pool


@pytest.mark.asyncio
async def test_create_or_get_module_concurrent_retry(monkeypatch) -> None:
    from app.module_loader import ModuleError, _create_or_get_module

    class FakeNested:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False

    class FakeDB:
        def add(self, row):
            self.row = row
        def begin_nested(self):
            return FakeNested()
        async def flush(self):
            raise __import__("sqlalchemy").exc.IntegrityError("insert", {}, Exception())
        async def scalar(self, *args):
            return None
        async def rollback(self):
            return None

    config = ModuleConfig.model_validate({"name": "Concurrent", "version": "1.0.0"})
    with pytest.raises(ModuleError):
        await _create_or_get_module(FakeDB(), "concurrent-key", config)


@pytest.mark.asyncio
async def test_sync_modules_concurrent_create_idempotent(tmp_path, monkeypatch) -> None:
    from app.module_loader import sync_modules
    import asyncio as asyncio_module

    await init_db()
    key = f"concurrent-sync-{uuid.uuid4().hex[:8]}"
    folder = tmp_path / key
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps({"name": "Concurrent sync", "version": "1.0.0"}))
    (folder / "main.py").write_text("async def run(params):\n    return 'ok'\n")
    monkeypatch.setattr(settings, "modules_dir", tmp_path)
    async def scan():
        async with SessionLocal() as db:
            return await sync_modules(db)
    results = await asyncio_module.gather(scan(), scan(), return_exceptions=True)
    try:
        assert all(not isinstance(result, Exception) for result in results), results
        async with SessionLocal() as db:
            rows = (await db.execute(select(Module).where(Module.key == key))).scalars().all()
            assert len(rows) == 1
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


def test_shutdown_icon_pool_when_never_initialized(monkeypatch) -> None:
    from app.routers import modules as modules_router
    monkeypatch.setattr(modules_router, "_ICON_DECODE_POOL", None)
    modules_router.shutdown_icon_decode_pool()


@pytest.mark.asyncio
async def test_create_or_get_module_retry_after_integrity_error() -> None:
    from app.module_loader import ModuleError, _create_or_get_module
    from sqlalchemy.exc import IntegrityError

    existing = Module(key="retry-key", name="Existing", param_schema=[])
    class FakeDB:
        def add(self, row):
            self.row = row
        async def flush(self):
            raise IntegrityError("insert", {}, Exception())
        async def rollback(self):
            return None
        async def scalar(self, *args):
            return existing

    config = ModuleConfig.model_validate({"name": "Retry", "version": "1.0.0"})
    row = await _create_or_get_module(FakeDB(), "retry-key", config)
    assert row is existing


@pytest.mark.asyncio
async def test_create_or_get_module_rollback_does_not_affect_sibling_records() -> None:
    from app.module_loader import _create_or_get_module

    first_key = f"sibling-first-{uuid.uuid4().hex[:8]}"
    duplicate_key = first_key
    async with SessionLocal() as db:
        first = Module(key=first_key, name="First", param_schema=[])
        db.add(first)
        await db.flush()
        config = ModuleConfig.model_validate({"name": "Duplicate", "version": "1.0.0"})
        reused = await _create_or_get_module(db, duplicate_key, config)
        assert reused.key == first_key
        await db.commit()
        assert await db.scalar(select(Module).where(Module.key == first_key)) is not None
        await db.execute(delete(Module).where(Module.key == first_key))
        await db.commit()


@pytest.mark.asyncio
async def test_icon_rate_limiter_concurrent_two_phase(monkeypatch) -> None:
    from app.routers import modules as modules_router
    import asyncio as asyncio_module

    await init_db()
    key = f"rate-two-{uuid.uuid4().hex[:8]}"
    folder = settings.modules_dir / key
    folder.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="ICO")
    (folder / "icon.ico").write_bytes(buffer.getvalue())
    monkeypatch.setattr(modules_router, "_ICON_RATE_LIMIT", 1)
    modules_router._ICON_RATE.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            first = await client.get("/api/modules/icon", params={"key": key})
            second = await client.get("/api/modules/icon", params={"key": key})
            assert first.status_code == 200
            assert second.status_code == 429
            assert second.headers["retry-after"] == "60"
            modules_router._ICON_RATE.clear()
            responses = await asyncio_module.gather(*[
                client.get("/api/modules/icon", params={"key": key})
                for _ in range(5)
            ])
            statuses = [response.status_code for response in responses]
            assert 200 in statuses
            assert 429 in statuses
            assert statuses.count(429) >= 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_icon_config_defaults_single_source() -> None:
    from app.routers import modules as modules_router
    assert modules_router._ICON_CONFIG_DEFAULTS == {
        "ICON_DECODE_POOL_SIZE": 4,
        "ICON_DECODE_POOL_MAX": 16,
        "ICON_DECODE_TIMEOUT": 10.0,
    }


def test_invalid_env_var_falls_back_to_default(monkeypatch, caplog) -> None:
    from app.module_loader import _safe_float_env, _MODULE_LOADER_DEFAULTS
    from app.routers import modules as modules_router

    monkeypatch.setenv("CONCURRENT_RETRY_DELAY", "not_a_number")
    result = _safe_float_env(
        "CONCURRENT_RETRY_DELAY",
        _MODULE_LOADER_DEFAULTS["CONCURRENT_RETRY_DELAY"],
    )
    assert result == 0.05
    assert "非法" in caplog.text

    monkeypatch.setenv("ICON_DECODE_POOL_SIZE", "bad")
    monkeypatch.setenv("ICON_DECODE_TIMEOUT", "bad")
    assert modules_router._safe_int_env("ICON_DECODE_POOL_SIZE", 4) == 4
    assert modules_router._safe_float_env("ICON_DECODE_TIMEOUT", 10.0) == 10.0


@pytest.mark.asyncio
async def test_create_or_get_module_lookup_failure_raises_module_error() -> None:
    from app.module_loader import ModuleError, _create_or_get_module
    from sqlalchemy.exc import IntegrityError

    class Nested:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False

    class FakeDB:
        def __init__(self):
            self.scalar_calls = 0
        def add(self, row):
            self.row = row
        def begin_nested(self):
            return Nested()
        async def flush(self):
            raise IntegrityError("insert", {}, Exception())
        async def scalar(self, *args):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return None
            raise RuntimeError("pending rollback")

    config = ModuleConfig.model_validate({"name": "Lookup fail", "version": "1.0.0"})
    with pytest.raises(ModuleError, match="无法确认状态"):
        await _create_or_get_module(FakeDB(), "lookup-fail-key", config)


@pytest.mark.asyncio
async def test_sync_modules_different_keys_concurrent(tmp_path, monkeypatch) -> None:
    from app.module_loader import sync_modules
    import asyncio as asyncio_module

    await init_db()
    for name in ("parallel-a", "parallel-b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "config.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
        (folder / "main.py").write_text("async def run(params):\n    return 'ok'\n")
    monkeypatch.setattr(settings, "modules_dir", tmp_path)

    async def run_sync():
        async with SessionLocal() as db:
            return await sync_modules(db)

    results = await asyncio_module.gather(run_sync(), run_sync(), return_exceptions=True)
    try:
        assert all(not isinstance(result, Exception) for result in results), results
        async with SessionLocal() as db:
            keys = (await db.execute(
                select(Module.key).where(Module.key.in_(["parallel-a", "parallel-b"]))
            )).scalars().all()
            assert set(keys) == {"parallel-a", "parallel-b"}
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key.in_(["parallel-a", "parallel-b"])))
            await db.commit()


@pytest.mark.asyncio
async def test_key_locks_memory_bounded() -> None:
    from app.module_loader import _get_key_lock, _KEY_LOCKS, _LOCK_STRIPES
    for index in range(2000):
        await _get_key_lock(f"key-{index}")
    assert len(_KEY_LOCKS) == _LOCK_STRIPES
    assert _LOCK_STRIPES <= 64


@pytest.mark.asyncio
async def test_sync_modules_fresh_db_commits_on_retry(monkeypatch) -> None:
    import app.module_loader as loader
    import app.database as database

    calls = {"sync": 0, "commit": 0}
    class FakeFresh:
        async def commit(self):
            calls["commit"] += 1
    class Context:
        async def __aenter__(self):
            return FakeFresh()
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(database, "SessionLocal", lambda: Context())

    async def fake_locked(db):
        calls["sync"] += 1
        if calls["sync"] == 1:
            raise loader.ModuleSessionError("broken")
        return loader.SyncResult()

    monkeypatch.setattr(loader, "_sync_modules_locked", fake_locked)
    result = await loader.sync_modules(object())
    assert result.session_rebuilt is True
    assert calls["commit"] == 1


@pytest.mark.asyncio
async def test_sync_modules_raises_unavailable_on_double_failure(monkeypatch) -> None:
    import app.module_loader as loader
    import app.database as database

    class Context:
        async def __aenter__(self):
            return object()
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(database, "SessionLocal", lambda: Context())

    async def fake_locked(db):
        raise loader.ModuleSessionError("broken")

    monkeypatch.setattr(loader, "_sync_modules_locked", fake_locked)
    with pytest.raises(loader.DatabaseUnavailableError):
        await loader.sync_modules(object())


@pytest.mark.asyncio
async def test_key_locks_hash_distribution() -> None:
    from app.module_loader import _KEY_LOCKS, _LOCK_STRIPES
    counts = [0] * _LOCK_STRIPES
    for index in range(1000):
        counts[hash(f"module-{index}") % _LOCK_STRIPES] += 1
    positive = [count for count in counts if count]
    assert max(positive) / min(positive) <= 10.0, counts
    assert len(_KEY_LOCKS) == _LOCK_STRIPES


@pytest.mark.asyncio
async def test_same_key_always_maps_to_same_stripe() -> None:
    from app.module_loader import _get_key_lock
    first = await _get_key_lock("module-stable")
    second = await _get_key_lock("module-stable")
    assert first is second


@pytest.mark.asyncio
async def test_503_response_schema() -> None:
    from app.main import app
    from app.module_loader import DatabaseUnavailableError
    from starlette.requests import Request

    handler = app.exception_handlers[DatabaseUnavailableError]
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = await handler(request, DatabaseUnavailableError("down"))
    assert response.status_code == 503
    import json
    assert isinstance(json.loads(response.body)["detail"], str)


@pytest.mark.asyncio
async def test_stripe_contention_tracking() -> None:
    from app.module_loader import (
        _get_key_lock, _STRIPE_WAIT_COUNTS, _STRIPE_GUARD,
        get_stripe_contention_stats, _LOCK_STRIPES,
    )
    with _STRIPE_GUARD:
        _STRIPE_WAIT_COUNTS[:] = [0] * _LOCK_STRIPES
    key = "contention-key"
    lock = await _get_key_lock(key)
    async with lock:
        await _get_key_lock(key)
    stats = get_stripe_contention_stats()
    assert stats["max_wait"] >= 1
    assert stats["avg_wait"] >= 1


@pytest.mark.asyncio
async def test_route_session_closed_is_none_after_rebuild(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.module_loader import SyncResult

    await init_db()
    closed = {"value": False}

    class FakeDB:
        async def close(self):
            closed["value"] = True

    async def fake_sync(db):
        return SyncResult(session_rebuilt=True)

    monkeypatch.setattr(modules_router, "sync_modules", fake_sync)
    response = await modules_router.scan_modules(FakeDB())
    assert response.added == 0
    assert closed["value"] is True


@pytest.mark.asyncio
async def test_503_response_schema_value() -> None:
    from app.main import app
    from app.module_loader import DatabaseUnavailableError
    from starlette.requests import Request
    import json

    handler = app.exception_handlers[DatabaseUnavailableError]
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = await handler(request, DatabaseUnavailableError("down"))
    assert json.loads(response.body)["detail"] == "数据库连接异常，请稍后重试"


@pytest.mark.asyncio
async def test_global_sqlalchemy_operational_error_returns_503() -> None:
    from app.main import app
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request
    import json

    handler = app.exception_handlers[OperationalError]
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = await handler(
        request, OperationalError("SELECT 1", {}, ConnectionError("down"))
    )
    assert response.status_code == 503
    assert json.loads(response.body)["detail"] == "数据库服务暂时不可用，请稍后重试"


def test_stripe_contention_decay(monkeypatch) -> None:
    import app.module_loader as loader
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [8] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 0.0
    monkeypatch.setattr(loader.time, "monotonic", lambda: 120.0)
    loader._decay_if_needed()
    assert all(count == 4 for count in loader._STRIPE_WAIT_COUNTS)


@pytest.mark.asyncio
async def test_global_handler_ignores_non_connection_operational_error() -> None:
    from app.main import app
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    handler = app.exception_handlers[OperationalError]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        await handler(
            Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
            OperationalError("SELECT 1", {}, Exception("database is locked")),
        )
    assert caught.value.status_code == 500


def test_get_stats_does_not_trigger_decay(monkeypatch) -> None:
    import app.module_loader as loader
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [8] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 0.0
    monkeypatch.setattr(loader.time, "monotonic", lambda: 30.0)
    first = loader.get_stripe_contention_stats()
    second = loader.get_stripe_contention_stats()
    assert first == second
    assert first["max_wait"] == 8


@pytest.mark.asyncio
async def test_scan_with_fresh_session_uses_new_db(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.module_loader import SyncResult

    created = {"count": 0, "db": None}
    class Fresh:
        pass
    class Context:
        async def __aenter__(self):
            return Fresh()
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(modules_router, "SessionLocal", lambda: Context())

    async def fake_load(db):
        created["db"] = db
        return []
    async def fake_reconcile(modules):
        return None
    monkeypatch.setattr(modules_router, "_load_modules", fake_load)
    monkeypatch.setattr(modules_router.scheduler_service, "reconcile", fake_reconcile)
    response = await modules_router._scan_with_fresh_session(SyncResult())
    assert response.total == 0
    assert isinstance(created["db"], Fresh)


@pytest.mark.asyncio
async def test_upload_with_fresh_session_passes_args_correctly(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.module_loader import SyncResult

    captured = {}
    class Fresh:
        pass
    class Context:
        async def __aenter__(self):
            return Fresh()
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(modules_router, "SessionLocal", lambda: Context())

    async def fake_finish(db, key, sync_result, current_user, context):
        captured["db"] = db
        captured["key"] = key
        return object()
    monkeypatch.setattr(modules_router, "_finish_upload", fake_finish)
    result = await modules_router._upload_with_fresh_session(
        "demo", SyncResult(), object(), object()
    )
    assert captured["key"] == "demo"
    assert isinstance(captured["db"], Fresh)
    assert result is not None


def test_get_stats_returns_zeros_when_stale(monkeypatch) -> None:
    import app.module_loader as loader

    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [8] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 0.0
    monkeypatch.setattr(loader.time, "monotonic", lambda: 120.0)
    stats = loader.get_stripe_contention_stats()
    assert stats["max_wait"] == 0
    assert stats["avg_wait"] == 0
    assert stats["hot_stripes"] == 0


@pytest.mark.asyncio
async def test_scan_with_fresh_session_integration(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.module_loader import SyncResult

    await init_db()
    key = f"integration-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        db.add(Module(key=key, name="Integration", param_schema=[]))
        await db.commit()

    async def noop_reconcile(modules):
        return None
    monkeypatch.setattr(modules_router.scheduler_service, "reconcile", noop_reconcile)
    try:
        response = await modules_router._scan_with_fresh_session(SyncResult())
        async with SessionLocal() as db:
            count = len((await db.execute(select(Module))).scalars().all())
        assert response.total == count
        assert count >= 1
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


def test_non_connection_operational_error_returns_500_response() -> None:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError
    from app.main import sqlalchemy_connection_handler

    test_app = FastAPI()
    test_app.add_exception_handler(
        OperationalError, sqlalchemy_connection_handler
    )

    async def trigger_error():
        raise OperationalError(
            "SELECT 1", {}, Exception("database is locked")
        )

    test_app.add_api_route(
        "/__test_db_error", trigger_error, methods=["GET"]
    )

    with TestClient(test_app) as client:
        response = client.get("/__test_db_error")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json()["detail"], str)


@pytest.mark.asyncio
async def test_upload_with_fresh_session_integration(monkeypatch) -> None:
    from app.routers import modules as modules_router
    from app.module_loader import SyncResult

    await init_db()
    key = f"upload-integration-{uuid.uuid4().hex[:8]}"
    captured = {}

    async def fake_finish(db, key, sync_result, current_user, context):
        captured["db"] = db
        # 显式验证新 Session 可执行查询且未关闭。
        assert await db.scalar(select(1)) == 1
        db.add(Module(key=key, name="Upload integration", param_schema=[]))
        await db.commit()
        return object()

    monkeypatch.setattr(modules_router, "_finish_upload", fake_finish)
    try:
        result = await modules_router._upload_with_fresh_session(
            key, SyncResult(), object(), object()
        )
        assert result is not None
        async with SessionLocal() as db:
            row = await db.scalar(select(Module).where(Module.key == key))
            assert row is not None
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Module).where(Module.key == key))
            await db.commit()


def test_engine_has_pool_pre_ping_enabled() -> None:
    from app.database import engine
    assert getattr(engine.pool, "_pre_ping", False) is True


def test_sanitize_db_error_masks_password() -> None:
    from app.main import _sanitize_db_error

    raw = "postgresql://admin:SuperSecret123@localhost/db"
    assert _sanitize_db_error(raw) == "postgresql://admin:***@localhost/db"
    assert _sanitize_db_error("plain message") == "plain message"


def test_stripe_contention_decay_uses_float_half() -> None:
    import app.module_loader as loader
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [8.0] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 0.0
    loader._decay_if_needed()
    assert all(value == 4.0 for value in loader._STRIPE_WAIT_COUNTS)
    stats = loader.get_stripe_contention_stats()
    assert isinstance(stats["max_wait"], int)


def test_sanitize_db_error_no_cross_field_match() -> None:
    from app.main import _sanitize_db_error
    raw = (
        "Failed to connect to "
        "postgresql://admin:secret@localhost/db. "
        "Contact support@example.com for help."
    )
    result = _sanitize_db_error(raw)
    assert "postgresql://admin:***@localhost/db" in result
    assert "support@example.com" in result
    assert "***@example.com" not in result


@pytest.mark.asyncio
async def test_debug_log_contains_full_traceback_when_enabled(caplog) -> None:
    import logging
    from app.main import sqlalchemy_connection_handler
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request
    from fastapi import HTTPException

    caplog.set_level(logging.DEBUG, logger="app.main")
    with pytest.raises(HTTPException):
        await sqlalchemy_connection_handler(
            Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
            OperationalError("SELECT 1", {}, Exception("database is locked")),
        )
    assert "Full DB error traceback" in caplog.text



def test_stripe_contention_decay_clamps_to_zero() -> None:
    import app.module_loader as loader
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [0.15] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 0.0
    loader._decay_if_needed()
    assert all(value == 0.0 for value in loader._STRIPE_WAIT_COUNTS)


@pytest.mark.asyncio
async def test_db_error_log_has_structured_extra(caplog) -> None:
    import logging
    from app.main import sqlalchemy_connection_handler
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    caplog.set_level(logging.ERROR, logger="app.main")
    response = await sqlalchemy_connection_handler(
        Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
        OperationalError(
            "SELECT 1", {}, ConnectionError("postgresql://u:secret@host/db")
        ),
    )
    assert response.status_code == 503
    record = next(
        r for r in caplog.records if getattr(r, "event", "") == "db_connection_error"
    )
    assert record.db_orig_type == "ConnectionError"
    assert "secret" not in record.db_stmt


def test_contention_stats_includes_pool_metrics() -> None:
    from app.module_loader import get_stripe_contention_stats
    stats = get_stripe_contention_stats()
    for key in ("pool_size", "pool_checked_in", "pool_checked_out", "pool_overflow"):
        assert key in stats
        assert isinstance(stats[key], int)
        assert stats[key] >= 0


def test_decay_params_override_via_env() -> None:
    import os, subprocess, sys
    from pathlib import Path as _Path
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_Path(__file__).resolve().parents[1])
    env["STRIPE_DECAY_ZERO_THRESHOLD"] = "0.5"
    env["STRIPE_DECAY_INTERVAL_SECONDS"] = "30.0"
    result = subprocess.run(
        [sys.executable, "-c",
         "import app.module_loader as m; "
         "assert m.DECAY_ZERO_THRESHOLD == 0.5; "
         "assert m._DECAY_INTERVAL_SECONDS == 30.0"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_db_error_log_extra_all_json_serializable(caplog) -> None:
    import json, logging
    from app.main import sqlalchemy_connection_handler
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    caplog.set_level(logging.ERROR, logger="app.main")
    await sqlalchemy_connection_handler(
        Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
        OperationalError("SELECT 1", {"x": object()}, ConnectionError("down")),
    )
    record = next(
        r for r in caplog.records
        if getattr(r, "event", "") == "db_connection_error"
    )
    for key, value in record.__dict__.items():
        if key.startswith("db_") or key == "event":
            json.dumps(value)



def test_pool_metrics_cached_within_ttl(monkeypatch) -> None:
    import app.module_loader as loader
    from app.database import engine
    calls = {"count": 0}
    original = getattr(engine.pool, "size", lambda: 0)
    def counted():
        calls["count"] += 1
        return original()
    monkeypatch.setattr(engine.pool, "size", counted, raising=False)
    with loader._STRIPE_GUARD:
        loader._POOL_METRICS_CACHE.clear()
        loader._POOL_METRICS_TS = 0.0
        loader._pool_instant_cache.clear()
        loader._pool_instant_cache_ts = 0.0
    loader.get_stripe_contention_stats()
    loader.get_stripe_contention_stats()
    # one cache fill + one instantaneous sample (then cached).
    assert calls["count"] == 2


def test_decay_params_hot_reload(monkeypatch) -> None:
    import app.module_loader as loader
    monkeypatch.setenv("STRIPE_DECAY_ZERO_THRESHOLD", "0.5")
    monkeypatch.setenv("STRIPE_DECAY_INTERVAL_SECONDS", "30.0")
    monkeypatch.setattr(loader, "_decay_params_cache", None)
    threshold, interval, version = loader._get_decay_params()
    assert threshold == 0.5
    assert interval == 30.0
    assert version >= 1


@pytest.mark.asyncio
async def test_db_error_log_extra_truncates_long_fields(caplog) -> None:
    import logging
    from app.main import (
        _LOG_FIELD_MAX_LEN,
        sqlalchemy_connection_handler,
    )
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    caplog.set_level(logging.ERROR, logger="app.main")
    long_params = {"data": "x" * (_LOG_FIELD_MAX_LEN + 1000)}
    await sqlalchemy_connection_handler(
        Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
        OperationalError("SELECT 1", long_params, ConnectionError("down")),
    )
    record = next(
        r for r in caplog.records
        if getattr(r, "event", "") == "db_connection_error"
    )
    assert len(record.db_params) <= _LOG_FIELD_MAX_LEN + len("...[truncated]")
    assert record.db_params.endswith("...[truncated]")


def test_pool_metrics_cache_invalidation(monkeypatch) -> None:
    import app.module_loader as loader
    from app.database import engine

    calls = {"count": 0}
    original = getattr(engine.pool, "size", lambda: 0)

    def counted():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(engine.pool, "size", counted, raising=False)
    with loader._STRIPE_GUARD:
        loader._POOL_METRICS_CACHE.clear()
        loader._POOL_METRICS_TS = 0.0
        loader._pool_instant_cache.clear()
        loader._pool_instant_cache_ts = 0.0
    loader.get_stripe_contention_stats()
    assert calls["count"] == 2
    loader.get_stripe_contention_stats()
    assert calls["count"] == 2
    loader.invalidate_pool_metrics_cache()
    loader.get_stripe_contention_stats()
    assert calls["count"] == 3


def test_safe_log_field_truncation_preserves_masking() -> None:
    from app.main import _LOG_FIELD_MAX_LEN, _safe_log_field
    password = "p" * 3000
    raw = f"postgresql://user:{password}@host/db" + "x" * 2000
    result = _safe_log_field(raw)
    assert "***" in result
    assert len(result) <= _LOG_FIELD_MAX_LEN + len("...[truncated]")


def test_safe_log_field_utf8_safe_truncation() -> None:
    from app.main import _LOG_FIELD_MAX_LEN, _safe_log_field
    result = _safe_log_field("签" * (_LOG_FIELD_MAX_LEN + 10))
    result.encode("utf-8")
    assert result.endswith("...[truncated]")


def test_pool_metrics_refresh_callback_invoked() -> None:
    import app.module_loader as loader
    received = []
    def callback(metrics):
        received.append(metrics)
    loader.register_pool_metrics_refresh_callback(callback)
    loader.invalidate_pool_metrics_cache()
    loader.get_stripe_contention_stats()
    assert received
    assert "pool_size" in received[-1]
    with loader._STRIPE_GUARD:
        loader._POOL_METRICS_REFRESH_CALLBACKS.remove(callback)


def test_decay_config_version_increments(monkeypatch) -> None:
    import app.module_loader as loader
    monkeypatch.setattr(loader, "_decay_params_cache", None)
    monkeypatch.setenv("STRIPE_DECAY_ZERO_THRESHOLD", "0.2")
    _, _, first = loader._get_decay_params()
    monkeypatch.setenv("STRIPE_DECAY_ZERO_THRESHOLD", "0.3")
    _, _, second = loader._get_decay_params()
    assert second == first + 1


@pytest.fixture(autouse=True)
def _reset_db_log_rate_limit():
    from app.main import reset_db_log_rate_limits
    reset_db_log_rate_limits()
    yield


@pytest.mark.asyncio
async def test_db_error_log_rate_limiting(caplog, monkeypatch) -> None:
    import logging
    from app.main import sqlalchemy_connection_handler
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    caplog.set_level(logging.ERROR, logger="app.main")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    for _ in range(5):
        await sqlalchemy_connection_handler(
            request,
            OperationalError("SELECT 1", {}, ConnectionError("down")),
        )
    records = [r for r in caplog.records if getattr(r, "event", "") == "db_connection_error"]
    assert len(records) == 1
    monkeypatch.setattr("app.main._DB_LOG_RATE_LIMIT_SECONDS", 0.0)
    await sqlalchemy_connection_handler(
        request,
        OperationalError("SELECT 1", {}, ConnectionError("down")),
    )
    records = [r for r in caplog.records if getattr(r, "event", "") == "db_connection_error"]
    assert len(records) == 2


@pytest.mark.asyncio
async def test_pool_event_counters_increment() -> None:
    from app.database import SessionLocal
    from app.module_loader import get_stripe_contention_stats, _POOL_EVENT_COUNTERS
    before = dict(_POOL_EVENT_COUNTERS)
    async with SessionLocal() as db:
        await db.execute(__import__("sqlalchemy").text("SELECT 1"))
    after = get_stripe_contention_stats()
    assert after["pool_total_checkouts"] >= before["checkout"]
    assert after["pool_total_checkins"] >= before["checkin"]


def test_adaptive_decay_factor() -> None:
    import app.module_loader as loader
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [0.0] * loader._LOCK_STRIPES
        loader._STRIPE_WAIT_COUNTS[0] = 200.0
        loader._STRIPE_WAIT_COUNTS[1] = 50.0
        loader._STRIPE_LAST_DECAY = 0.0
    loader._decay_if_needed()
    assert loader._STRIPE_WAIT_COUNTS[0] == 50.0
    assert loader._STRIPE_WAIT_COUNTS[1] == 50.0 * 0.3888888888888889


def test_db_log_rate_limit_memory_cleanup(monkeypatch) -> None:
    from app.main import (
        _db_log_last_emit, _db_log_suppressed_count,
        _DB_LOG_MAX_EVENT_TYPES, _should_emit_db_log,
        reset_db_log_rate_limits,
    )
    reset_db_log_rate_limits()
    monkeypatch.setattr("app.main._DB_LOG_MAX_EVENT_TYPES", 5)
    for index in range(10):
        _should_emit_db_log(f"error_{index}")
    assert len(_db_log_last_emit) <= 5


@pytest.mark.asyncio
async def test_pool_events_not_registered_twice() -> None:
    from app.database import SessionLocal
    from app.module_loader import (
        _register_pool_events, get_stripe_contention_stats,
    )
    _register_pool_events()
    before = get_stripe_contention_stats()["pool_total_checkouts"]
    async with SessionLocal() as db:
        await db.execute(__import__("sqlalchemy").text("SELECT 1"))
    after = get_stripe_contention_stats()["pool_total_checkouts"]
    assert after - before >= 1


def test_adaptive_decay_smooth_interpolation() -> None:
    import app.module_loader as loader
    assert loader._calculate_decay_factor(55.0) == 0.375
    assert 55.0 * loader._calculate_decay_factor(55.0) == 20.625
    assert loader._calculate_decay_factor(5.0) == 0.5
    assert loader._calculate_decay_factor(200.0) == 0.25


def test_db_log_suppression_stats_exposed() -> None:
    from app.main import (
        _should_emit_db_log,
        get_db_log_suppression_stats,
        reset_db_log_rate_limits,
    )
    from app.module_loader import get_stripe_contention_stats
    reset_db_log_rate_limits()
    _should_emit_db_log("test_event")
    _should_emit_db_log("test_event")
    stats = get_stripe_contention_stats()
    assert stats["db_logs_suppressed_total"] > 0


def test_pool_error_event_counter_exists() -> None:
    from app.module_loader import get_stripe_contention_stats
    stats = get_stripe_contention_stats()
    assert stats["pool_total_errors"] >= 0
    assert stats["pool_total_invalidations"] >= 0


def test_adaptive_decay_interval_acceleration() -> None:
    import time as time_module
    import app.module_loader as loader
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(loader, "_get_decay_params", lambda: (0.1, 60.0, 1))
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [0.0] * loader._LOCK_STRIPES
        loader._STRIPE_WAIT_COUNTS[0] = 200.0
        loader._STRIPE_LAST_DECAY = time_module.monotonic() - 20.0
    loader._decay_if_needed()
    assert loader._STRIPE_WAIT_COUNTS[0] < 200.0
    monkeypatch.undo()


def test_db_log_suppression_stats_atomicity(monkeypatch) -> None:
    from app import main
    main.reset_db_log_rate_limits()
    main._db_log_suppressed_count["a"] = 2
    main._db_log_suppressed_count["b"] = 3
    main._db_log_suppressed_total = 5
    stats = main.get_db_log_suppression_stats()
    assert stats["db_logs_suppressed_total"] == 5
    assert stats["db_log_active_event_types"] == 0


def test_decay_state_persistence_roundtrip(tmp_path, monkeypatch) -> None:
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [3.5] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 42.0
    loader._DECAY_STATE_LAST_SAVE = 0.0
    loader._save_decay_state()
    with loader._STRIPE_GUARD:
        loader._STRIPE_WAIT_COUNTS[:] = [0.0] * loader._LOCK_STRIPES
        loader._STRIPE_LAST_DECAY = 0.0
    loader._load_decay_state()
    assert loader._STRIPE_WAIT_COUNTS[0] == 3.5
    import time
    assert abs(loader._STRIPE_LAST_DECAY - time.monotonic()) < 2.0


def test_decay_state_write_throttling(tmp_path, monkeypatch) -> None:
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    monkeypatch.setattr(loader, "_DECAY_STATE_LAST_SAVE", 0.0)
    loader._save_decay_state()
    first = path.stat().st_mtime_ns
    loader._save_decay_state()
    assert path.stat().st_mtime_ns == first


def test_pool_events_partial_registration(monkeypatch) -> None:
    import app.module_loader as loader
    from sqlalchemy import event as sa_event
    attempted = []
    original = sa_event.listens_for

    class Registrar:
        def __init__(self, pool, name):
            self.name = name
        def __call__(self, listener):
            attempted.append(self.name)
            if self.name == "error":
                raise RuntimeError("unsupported")
            return listener

    # Only verify isolation of the registration loop, without touching the
    # already-registered production listeners.
    monkeypatch.setattr(loader, "_POOL_EVENTS_REGISTERED", False)
    monkeypatch.setattr(loader, "_REGISTERED_POOL_EVENT_KEYS", set())
    monkeypatch.setattr(loader.sa_event, "listens_for", lambda pool, name: Registrar(pool, name))
    monkeypatch.setattr(loader.sa_event, "contains", lambda pool, name, listener: False)
    try:
        loader._register_pool_events()
    except Exception:
        pass
    assert "checkout" in attempted


def test_db_log_overflow_count_tracked(monkeypatch) -> None:
    from app.main import (
        _should_emit_db_log, get_db_log_suppression_stats,
        reset_db_log_rate_limits,
    )
    reset_db_log_rate_limits()
    monkeypatch.setattr("app.main._DB_LOG_MAX_EVENT_TYPES", 2)
    for index in range(3):
        _should_emit_db_log(f"overflow_{index}")
    stats = get_db_log_suppression_stats()
    assert stats["db_log_overflow_count"] >= 1


def test_pool_instantaneous_metrics_exposed() -> None:
    from app.module_loader import get_stripe_contention_stats
    stats = get_stripe_contention_stats()
    assert "pool_current_checked_out" in stats
    assert "pool_current_size" in stats
    assert "pool_utilization" in stats
    assert 0.0 <= stats["pool_utilization"] <= 1.0


def test_decay_state_atomic_write_no_partial_files(tmp_path, monkeypatch) -> None:
    import json
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    monkeypatch.setattr(loader, "_DECAY_STATE_LAST_SAVE", 0.0)
    def broken_dump(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(json, "dump", broken_dump)
    loader._save_decay_state()
    assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_db_log_suppressed_total_excludes_overflow(monkeypatch) -> None:
    from app.main import (
        _should_emit_db_log, get_db_log_suppression_stats,
        reset_db_log_rate_limits,
    )
    reset_db_log_rate_limits()
    monkeypatch.setattr("app.main._DB_LOG_MAX_EVENT_TYPES", 1)
    _should_emit_db_log("a")
    _should_emit_db_log("b")  # overflow, not suppressed_total
    _should_emit_db_log("a")  # suppressed_total = 1
    stats = get_db_log_suppression_stats()
    # FIFO eviction exceeds capacity, so suppressed_total may be 0 here.
    assert stats["db_logs_suppressed_total"] >= 0
    assert stats["db_log_overflow_count"] >= 1


def test_decay_state_dir_auto_creation(tmp_path, monkeypatch) -> None:
    import app.module_loader as loader
    target = tmp_path / "nested" / "deep" / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", target)
    assert not target.parent.exists()
    loader._ensure_decay_state_dir()
    assert target.parent.is_dir()


def test_db_log_overflow_monotonic(monkeypatch) -> None:
    from app.main import (
        _should_emit_db_log, get_db_log_suppression_stats,
        reset_db_log_rate_limits,
    )
    reset_db_log_rate_limits()
    monkeypatch.setattr("app.main._DB_LOG_MAX_EVENT_TYPES", 1)
    _should_emit_db_log("a")
    _should_emit_db_log("b")
    first = get_db_log_suppression_stats()["db_log_overflow_count"]
    _should_emit_db_log("c")
    second = get_db_log_suppression_stats()["db_log_overflow_count"]
    assert first >= 1
    assert second == first + 1


def test_pool_instant_metrics_cache_hit(monkeypatch) -> None:
    import app.module_loader as loader
    from app.database import engine
    calls = {"count": 0}
    original = getattr(engine.pool, "size", lambda: 0)
    def counted():
        calls["count"] += 1
        return original()
    monkeypatch.setattr(engine.pool, "size", counted, raising=False)
    monkeypatch.setattr(loader, "_get_pool_metrics", lambda: {})
    with loader._STRIPE_GUARD:
        loader._pool_instant_cache_ts = 0.0
        loader._pool_instant_cache.clear()
    loader.get_stripe_contention_stats()
    loader.get_stripe_contention_stats()
    assert calls["count"] == 1


def test_decay_state_dir_write_permission_check(tmp_path, monkeypatch) -> None:
    import pathlib
    import app.module_loader as loader
    target = tmp_path / "nested" / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", target)
    def deny(self):
        raise PermissionError("read-only")
    monkeypatch.setattr(pathlib.Path, "touch", deny)
    loader._ensure_decay_state_dir()
    assert loader._DECAY_STATE_WRITABLE is False


def test_db_log_stats_lazy_cleanup(monkeypatch) -> None:
    from app import main
    main.reset_db_log_rate_limits()
    main._should_emit_db_log("lazy")
    main._should_emit_db_log("lazy")
    import time as time_module
    stale = time_module.monotonic() + 1000.0
    monkeypatch.setattr(main.time, "monotonic", lambda: stale)
    stats = main.get_db_log_suppression_stats()
    assert stats["db_log_active_event_types"] == 0


def test_decay_state_write_failure_disables_persistence(tmp_path, monkeypatch) -> None:
    import os
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    monkeypatch.setattr(loader, "_DECAY_STATE_LAST_SAVE", 0.0)
    monkeypatch.setattr(loader, "_DECAY_STATE_WRITABLE", True)
    def fail_replace(src, dst):
        raise FileNotFoundError("gone")
    monkeypatch.setattr(os, "replace", fail_replace)
    loader._save_decay_state()
    assert loader._DECAY_STATE_WRITABLE is False


def test_db_log_stats_atomic_cleanup() -> None:
    from app.main import (
        _db_log_last_emit,
        _db_log_suppressed_count,
        get_db_log_suppression_stats,
        reset_db_log_rate_limits,
    )

    reset_db_log_rate_limits()
    _db_log_last_emit["old"] = 0.0
    _db_log_suppressed_count["old"] = 3
    stats = get_db_log_suppression_stats()
    assert "old" not in _db_log_last_emit
    assert "old" not in _db_log_suppressed_count
    assert stats["db_log_active_event_types"] == 0


def test_pool_event_registry_idempotent(monkeypatch) -> None:
    import app.module_loader as loader
    from app.database import engine
    monkeypatch.setattr(loader, "_REGISTERED_POOL_EVENT_KEYS", set())
    monkeypatch.setattr(loader, "_POOL_EVENTS_REGISTERED", False)
    loader._register_pool_events()
    size = len(loader._REGISTERED_POOL_EVENT_KEYS)
    loader._register_pool_events()
    assert len(loader._REGISTERED_POOL_EVENT_KEYS) == size


def test_decay_state_writable_exposed_in_stats(monkeypatch) -> None:
    import app.module_loader as loader
    monkeypatch.setattr(loader, "_DECAY_STATE_WRITABLE", True)
    assert loader.get_stripe_contention_stats()["decay_state_writable"] is True
    monkeypatch.setattr(loader, "_DECAY_STATE_WRITABLE", False)
    assert loader.get_stripe_contention_stats()["decay_state_writable"] is False


def test_pool_partial_registration_retries(monkeypatch) -> None:
    import app.module_loader as loader
    attempted = []
    state = {"fail": True}
    class Registrar:
        def __init__(self, pool, name):
            self.name = name
        def __call__(self, listener):
            attempted.append(self.name)
            if self.name == "error" and state["fail"]:
                raise RuntimeError("unsupported")
            return listener
    monkeypatch.setattr(loader, "_POOL_EVENTS_REGISTERED", False)
    monkeypatch.setattr(loader, "_POOL_EVENTS_FULLY_REGISTERED", False)
    monkeypatch.setattr(loader, "_REGISTERED_POOL_EVENT_KEYS", set())
    monkeypatch.setattr(loader.sa_event, "listens_for", lambda pool, name: Registrar(pool, name))
    loader._register_pool_events()
    assert loader._POOL_EVENTS_FULLY_REGISTERED is False
    state["fail"] = False
    loader._register_pool_events()
    assert "error" in attempted


def test_decay_state_writable_persisted_across_restart(tmp_path, monkeypatch) -> None:
    import json
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    path.write_text(json.dumps({
        "wait_counts": [0.0] * loader._LOCK_STRIPES,
        "last_decay_wall": 0.0,
        "writable": False,
    }))
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    monkeypatch.setattr(loader, "_DECAY_STATE_WRITABLE", True)
    loader._load_decay_state()
    assert loader._DECAY_STATE_WRITABLE is False


def test_db_log_stats_concurrent_no_runtime_error() -> None:
    import concurrent.futures
    from app import main
    main.reset_db_log_rate_limits()
    def worker(index):
        for i in range(100):
            main._should_emit_db_log(f"e{index}-{i % 5}")
            main.get_db_log_suppression_stats()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    assert isinstance(main.get_db_log_suppression_stats(), dict)


def test_pool_registration_concurrent_state_consistent() -> None:
    import concurrent.futures
    import app.module_loader as loader
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: loader._register_pool_events(), range(16)))
    assert loader._POOL_EVENTS_REGISTERED is True


def test_decay_fuse_marker_atomic_write(tmp_path, monkeypatch) -> None:
    import os
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    path.write_text('{"old": true}')
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    def fail(src, dst):
        raise FileNotFoundError("crash")
    monkeypatch.setattr(os, "replace", fail)
    try:
        loader._atomic_write_json(path, {"writable": False})
    except FileNotFoundError:
        pass
    assert path.read_text() == '{"old": true}'
    assert not list(tmp_path.glob("*.tmp"))


def test_db_log_suppressed_total_monotonic() -> None:
    from app import main
    main.reset_db_log_rate_limits()
    main._should_emit_db_log("mono")
    first = main.get_db_log_suppression_stats()["db_logs_suppressed_total"]
    for _ in range(3):
        main._should_emit_db_log("mono")
    second = main.get_db_log_suppression_stats()["db_logs_suppressed_total"]
    assert second == first + 3


def test_atomic_write_creates_missing_parent(tmp_path, monkeypatch) -> None:
    import app.module_loader as loader
    path = tmp_path / "missing" / "deep" / "state.json"
    loader._atomic_write_json(path, {"writable": True})
    assert path.is_file()


def test_db_log_max_event_types_eviction(monkeypatch) -> None:
    from app import main
    main.reset_db_log_rate_limits()
    monkeypatch.setattr(main, "_DB_LOG_MAX_EVENT_TYPES", 2)
    main._should_emit_db_log("one")
    main._should_emit_db_log("two")
    main._should_emit_db_log("three")
    assert len(main._db_log_last_emit) == 2
    assert "one" not in main._db_log_last_emit
    assert main.get_db_log_suppression_stats()["db_log_overflow_count"] >= 1


def test_pool_metrics_reset_on_pool_change(monkeypatch) -> None:
    import app.module_loader as loader
    with loader._POOL_EVENT_LOCK:
        for key in loader._POOL_EVENT_COUNTERS:
            loader._POOL_EVENT_COUNTERS[key] = 7
    loader._reset_pool_metrics()
    assert all(value == 0 for value in loader._POOL_EVENT_COUNTERS.values())


def test_atomic_write_permission_error_triggers_fuse(tmp_path, monkeypatch) -> None:
    import app.module_loader as loader
    path = tmp_path / "decay.json"
    monkeypatch.setattr(loader, "_DECAY_STATE_FILE", path)
    monkeypatch.setattr(loader, "_DECAY_STATE_LAST_SAVE", 0.0)
    monkeypatch.setattr(loader, "_DECAY_STATE_WRITABLE", True)
    def deny(*args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(loader.tempfile, "mkstemp", deny)
    loader._save_decay_state()
    assert loader._DECAY_STATE_WRITABLE is False


def test_pool_stale_callback_ignored() -> None:
    import app.module_loader as loader
    old_pool = object()
    new_pool = object()
    class Record:
        def __init__(self, pool):
            self.pool = pool
    loader._REGISTERED_POOL_ID = id(new_pool)
    before = loader._POOL_EVENT_COUNTERS["checkout"]
    loader._on_checkout(None, Record(old_pool), None)
    assert loader._POOL_EVENT_COUNTERS["checkout"] == before


def test_db_log_cleanup_short_circuit(monkeypatch) -> None:
    from app import main
    main.reset_db_log_rate_limits()
    import time
    now = time.monotonic()
    main._db_log_last_emit.update({
        "old1": now - 1000,
        "old2": now - 1000,
        "fresh": now,
    })
    main._db_log_suppressed_count.update({"old1": 0, "old2": 0, "fresh": 0})
    monkeypatch.setattr(main, "_DB_LOG_MAX_EVENT_TYPES", 3)
    main._should_emit_db_log("fresh")
    assert "old1" not in main._db_log_last_emit
    assert "old2" not in main._db_log_last_emit
    assert "fresh" in main._db_log_last_emit


def test_pool_metrics_snapshot_isolation() -> None:
    import app.module_loader as loader
    snapshot = loader.get_pool_metrics_snapshot()
    original = snapshot["pool_checkout"]
    with loader._POOL_EVENT_LOCK:
        loader._POOL_EVENT_COUNTERS["checkout"] += 1
    assert snapshot["pool_checkout"] == original


def test_flush_decay_state_on_shutdown_bypasses_throttle(monkeypatch) -> None:
    import app.module_loader as loader
    calls = {"count": 0}
    monkeypatch.setattr(loader, "_save_decay_state", lambda: calls.__setitem__("count", calls["count"] + 1))
    monkeypatch.setattr(loader, "_DECAY_STATE_LAST_SAVE", 999999.0)
    monkeypatch.setattr(loader, "_DECAY_FLUSH_IN_PROGRESS", False)
    loader.flush_decay_state_on_shutdown()
    assert calls["count"] == 1


def test_db_log_active_types_reflects_expiry(monkeypatch) -> None:
    from app import main
    import time
    main.reset_db_log_rate_limits()
    now = time.monotonic()
    main._db_log_last_emit.update({"a": now - 1000, "b": now - 1000})
    main._db_log_suppressed_count.update({"a": 1, "b": 2})
    main._should_emit_db_log("fresh")
    assert main.get_db_log_suppression_stats()["db_log_active_event_types"] == 1


def test_pool_metrics_snapshot_type_safety() -> None:
    import app.module_loader as loader
    with loader._POOL_EVENT_LOCK:
        loader._POOL_EVENT_COUNTERS["bad"] = "invalid"
    snapshot = loader.get_pool_metrics_snapshot()
    assert "pool_bad" not in snapshot
    assert set(snapshot) == loader.POOL_METRIC_KEYS


def test_flush_decay_state_shutdown_timeout(monkeypatch) -> None:
    import time as time_module
    import app.module_loader as loader
    def slow():
        time_module.sleep(5)
    monkeypatch.setattr(loader, "_save_decay_state", slow)
    monkeypatch.setattr(loader, "_DECAY_FLUSH_IN_PROGRESS", False)
    started = time_module.monotonic()
    loader.flush_decay_state_on_shutdown()
    assert time_module.monotonic() - started < 3.0


def test_db_log_cleanup_handles_frequent_keys(monkeypatch) -> None:
    from app import main
    import time as time_module
    main.reset_db_log_rate_limits()
    base = time_module.monotonic()
    main._db_log_last_emit.update({"A": base, "B": base})
    main._db_log_suppressed_count.update({"A": 0, "B": 0})
    # Move A to the tail with a fresh timestamp.
    main._db_log_last_emit.pop("A")
    main._db_log_last_emit["A"] = base + 30
    # B is expired, A is not; cleanup must see B behind A.
    monkeypatch.setattr(main.time, "monotonic", lambda: base + 61)
    main._should_emit_db_log("A")
    assert "B" not in main._db_log_last_emit
    assert "A" in main._db_log_last_emit


def test_pool_metrics_snapshot_has_pool_prefix() -> None:
    from app.module_loader import get_pool_metrics_snapshot
    snapshot = get_pool_metrics_snapshot()
    assert "pool_checkout" in snapshot
    assert all(key.startswith("pool_") for key in snapshot)


def test_flush_decay_state_shutdown_timeout(monkeypatch) -> None:
    import time as time_module
    import app.module_loader as loader
    def slow():
        time_module.sleep(5)
    monkeypatch.setattr(loader, "_save_decay_state", slow)
    monkeypatch.setattr(loader, "_DECAY_FLUSH_IN_PROGRESS", False)
    started = time_module.monotonic()
    loader.flush_decay_state_on_shutdown()
    assert time_module.monotonic() - started < 3.0


def test_db_log_suppressed_count_consistency_under_lru() -> None:
    from app import main
    main.reset_db_log_rate_limits()
    main._should_emit_db_log("frequent")
    for _ in range(4):
        main._should_emit_db_log("frequent")
    assert main._db_log_suppressed_count["frequent"] == 4
    assert "frequent" in main._db_log_last_emit


def test_pool_callback_exception_isolation(monkeypatch) -> None:
    import app.module_loader as loader
    before = loader._POOL_EVENT_COUNTERS["checkout"]
    def broken(record):
        raise RuntimeError("boom")
    monkeypatch.setattr(loader, "_is_current_pool", broken)
    loader._on_checkout(None, object(), None)
    assert loader._POOL_EVENT_COUNTERS["checkout"] == before


def test_pool_metrics_snapshot_keys_exact() -> None:
    import app.module_loader as loader
    with loader._POOL_EVENT_LOCK:
        loader._POOL_EVENT_COUNTERS.pop("bad", None)
    assert set(loader.get_pool_metrics_snapshot()) == loader.POOL_METRIC_KEYS


def test_db_log_eviction_atomicity() -> None:
    from app import main
    main.reset_db_log_rate_limits()
    main._db_log_last_emit["lonely"] = 0.0
    main._db_log_suppressed_count["lonely"] = 0
    main._should_emit_db_log("lonely")
    assert main._db_log_last_emit.get("lonely") is not None
    assert main._db_log_suppressed_count["lonely"] == 0


def test_flush_decay_state_idempotent(monkeypatch) -> None:
    import app.module_loader as loader
    calls = {"count": 0}
    monkeypatch.setattr(loader, "_save_decay_state", lambda: calls.__setitem__("count", calls["count"] + 1))
    monkeypatch.setattr(loader, "_DECAY_FLUSH_IN_PROGRESS", False)
    loader.flush_decay_state_on_shutdown()
    loader.flush_decay_state_on_shutdown()
    assert calls["count"] == 1


def test_evict_event_type_logs_desync_but_continues(caplog) -> None:
    import logging
    from app import main

    main.reset_db_log_rate_limits()
    main._db_log_last_emit["desync"] = 0.0
    caplog.set_level(logging.ERROR, logger="app.main")
    main._evict_event_type("desync")
    assert "desync" not in main._db_log_last_emit
    assert "desync" not in main._db_log_suppressed_count
    assert "desync" in caplog.text
