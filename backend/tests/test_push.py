"""Push configuration normalization and template rendering tests."""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from app.services.push import (
    CHANNEL_SPECS,
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_TITLE_TEMPLATE,
    PushConfigError,
    _dingtalk_signed_url,
    _feishu_sign,
    normalize_push_config,
    normalize_templates,
    render_template,
    send_message,
)


def test_channel_config_validation() -> None:
    assert normalize_push_config("none", {"anything": "ignored"}) == {}
    assert normalize_push_config("bark", {"key": "abc"}) == {"key": "abc"}
    assert normalize_push_config("serverchan", {"send_key": "SCT123"}) == {
        "send_key": "SCT123"
    }
    assert normalize_push_config("pushplus", {"token": "token"}) == {"token": "token"}

    dingtalk = normalize_push_config(
        "dingtalk",
        {
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=abc",
            "secret": "SEC123",
        },
    )
    assert dingtalk["webhook"].startswith("https://oapi.dingtalk.com/")
    assert dingtalk["secret"] == "SEC123"

    feishu = normalize_push_config(
        "feishu",
        {"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/abc"},
    )
    assert feishu["webhook"].startswith("https://open.feishu.cn/")

    with pytest.raises(PushConfigError):
        normalize_push_config("telegram", {})
    with pytest.raises(PushConfigError):
        normalize_push_config("bark", {})
    with pytest.raises(PushConfigError):
        normalize_push_config(
            "dingtalk", {"webhook": "https://evil.example.com/robot"}
        )
    with pytest.raises(PushConfigError):
        normalize_push_config(
            "feishu", {"webhook": "http://open.feishu.cn/open-apis/bot/v2/hook/abc"}
        )
    with pytest.raises(PushConfigError):
        normalize_push_config("dingtalk", {"webhook": "https://oapi.dingtalk.com/"})
    assert len(CHANNEL_SPECS) == 6


def test_template_rendering_and_defaults() -> None:
    title, body = normalize_templates("", "")
    assert title == DEFAULT_TITLE_TEMPLATE
    assert body == DEFAULT_BODY_TEMPLATE
    with pytest.raises(PushConfigError):
        normalize_templates("x" * 301, "body")
    with pytest.raises(PushConfigError):
        normalize_templates("title", "x" * 8001)

    rendered = render_template(
        "{event}｜{module_name}\n{account} {status}\n{missing}",
        {
            "event": "签到成功",
            "module_name": "演示",
            "account": "ab***@example.com",
            "status": "成功",
        },
    )
    assert "签到成功｜演示" in rendered
    assert "ab***@example.com 成功" in rendered
    assert "{missing}" in rendered


def test_signature_helpers_do_not_leak_and_are_well_formed() -> None:
    timestamp, sign = _feishu_sign("top-secret")
    expected = base64.b64encode(
        hmac.new(
            f"{timestamp}\ntop-secret".encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
    ).decode("ascii")
    assert sign == expected
    assert "top-secret" not in sign

    signed = _dingtalk_signed_url(
        "https://oapi.dingtalk.com/robot/send?access_token=abc", "secret"
    )
    assert "timestamp=" in signed and "sign=" in signed
    assert "secret" not in signed


@pytest.mark.asyncio
async def test_disabled_channel_is_a_noop() -> None:
    result = await send_message("none", {}, "title", "body")
    assert result["sent"] is False
    assert result["reason"] == "未配置推送渠道"


@pytest.mark.asyncio
async def test_notify_module_renders_templates_and_respects_switch(monkeypatch) -> None:
    from sqlalchemy import delete, select

    from app.crypto import EncryptionContext, parameter_cipher
    from app.database import SessionLocal, init_db
    from app.models import Module, PushConfig
    from app.services import push as push_module
    from app.services.bootstrap import initialize_modules, seed_admin

    await init_db()
    await seed_admin()
    await initialize_modules()

    sent: list[dict] = []

    async def fake_send(channel, config, title, body, **_kwargs):
        sent.append(
            {"channel": channel, "config": config, "title": title, "body": body}
        )
        return {"sent": True, "channel": channel}

    monkeypatch.setattr(push_module, "send_message", fake_send)

    async with SessionLocal() as db:
        module = await db.scalar(select(Module).where(Module.key == "moyu_energy"))
        assert module is not None
        module.push_enabled = True
        row = await db.get(PushConfig, 1)
        if row is None:
            row = PushConfig(id=1)
            db.add(row)
        row.channel = "bark"
        row.config_encrypted = parameter_cipher.encrypt(
            {"key": "test-key"},
            EncryptionContext(1, "__push_config__"),
        )
        row.title_template = "{event}｜{module_name}"
        row.body_template = "{account}/{status}/{result}\n{details}"
        await db.commit()
        module_id = module.id

    try:
        result = await push_module.notify_module(
            module_id,
            event="partial_failure",
            status_text="部分失败",
            result="2 个账号中 1 个成功、1 个失败",
            account="2 个账号",
            details="- 账号 1：成功",
        )
        assert result["sent"] is True
        assert sent[-1]["title"] == "多账号部分失败｜摸鱼能量签到（多账号）"
        assert "2 个账号/部分失败" in sent[-1]["body"]
        assert "- 账号 1：成功" in sent[-1]["body"]

        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            module.push_enabled = False
            await db.commit()
        skipped = await push_module.notify_module(
            module_id,
            event="success",
            status_text="成功",
            result="签到成功",
        )
        assert skipped["sent"] is False
        assert skipped["reason"] == "模块推送未启用"
        assert len(sent) == 1
    finally:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is not None:
                module.push_enabled = False
            await db.execute(delete(PushConfig).where(PushConfig.id == 1))
            await db.commit()


@pytest.mark.asyncio
async def test_corrupt_push_config_is_not_silently_overwritten() -> None:
    from app.database import SessionLocal, init_db
    from app.models import PushConfig
    from app.services.bootstrap import seed_admin
    from app.services.push import PushConfigError, save_push_config

    await init_db()
    await seed_admin()
    async with SessionLocal() as db:
        row = await db.get(PushConfig, 1)
        if row is None:
            row = PushConfig(id=1)
            db.add(row)
        row.channel = "bark"
        row.config_encrypted = "not-a-valid-v1-or-v2-token"
        await db.commit()
        original = row.config_encrypted
    with pytest.raises(PushConfigError):
        async with SessionLocal() as db:
            await save_push_config(
                db,
                "bark",
                {"key": "new-key"},
                "{event}",
                "{result}",
            )
    async with SessionLocal() as db:
        row = await db.get(PushConfig, 1)
        assert row is not None
        assert row.config_encrypted == original
