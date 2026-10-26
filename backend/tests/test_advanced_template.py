"""Tests for the advanced multi-account module template."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.module_loader import parse_config_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "templates" / "advanced_checkin"
PACKAGE = "_advanced_checkin_template_test"


def load_template():
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        TEMPLATE_DIR / "main.py",
        submodule_search_locations=[str(TEMPLATE_DIR)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_advanced_template_simulation() -> None:
    module = load_template()
    try:
        config = parse_config_file(TEMPLATE_DIR / "config.json")
        assert config.name.startswith("Acme")
        assert config.multi_account is True
        assert config.default_start_time == "09:00"
        assert config.default_end_time == "11:00"
        assert config.default_repeat_cycle == "daily"
        assert len(config.params) == 7
        assert any(param.account_label for param in config.params)
        assert not any(param.key.startswith("push") for param in config.params)

        result = await module.run(
            {
                "simulate": True,
                "account": "demo@example.com",
                "password": "not-a-real-password",
                "cookie": "session=expired",
                "max_retries": 2,
                "request_timeout": 10,
            }
        )
        assert result["success"] is True
        assert result["auth_refreshed"] is True
        assert result["simulated"] is True
        assert result["points"] == 12
        assert result["request_count"] == 3
        assert "push" not in result
    finally:
        for name in list(sys.modules):
            if name == PACKAGE or name.startswith(PACKAGE + "."):
                sys.modules.pop(name, None)


@pytest.mark.asyncio
async def test_advanced_template_real_mode_requires_credentials() -> None:
    module = load_template()
    try:
        result = await module.run(
            {
                "simulate": False,
                "api_base": "https://api.example.com",
                "account": "",
                "password": "",
                "cookie": "",
            }
        )
        assert result["success"] is False
        assert "配置错误" in result["message"]
        assert "push" not in result
    finally:
        for name in list(sys.modules):
            if name == PACKAGE or name.startswith(PACKAGE + "."):
                sys.modules.pop(name, None)
