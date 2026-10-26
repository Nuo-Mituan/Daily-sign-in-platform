"""Unit tests for crypto, scheduling, account normalization and module loading."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.crypto import EncryptionContext, ParameterCipher, ParameterDecryptionError, mask_secret
from app.module_loader import (
    MAX_ACCOUNTS,
    ModuleConfigError,
    account_display,
    load_runner,
    normalize_accounts,
    parse_config_file,
    unload_runner,
    validate_and_normalize_params,
)
from app.scheduling import (
    ScheduleError,
    midpoint_scheduled_at,
    next_occurrence,
    next_period_start,
    next_plan_at,
    normalize_legacy_cycle,
    period_start_for,
    random_scheduled_at,
    schedule_window,
    validate_schedule,
)
from app.security import hash_password, verify_password

MODULES_DIR = Path(__file__).resolve().parents[2] / "modules"
TZ = ZoneInfo("Asia/Shanghai")


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("S3cure-password!")
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password("S3cure-password!", hashed)
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("S3cure-password!", "malformed")


def test_parameter_cipher_v2_roundtrip_and_aad() -> None:
    cipher = ParameterCipher("test-secret-key")
    context = EncryptionContext(user_id=1, module_key="demo_checkin")
    payload = {"cookie": "SESSDATA=中文; token=abc", "retries": 3, "notify": True}
    token = cipher.encrypt(payload, context)
    assert token.startswith("v2:")
    assert token != str(payload)
    assert cipher.decrypt(token, context) == payload
    assert cipher.is_v2(token)

    # AAD binds owner/module/index.  Moving a ciphertext to another record fails.
    with pytest.raises(ParameterDecryptionError):
        cipher.decrypt(token, EncryptionContext(2, "demo_checkin"))
    with pytest.raises(ParameterDecryptionError):
        cipher.decrypt(token, EncryptionContext(1, "another_module"))

    with pytest.raises(ParameterDecryptionError):
        ParameterCipher("another-secret").decrypt(token, context)

    accounts = [
        {"id": "a1", "label": "主账号", "params": {"cookie": "secret-one"}},
        {"id": "a2", "label": "", "params": {"cookie": "secret-two"}},
    ]
    account_token = cipher.encrypt_accounts(accounts, context)
    assert account_token.startswith("v2:")
    decrypted, upgraded = cipher.decrypt_accounts(account_token, context)
    assert decrypted == accounts
    assert upgraded is False
    # Swapping inner account ciphertexts invalidates the per-index AAD.
    from dataclasses import replace

    outer = cipher.decrypt_any(
        account_token, replace(context, account_index=-1)
    )
    outer[0], outer[1] = outer[1], outer[0]
    tampered = cipher.encrypt_any(
        outer, replace(context, account_index=-1)
    )
    with pytest.raises(ParameterDecryptionError):
        cipher.decrypt_accounts(tampered, context)


def test_parameter_cipher_v1_compatibility_and_masking() -> None:
    secret = "legacy-secret"
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    from cryptography.fernet import Fernet

    legacy = Fernet(legacy_key).encrypt(
        json.dumps({"account": "a@example.com"}).encode()
    ).decode()
    cipher = ParameterCipher(secret)
    context = EncryptionContext(1, "demo_checkin")
    assert cipher.is_v2(legacy) is False
    assert cipher.decrypt(legacy, context) == {"account": "a@example.com"}
    assert mask_secret("abcdefgh123456") == "abcd****3456"
    assert mask_secret("short") == "****"


def test_schedule_validation_and_five_cycles() -> None:
    assert validate_schedule("08:00", "10:00", "daily") == (
        "08:00",
        "10:00",
        "daily",
        "",
    )
    assert validate_schedule("08:00", "10:00", "weekly", "5") == (
        "08:00",
        "10:00",
        "weekly",
        "5",
    )
    assert validate_schedule("08:00", "10:00", "monthly_15") == (
        "08:00",
        "10:00",
        "monthly_15",
        "",
    )
    assert validate_schedule("08:00", "10:00", "monthly", "28")[3] == "28"
    assert validate_schedule("08:00", "10:00", "yearly", "2-29")[3] == "2-29"

    # Legacy cycles are accepted only for migration/config compatibility and
    # normalized to the new monthly-1st representation.
    assert normalize_legacy_cycle("half_month", "") == ("monthly", "1")
    assert normalize_legacy_cycle("quarterly", "") == ("monthly", "1")
    assert validate_schedule("08:00", "10:00", "half_month")[2:] == ("monthly", "1")

    with pytest.raises(ScheduleError):
        validate_schedule("9:00", "10:00", "daily")
    with pytest.raises(ScheduleError):
        validate_schedule("10:00", "10:00", "daily")
    with pytest.raises(ScheduleError):
        validate_schedule("11:00", "10:00", "daily")
    with pytest.raises(ScheduleError):
        validate_schedule("08:00", "10:00", "fortnightly")
    with pytest.raises(ScheduleError):
        validate_schedule("25:00", "26:00", "daily")
    for cycle, sub in [
        ("weekly", "0"),
        ("weekly", "8"),
        ("monthly", "0"),
        ("monthly", "29"),
        ("yearly", "2-30"),
        ("yearly", "13-1"),
        ("yearly", "bad"),
    ]:
        with pytest.raises(ScheduleError):
            validate_schedule("08:00", "10:00", cycle, sub)

    day = date(2026, 10, 18)  # Sunday
    assert period_start_for("daily", day) == day
    assert period_start_for("weekly", day, "7") == day
    assert period_start_for("weekly", day, "1") == date(2026, 10, 12)
    assert period_start_for("monthly_15", day) == date(2026, 10, 15)
    assert period_start_for("monthly_15", date(2026, 10, 10)) == date(
        2026, 9, 15
    )
    assert period_start_for("monthly", day, "1") == date(2026, 10, 1)
    assert period_start_for("monthly", day, "28") == date(2026, 9, 28)
    assert period_start_for("yearly", day, "10-1") == date(2026, 10, 1)
    assert period_start_for("yearly", day, "12-31") == date(2025, 12, 31)
    assert period_start_for("yearly", date(2026, 3, 1), "2-29") == date(
        2024, 2, 29
    )

    assert next_period_start("daily", date(2026, 10, 18)) == date(2026, 10, 19)
    assert next_period_start("weekly", date(2026, 10, 12), "1") == date(
        2026, 10, 19
    )
    assert next_period_start("monthly_15", date(2026, 10, 15)) == date(
        2026, 11, 15
    )
    assert next_period_start("monthly", date(2026, 10, 28), "28") == date(
        2026, 11, 28
    )
    assert next_period_start("yearly", date(2026, 1, 1), "1-1") == date(
        2027, 1, 1
    )
    assert next_period_start("yearly", date(2024, 2, 29), "2-29") == date(
        2028, 2, 29
    )
    assert next_occurrence("weekly", date(2026, 10, 18), "5") == date(
        2026, 10, 23
    )
    assert next_occurrence("yearly", date(2026, 1, 1), "2-29") == date(
        2028, 2, 29
    )


def test_schedule_windows_and_random_generation() -> None:
    start, end = schedule_window(date(2026, 10, 18), "09:00", "10:00", TZ)
    assert start.hour == 9 and end.hour == 10
    midpoint = midpoint_scheduled_at(date(2026, 10, 18), "09:00", "10:00", TZ)
    assert midpoint == datetime(2026, 10, 18, 1, 30, tzinfo=timezone.utc)

    generated = random_scheduled_at(
        date(2026, 10, 18),
        "09:00",
        "10:00",
        TZ,
        now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
    )
    assert generated is not None
    local = generated.astimezone(TZ)
    assert local.date() == date(2026, 10, 18)
    assert (local.hour, local.minute) >= (9, 0)
    assert (local.hour, local.minute) <= (10, 0)

    after_end = random_scheduled_at(
        date(2026, 10, 18),
        "09:00",
        "10:00",
        TZ,
        now=datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc),
    )
    assert after_end is None

    plan = next_plan_at(
        "daily",
        TZ,
        now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
    )
    assert plan == datetime(2026, 10, 19, 0, 0, tzinfo=TZ)
    weekly_plan = next_plan_at(
        "weekly",
        TZ,
        now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
        repeat_sub_value="7",
    )
    assert weekly_plan == datetime(2026, 10, 25, 0, 0, tzinfo=TZ)
    monthly_plan = next_plan_at(
        "monthly",
        TZ,
        now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
        repeat_sub_value="28",
    )
    assert monthly_plan == datetime(2026, 10, 28, 0, 0, tzinfo=TZ)
    leap_plan = next_plan_at(
        "yearly",
        TZ,
        now=datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc),
        repeat_sub_value="2-29",
    )
    assert leap_plan == datetime(2028, 2, 29, 0, 0, tzinfo=TZ)


def test_demo_module_config_and_params() -> None:
    config = parse_config_file(MODULES_DIR / "demo_checkin" / "config.json")
    assert config.default_start_time == "09:00"
    assert config.default_end_time == "11:00"
    assert config.default_repeat_cycle == "daily"
    assert config.default_repeat_sub_value == ""
    assert config.multi_account is False
    assert len(config.params) == 6
    password_spec = next(param for param in config.params if param.key == "password")
    assert password_spec.sensitive is True

    normalized = validate_and_normalize_params(
        config,
        {
            "account": "demo@example.com",
            "password": "secret",
            "server": "global",
            "mode": "success",
            "retries": "2",
            "verbose": "true",
        },
    )
    assert normalized["server"] == "global"
    assert normalized["retries"] == 2
    assert normalized["verbose"] is True

    with pytest.raises(ModuleConfigError) as exc_info:
        validate_and_normalize_params(config, {})
    message = str(exc_info.value)
    assert "账号" in message
    assert "密码" in message
    # server has a default ("cn"), so it is not reported as missing.
    assert "服务器" not in message

    defaults = validate_and_normalize_params(
        config, {"account": "demo", "password": "secret"}
    )
    assert defaults["server"] == "cn"
    assert defaults["mode"] == "success"
    assert defaults["verbose"] is True
    assert defaults["retries"] == 1

    with pytest.raises(ModuleConfigError):
        validate_and_normalize_params(
            config,
            {"account": "demo", "password": "secret", "server": "not-a-server"},
        )
    with pytest.raises(ModuleConfigError):
        validate_and_normalize_params(
            config,
            {"account": "demo", "password": "secret", "retries": 99},
        )


def test_legacy_cron_config_derives_window(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "name": "Legacy",
                "description": "legacy cron config",
                "default_cron": "30 9 * * *",
                "params": [],
            }
        ),
        encoding="utf-8",
    )
    config = parse_config_file(path)
    assert config.default_start_time == "09:30"
    assert config.default_end_time == "10:30"
    assert config.default_repeat_cycle == "daily"
    assert config.default_repeat_sub_value == ""
    assert config.multi_account is False


def test_legacy_repeat_cycle_config_normalizes(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "name": "Legacy Cycle",
                "description": "old repeat cycle",
                "default_repeat_cycle": "quarterly",
                "params": [],
            }
        ),
        encoding="utf-8",
    )
    config = parse_config_file(path)
    assert config.default_repeat_cycle == "monthly"
    assert config.default_repeat_sub_value == "1"


def test_multi_account_normalization_and_relative_import() -> None:
    config = parse_config_file(MODULES_DIR / "moyu_energy" / "config.json")
    assert config.multi_account is True
    assert config.default_start_time == "08:00"
    assert config.default_end_time == "10:00"

    accounts = normalize_accounts(
        config,
        [
            {
                "id": "main",
                "label": "主账号",
                "params": {
                    "cookie": "SESSDATA=abcdefgh123456; bili_jct=xyz",
                    "target_level": 3,
                    "verbose": False,
                },
            },
            {
                "id": "alt",
                "label": "",
                "params": {
                    "cookie": "SESSDATA=zyxwvu987654; bili_jct=abc",
                    "target_level": "5",
                    "verbose": "false",
                },
            },
        ],
    )
    assert [item["id"] for item in accounts] == ["main", "alt"]
    assert accounts[0]["label"] == "主账号"
    assert account_display(config, accounts[0]) == "主账号"
    masked = account_display(config, accounts[1])
    assert "***" in masked
    assert "zyxwvu987654" not in masked
    assert accounts[1]["params"]["target_level"] == 5
    assert accounts[1]["params"]["verbose"] is False

    with pytest.raises(ModuleConfigError):
        normalize_accounts(config, [])
    with pytest.raises(ModuleConfigError):
        normalize_accounts(
            config,
            [{"id": "bad", "label": "", "params": {"target_level": 2}}],
        )
    many = [
        {
            "id": f"a{index}",
            "label": "",
            "params": {"cookie": f"cookie-{index}", "target_level": 2},
        }
        for index in range(MAX_ACCOUNTS + 1)
    ]
    with pytest.raises(ModuleConfigError):
        normalize_accounts(config, many)

    runner = load_runner("moyu_energy")
    try:
        assert callable(runner.run)
        assert runner.module.__name__.startswith("_checkin_pkg_moyu_energy_")
    finally:
        unload_runner(runner)
    assert all(not name.startswith(runner.name) for name in __import__("sys").modules)
