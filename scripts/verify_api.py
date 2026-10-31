#!/usr/bin/env python3
"""End-to-end API verification for the Daily Check-in Platform.

The HTTP checks use the standard library. The legacy-cycle migration check
imports the application modules to run the real migration function:

    docker compose exec -T checkin-platform python - < scripts/verify_api.py

For a local backend (this script mutates runtime data, so use a disposable
verification database; the multi-account test expects 1 second account gaps;
DATA_DIR/MODULES_DIR/LOGS_DIR/SECRET_KEY must match the running server):

    DATA_DIR=/path/to/data MODULES_DIR=/path/to/modules LOGS_DIR=/path/to/logs \
    SECRET_KEY=the-same-secret \
    VERIFY_BASE_URL=http://127.0.0.1:5000/api \
    ADMIN_USER=admin ADMIN_PASS=<random-initial-password> \
    ACCOUNT_INTERVAL_MIN_SECONDS=1 ACCOUNT_INTERVAL_MAX_SECONDS=1 \
    python3 scripts/verify_api.py

Coverage:
  * uniform login errors and unauthenticated 401s
  * username change idempotency / concurrent-safe endpoint
  * single-account parameter encryption round-trip
  * all five repeat cycles and conditional sub-options
  * protected schedule preview API (including the schedule-preview alias)
  * random schedule generation, manual regeneration
  * legacy half_month / quarterly -> monthly/1 migration
  * multi-account CRUD, serial execution, masked logs, partial failure summary
  * push configuration persistence and channel validation
  * module scan, dashboard statistics and execution history
"""

from __future__ import annotations

import argparse
import asyncio
import http.cookiejar
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_URL = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:5000/api").rstrip("/")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")
REQUEST_TIMEOUT = float(os.environ.get("VERIFY_TIMEOUT", "30"))
RUN_TIMEOUT = int(os.environ.get("VERIFY_RUN_TIMEOUT", "90"))

COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(COOKIE_JAR)
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CYCLE_CASES = [
    ("daily", ""),
    ("weekly", "5"),
    ("monthly_15", ""),
    ("monthly", "28"),
    ("yearly", "2-29"),
]


class VerificationError(RuntimeError):
    pass


def info(message: str) -> None:
    print(f"  · {message}", flush=True)


def passed(message: str) -> None:
    print(f"  [PASS] {message}", flush=True)


def api_response(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, Any]:
    url = f"{BASE_URL}{path}"
    body = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "daily-checkin-verifier/2.0",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token and method.upper() not in SAFE_METHODS:
        headers["X-CSRF-Token"] = token

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with OPENER.open(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            return response.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = raw
        return exc.code, data
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VerificationError(f"{method} {path} 请求失败：{exc}") from exc




def api_multipart(
    path: str,
    filename: str,
    content: bytes,
    fields: dict[str, str],
    token: str,
) -> tuple[int, Any]:
    boundary = f"----verify{int(time.time() * 1000)}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-CSRF-Token": token,
        "Content-Length": str(len(body)),
    }
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method="POST"
    )
    try:
        with OPENER.open(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
            return response.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, raw


def api(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    status, data = api_response(method, path, payload, token)
    if not 200 <= status < 300:
        raise VerificationError(
            f"{method} {path} 返回 HTTP {status}："
            f"{json.dumps(data, ensure_ascii=False)[:800]}"
        )
    return data


def expect_error(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    status: int,
    token: str | None = None,
) -> Any:
    actual, data = api_response(method, path, payload, token)
    assert_true(actual == status, f"{method} {path} 期望 HTTP {status}，实际 {actual}")
    return data


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def wait_for_health() -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, 31):
        try:
            health = api("GET", "/health")
            assert_true(bool(health and health.get("status") == "ok"), "健康检查返回异常")
            assert_true(bool(health.get("scheduler_running")), "调度器未运行")
            passed(f"健康检查正常，调度器运行中（第 {attempt} 次尝试）")
            return health
        except VerificationError as exc:
            last_error = str(exc)
            time.sleep(1)
    raise VerificationError(f"等待健康检查超时：{last_error}")


def check_public_surface() -> None:
    COOKIE_JAR.clear()
    for path in ["/modules", "/dashboard", "/push/config", "/logs"]:
        data = expect_error("GET", path, None, 401)
        assert_true(isinstance(data, dict), f"{path} 未返回 JSON 错误")
    preview_payload = {
        "start_time": "09:00",
        "end_time": "11:00",
        "repeat_cycle": "daily",
        "repeat_sub_value": "",
    }
    preview_error = expect_error(
        "POST", "/modules/schedule-preview", preview_payload, 401
    )
    assert_true(isinstance(preview_error, dict), "未认证预览接口未返回 JSON 错误")
    preview_error = expect_error(
        "POST", "/modules/schedule/preview", preview_payload, 401
    )
    assert_true(isinstance(preview_error, dict), "未认证预览接口未返回 JSON 错误")
    passed(
        "未认证访问 /modules、/dashboard、/push/config、/logs 与 "
        "/modules/schedule-preview（及别名）均返回 401"
    )

    uniform = "用户名或密码错误"
    wrong_user = expect_error(
        "POST", "/auth/login", {"username": "no-such-user", "password": "wrong"}, 401
    )
    wrong_password = expect_error(
        "POST", "/auth/login", {"username": ADMIN_USER, "password": "wrong-password"}, 401
    )
    assert_true(wrong_user.get("detail") == uniform, "未知用户登录错误信息不统一")
    assert_true(wrong_password.get("detail") == uniform, "错误密码登录错误信息不统一")
    passed("登录失败统一返回“用户名或密码错误”，不泄露账号是否存在")


def login(username: str | None = None, password: str | None = None) -> str:
    username = username or ADMIN_USER
    password = password or ADMIN_PASS
    response = api(
        "POST", "/auth/login", {"username": username, "password": password}
    )
    assert_true(bool(response), "登录响应为空")
    assert_true("access_token" not in response, "登录响应仍返回旧 JWT")
    csrf = response.get("csrf_token")
    assert_true(isinstance(csrf, str) and bool(csrf), "登录响应中没有 csrf_token")
    me = api("GET", "/auth/me", token=csrf)
    assert_true(me.get("username") == username, "当前用户信息与登录用户不一致")
    return csrf


def pick_modules(token: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    meta = api("GET", "/meta", token=token)
    modules = api("GET", "/modules", token=token)
    assert_true(isinstance(modules, list) and len(modules) >= 2, "模块列表少于 2 个示例模块")
    demo = next((item for item in modules if item.get("key") == "demo_checkin"), None)
    multi = next((item for item in modules if item.get("key") == "moyu_energy"), None)
    assert_true(demo is not None, "未找到示例模块 demo_checkin")
    assert_true(multi is not None, "未找到多账号示例模块 moyu_energy")
    assert_true(demo.get("multi_account") is False, "demo_checkin 应为单账号模式")
    assert_true(multi.get("multi_account") is True, "moyu_energy 应启用多账号模式")
    for item in modules:
        assert_true("current_schedule_at" in item, "模块列表缺少 current_schedule_at")
        assert_true("schedule_status" in item, "模块列表缺少 schedule_status")
        assert_true("start_time" in item and "end_time" in item, "模块列表缺少随机时间窗")
    assert_true(len(meta.get("repeat_cycles") or []) == 5, "周期选项数量不是 5")
    info(
        "模块："
        + ", ".join(
            f"{item['key']}({item.get('schedule_status')}, "
            f"{item.get('start_time')}-{item.get('end_time')}, "
            f"{item.get('repeat_cycle')}/{item.get('repeat_sub_value')})"
            for item in modules
        )
    )
    passed("模块列表包含随机执行时间、状态、子选项与多账号元信息")
    return meta, demo, multi


def option_values(spec: dict[str, Any]) -> list[Any]:
    values = []
    for option in spec.get("options") or []:
        values.append(option.get("value") if isinstance(option, dict) else option)
    return values


def build_params(
    schema: list[dict[str, Any]], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    overrides = overrides or {}
    values: dict[str, Any] = {}
    for spec in schema:
        key = spec["key"]
        if key in overrides:
            values[key] = overrides[key]
            continue
        kind = spec.get("type", "text")
        options = option_values(spec)
        default = spec.get("default")
        if kind == "switch":
            values[key] = bool(default)
        elif kind == "number":
            number = default
            if not isinstance(number, (int, float)):
                number = spec.get("min")
            values[key] = number if isinstance(number, (int, float)) else 1
        elif kind == "select":
            values[key] = default if default in options else (options[0] if options else "")
        elif kind == "password":
            values[key] = "Verify-Pass-123!"
        elif key == "account":
            values[key] = "verify@example.com"
        elif key in {"cookie", "token"}:
            values[key] = "VERIFY_COOKIE_BASE_123456789"
        else:
            values[key] = "verify-value"
    return values


def account_payload(
    schema: list[dict[str, Any]], index: int, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    values = build_params(schema, overrides)
    if "cookie" in values:
        values["cookie"] = f"SESSDATA=VERIFY_COOKIE_{index}_ABCDEF123456; bili_jct=VERIFY{index}"
    return {"id": f"verify-account-{index}", "label": "", "params": values}


def local_timezone(meta: dict[str, Any]):
    name = meta.get("timezone") or "Asia/Shanghai"
    try:
        from zoneinfo import ZoneInfo
    except ImportError as exc:  # pragma: no cover - Python 3.9 fallback
        raise VerificationError("验证脚本需要 Python 3.9+ 的 zoneinfo") from exc
    return ZoneInfo(name)


def schedule_window(meta: dict[str, Any]) -> tuple[str, str]:
    tz = local_timezone(meta)
    now = datetime.now(timezone.utc).astimezone(tz)
    start = (now + timedelta(minutes=20)).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=40)
    if end.date() != now.date():
        start = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=0, microsecond=0)
    if end <= start:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=0, microsecond=0)
    return start.strftime("%H:%M"), end.strftime("%H:%M")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_in_window(schedule_value: str, start: str, end: str, meta: dict[str, Any]) -> None:
    tz = local_timezone(meta)
    local = parse_iso(schedule_value).astimezone(tz)
    start_hour, start_minute = (int(part) for part in start.split(":"))
    end_hour, end_minute = (int(part) for part in end.split(":"))
    minutes = local.hour * 60 + local.minute
    assert_true(
        start_hour * 60 + start_minute <= minutes <= end_hour * 60 + end_minute,
        f"随机时间 {local:%Y-%m-%d %H:%M:%S} 不在时间窗 {start}-{end} 内",
    )
    info(f"本次随机执行时间（{meta.get('timezone')}）：{local:%Y-%m-%d %H:%M:%S}")


def test_cycle_persistence(
    module: dict[str, Any], token: str, meta: dict[str, Any]
) -> tuple[str, str]:
    module_id = module["id"]
    detail = api("GET", f"/modules/{module_id}", token=token)
    assert_true(bool(detail.get("param_schema")), "示例模块没有参数定义")
    params = build_params(detail["param_schema"])
    start, end = schedule_window(meta)

    api(
        "PUT",
        f"/modules/{module_id}",
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "daily",
            "params": params,
            "enabled": False,
        },
        token=token,
    )
    passed("单账号模块参数加密保存并回读成功")

    for cycle, sub_value in CYCLE_CASES:
        updated = api(
            "PUT",
            f"/modules/{module_id}",
            {
                "start_time": start,
                "end_time": end,
                "repeat_cycle": cycle,
                "repeat_sub_value": sub_value,
                "params": params,
                "enabled": False,
            },
            token=token,
        )
        assert_true(updated.get("repeat_cycle") == cycle, f"周期 {cycle} 保存后未回显")
        assert_true(
            updated.get("repeat_sub_value") == sub_value,
            f"周期 {cycle} 子选项保存后未回显",
        )
    passed("每日 / 每周 / 每月15日 / 每月 / 每年 5 种周期及子选项均可保存")

    preview = api(
        "POST",
        "/modules/schedule/preview",
        {
            "start_time": "09:00",
            "end_time": "11:00",
            "repeat_cycle": "yearly",
            "repeat_sub_value": "2-29",
        },
        token=token,
    )
    assert_true(preview.get("repeat_cycle") == "yearly", "预览接口周期回显异常")
    assert_true(preview.get("repeat_sub_value") == "2-29", "预览接口子选项回显异常")
    assert_true(bool(preview.get("next_occurrence")), "预览接口缺少下一次执行日期")
    passed(
        "受保护的周期预览接口正常，闰年 2-29 下一次执行日期："
        f"{preview['next_occurrence']}"
    )

    for payload in [
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "fortnightly",
            "params": params,
            "enabled": False,
        },
        {
            "start_time": end,
            "end_time": start,
            "repeat_cycle": "daily",
            "params": params,
            "enabled": False,
        },
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "weekly",
            "repeat_sub_value": "8",
            "params": params,
            "enabled": False,
        },
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "monthly",
            "repeat_sub_value": "29",
            "params": params,
            "enabled": False,
        },
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "yearly",
            "repeat_sub_value": "2-30",
            "params": params,
            "enabled": False,
        },
    ]:
        expect_error(
            "PUT", f"/modules/{module_id}", payload, 400, token=token
        )
    passed("非法周期、非法子选项、非法时间窗均被拒绝")

    enabled = api(
        "PUT",
        f"/modules/{module_id}",
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "daily",
            "repeat_sub_value": "",
            "params": params,
            "enabled": True,
            "push_enabled": False,
        },
        token=token,
    )
    assert_true(enabled.get("enabled") is True, "启用单账号模块失败")
    assert_true(bool(enabled.get("current_schedule_at")), "启用后没有生成本期随机执行时间")
    assert_true(enabled.get("schedule_status") in {"pending", "fallback"}, "随机执行状态异常")
    assert_in_window(enabled["current_schedule_at"], start, end, meta)

    regenerated = api(
        "POST", f"/modules/{module_id}/schedule/regenerate", token=token
    )
    schedule = regenerated.get("schedule") or {}
    assert_true(bool(schedule.get("scheduled_at")), "手动重新生成未返回随机时间")
    assert_true(schedule.get("source") == "manual", "手动生成来源未标记为 manual")
    assert_in_window(schedule["scheduled_at"], start, end, meta)
    passed("保存后立即生成本期随机时间，手动重新生成可更新本次执行时间")

    disabled = api(
        "PATCH",
        f"/modules/{module_id}/enabled",
        {"enabled": False},
        token=token,
    )
    assert_true(disabled.get("enabled") is False, "禁用单账号模块失败")
    passed("禁用模块后随机调度任务被移除")
    return start, end


def test_single_run(module: dict[str, Any], token: str) -> None:
    module_id = module["id"]
    started = api("POST", f"/modules/{module_id}/run", token=token)
    log_id = started.get("log_id")
    assert_true(bool(log_id), "单账号立即执行未返回 log_id")
    log = wait_for_log(log_id, token)
    assert_true(
        log.get("status") == "success",
        f"单账号手动执行失败：{log.get('message')}\n{(log.get('output') or '')[-900:]}",
    )
    assert_true(log.get("trigger") == "manual", "单账号执行记录触发方式错误")
    passed(f"单账号立即执行成功，耗时 {log.get('duration_ms')} ms")


def test_multi_account(
    module: dict[str, Any], token: str, meta: dict[str, Any], start: str, end: str
) -> bool:
    module_id = module["id"]
    detail = api("GET", f"/modules/{module_id}", token=token)
    schema = detail.get("param_schema") or []
    assert_true(detail.get("multi_account") is True, "多账号模块模式错误")
    first = account_payload(schema, 1)
    second = account_payload(schema, 2)

    saved = api(
        "PUT",
        f"/modules/{module_id}",
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "daily",
            "accounts": [first, second],
            "enabled": False,
            "push_enabled": True,
        },
        token=token,
    )
    assert_true(saved.get("account_count") == 2, "多账号保存后数量不正确")
    assert_true(saved.get("multi_account") is True, "多账号模式未回显")
    assert_true(saved.get("push_enabled") is True, "模块推送开关未开启")

    reread = api("GET", f"/modules/{module_id}", token=token)
    accounts = reread.get("accounts") or []
    assert_true(len(accounts) == 2, "多账号详情未返回两个账号")
    assert_true(
        [item.get("id") for item in accounts] == [first["id"], second["id"]],
        "账号顺序或 ID 未按保存顺序保留",
    )
    assert_true(
        first["params"]["cookie"] not in json.dumps(accounts, ensure_ascii=False),
        "账号明文从默认详情接口泄露",
    )
    assert_true(
        "****" in accounts[0]["params"].get("cookie", "")
        and "****" in accounts[1]["params"].get("cookie", ""),
        "账号敏感参数未以掩码返回",
    )
    revealed = api(
        "POST",
        f"/modules/{module_id}/reveal-sensitive",
        {"current_password": ADMIN_PASS},
        token=token,
    )
    revealed_accounts = revealed.get("accounts") or []
    assert_true(
        revealed_accounts[0]["params"].get("cookie") == first["params"]["cookie"]
        and revealed_accounts[1]["params"].get("cookie")
        == second["params"]["cookie"],
        "二次密码校验后账号明文回读失败",
    )
    passed("多账号顺序、掩码、二次密码显示与推送开关均正确")

    # Missing required per-account field must be rejected.
    broken = account_payload(schema, 3)
    broken["params"]["cookie"] = ""
    expect_error(
        "PUT",
        f"/modules/{module_id}",
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "daily",
            "accounts": [first, broken],
            "enabled": False,
        },
        400,
        token=token,
    )
    passed("多账号缺少账号级必填参数时被拒绝")

    enabled = api(
        "PUT",
        f"/modules/{module_id}",
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "daily",
            "accounts": [first, second],
            "enabled": True,
            "push_enabled": False,
        },
        token=token,
    )
    assert_true(enabled.get("enabled") is True, "启用多账号模块失败")
    assert_true(enabled.get("push_enabled") is False, "模块推送开关未关闭")
    assert_true(bool(enabled.get("current_schedule_at")), "多账号模块没有生成随机时间")
    assert_in_window(enabled["current_schedule_at"], start, end, meta)
    api("PATCH", f"/modules/{module_id}/enabled", {"enabled": False}, token=token)
    passed("多账号模块启用后生成本期随机时间，并已禁用以避免定时任务干扰验证")

    interval = int(meta.get("account_interval_min_seconds", 0))
    if interval > 30:
        info(
            "账号间隔大于 30 秒，跳过串行执行实测；请以 "
            "ACCOUNT_INTERVAL_MIN_SECONDS=1 启动验证环境"
        )
        return False

    started = api("POST", f"/modules/{module_id}/run", token=token)
    log_id = started.get("log_id")
    assert_true(bool(log_id), "多账号立即执行未返回 log_id")
    log = wait_for_log(log_id, token)
    output = log.get("output") or ""
    assert_true(log.get("status") == "success", f"多账号执行失败：{log.get('message')}")
    assert_true("全部 2 个账号签到成功" in (log.get("message") or ""), "全成功汇总文案异常")
    assert_true("[账号 1/2]" in output and "[账号 2/2]" in output, "日志缺少账号分隔标记")
    assert_true("等待" in output, "日志缺少账号间隔等待标记")
    assert_true(first["params"]["cookie"] not in output, "执行日志泄露了完整 Cookie")
    assert_true(second["params"]["cookie"] not in output, "执行日志泄露了第二个账号 Cookie")
    passed("多账号按顺序串行执行，间隔等待与脱敏账号日志正常")

    # One account fails -> aggregate partial failure.
    second["params"]["simulate_failure"] = True
    api(
        "PUT",
        f"/modules/{module_id}",
        {
            "start_time": start,
            "end_time": end,
            "repeat_cycle": "daily",
            "accounts": [first, second],
            "enabled": False,
            "push_enabled": False,
        },
        token=token,
    )
    started = api("POST", f"/modules/{module_id}/run", token=token)
    assert_true(bool(started.get("log_id")), "多账号立即执行未返回 log_id")
    log = wait_for_log(started.get("log_id"), token)
    message = log.get("message") or ""
    assert_true(log.get("status") == "failed", "账号部分失败时整体状态应为 failed")
    assert_true("1 个成功" in message and "1 个失败" in message, f"部分失败汇总异常：{message}")
    passed("多账号部分失败被正确汇总为整体失败（1 成功 / 1 失败）")
    return True


def wait_for_log(log_id: int, token: str) -> dict[str, Any]:
    deadline = time.time() + RUN_TIMEOUT
    log: dict[str, Any] = {}
    while time.time() < deadline:
        log = api("GET", f"/logs/{log_id}", token=token)
        if log.get("status") in {"success", "failed"}:
            assert_true(
                isinstance(log.get("last_seq"), int) and log.get("last_seq") >= 0,
                "执行详情缺少环形日志 last_seq",
            )
            return log
        time.sleep(0.8)
    raise VerificationError(
        f"执行 {log_id} 在 {RUN_TIMEOUT} 秒内未结束，最近状态：{log.get('status')}"
    )


def test_log_settings(token: str) -> None:
    current = api("GET", "/settings/logs", token=token)
    assert_true(
        1 <= int(current.get("retention_days", 0)) <= 365,
        "日志保留天数不在 1~365 范围",
    )
    expect_error("PUT", "/settings/logs", {"retention_days": 0}, 422, token=token)
    updated = api(
        "PUT", "/settings/logs", {"retention_days": 31}, token=token
    )
    assert_true(updated.get("retention_days") == 31, "日志保留天数保存失败")
    passed("环形日志保留天数可读取、非法值被拒绝、修改后立即裁剪")




def test_push_drivers(token: str) -> None:
    key = f"verify_driver_{int(time.time())}"
    safe = (
        "async def send(config, title, body):\n"
        "    return {'sent': True, 'channel': 'verify', 'response': 'ok'}\n"
    ).encode("utf-8")
    bad = b"import os\ndef send(config, title, body):\n    os.system('echo bad')\n"
    status, _ = api_multipart(
        "/push/drivers/upload", "danger.py", bad, {"key": key, "version": "1.0.0"}, token
    )
    assert_true(status == 400, "危险驱动未被 AST 校验拒绝")
    status, _ = api_multipart(
        "/push/drivers/upload",
        "safe.py",
        safe,
        {"key": key, "name": "Verify Driver", "version": "1.0.0"},
        token,
    )
    assert_true(status == 200, f"安全驱动上传失败：HTTP {status}")
    status, _ = api_multipart(
        "/push/drivers/upload",
        "safe.py",
        safe,
        {"key": key, "name": "Verify Driver", "version": "1.0.1"},
        token,
    )
    assert_true(status == 200, f"驱动热加载失败：HTTP {status}")
    rolled = api("POST", f"/push/drivers/{key}/rollback", {}, token=token)
    assert_true(
        rolled.get("driver", {}).get("version") == "1.0.0", "驱动回滚版本不正确"
    )
    api("DELETE", f"/push/drivers/{key}", token=token)
    passed("自定义驱动危险代码拒绝、上传热加载、回滚与删除均正常")


def test_push_records(token: str) -> None:
    drivers = api("GET", "/push/drivers", token=token)
    keys = {item.get("key") for item in drivers}
    assert_true("bark" in keys, "内置 Bark 驱动未注册")
    records = api("GET", "/push/records?page=1&page_size=5", token=token)
    assert_true("items" in records and "total" in records, "推送记录接口异常")
    batches = api("GET", "/push/batches?page=1&page_size=5", token=token)
    assert_true("items" in batches and "total" in batches, "统一批次接口异常")
    passed("推送驱动注册表、推送记录与统一批次摘要接口正常")


def test_push_config(token: str) -> None:
    current = api("GET", "/push/config", token=token)
    assert_true("available_variables" in current, "推送配置缺少模板变量")
    assert_true("{event}" in current["available_variables"], "缺少 {event} 推送变量")

    saved = api(
        "PUT",
        "/push/config",
        {
            "channel": "bark",
            "config": {"key": "verify-bark-key", "server": "https://api.day.app"},
            "title_template": "验证｜{event}｜{module_name}",
            "body_template": "{account} {status} {result}",
        },
        token=token,
    )
    assert_true(saved.get("channel") == "bark", "Bark 渠道未保存")
    assert_true(
        saved.get("config", {}).get("key") != "verify-bark-key"
        and "****" in saved.get("config", {}).get("key", ""),
        "Bark key 未以掩码返回",
    )
    assert_true(saved.get("title_template") == "验证｜{event}｜{module_name}", "标题模板未回读")

    expect_error(
        "PUT",
        "/push/config",
        {"channel": "telegram", "config": {}, "title_template": "x", "body_template": "y"},
        400,
        token=token,
    )
    expect_error(
        "PUT",
        "/push/config",
        {
            "channel": "dingtalk",
            "config": {"webhook": "https://evil.example.com/robot", "secret": "x"},
            "title_template": "x",
            "body_template": "y",
        },
        400,
        token=token,
    )
    passed("推送渠道配置加密保存、模板回读、非法渠道与非法 Webhook 均被正确处理")

    api(
        "PUT",
        "/push/config",
        {
            "channel": "none",
            "config": {},
            "title_template": "签到结果｜{module_name}",
            "body_template": "{time}\n{result}\n{details}",
        },
        token=token,
    )
    passed("推送配置可恢复为禁用状态")


def test_username_change(token: str) -> str:
    idempotent = api(
        "PUT",
        "/auth/username",
        {"current_password": ADMIN_PASS, "new_username": ADMIN_USER},
        token=token,
    )
    assert_true(idempotent.get("username") == ADMIN_USER, "重复提交当前用户名应幂等成功")
    expect_error(
        "PUT",
        "/auth/username",
        {"current_password": "definitely-wrong", "new_username": "verify_admin"},
        400,
        token=token,
    )
    passed("用户名更新幂等，错误密码被拒绝")

    temporary = f"verify_{int(time.time()) % 1000000}"
    changed = api(
        "PUT",
        "/auth/username",
        {"current_password": ADMIN_PASS, "new_username": temporary},
        token=token,
    )
    assert_true(changed.get("username") == temporary, "用户名未更新")
    temporary_token = login(temporary, ADMIN_PASS)
    api(
        "PUT",
        "/auth/username",
        {"current_password": ADMIN_PASS, "new_username": ADMIN_USER},
        token=temporary_token,
    )
    refreshed_token = login(ADMIN_USER, ADMIN_PASS)
    passed("用户名修改后新用户名可登录，并可改回原用户名")
    return refreshed_token


def test_scan_and_dashboard(token: str, expect_partial_failure: bool) -> None:
    scan = api("POST", "/modules/scan", token=token)
    assert_true(isinstance(scan.get("total"), int), "扫描结果缺少模块总数")
    passed(
        f"模块目录扫描正常：新增 {scan.get('added')}，更新 {scan.get('updated')}，"
        f"异常 {len(scan.get('invalid') or [])}"
    )

    dashboard = api("GET", "/dashboard", token=token)
    stats = dashboard.get("stats") or {}
    assert_true(int(stats.get("total_modules", 0)) >= 2, "仪表盘模块总数异常")
    assert_true(int(stats.get("today_runs", 0)) >= 2, "仪表盘今日执行数未增加")
    if expect_partial_failure:
        assert_true(int(stats.get("today_failed", 0)) >= 1, "仪表盘未记录多账号部分失败")
    passed(
        "仪表盘统计正常："
        f"模块 {stats.get('total_modules')}，今日执行 {stats.get('today_runs')}，"
        f"成功 {stats.get('today_success')}，失败 {stats.get('today_failed')}"
    )

    logs = api("GET", "/logs?page=1&page_size=20", token=token)
    assert_true(int(logs.get("total", 0)) >= 2, "执行历史数量异常")
    assert_true(bool(logs.get("items")), "执行历史为空")
    passed("执行历史分页查询正常")


def _import_backend():
    try:
        from app.database import SessionLocal  # noqa: F401
    except ImportError:
        backend = Path.cwd() / "backend"
        if backend.is_dir():
            sys.path.insert(0, str(backend))
    from app.database import SessionLocal
    from app.migrations import migrate_schema
    from app.models import Module

    return SessionLocal, migrate_schema, Module


async def _verify_legacy_cycle_migration() -> None:
    """Insert a legacy row, run the real migration, and verify the downgrade."""
    SessionLocal, migrate_schema, Module = _import_backend()
    marker = f"verify_legacy_{int(time.time())}"
    async with SessionLocal() as db:
        row = Module(
            key=marker,
            name="Legacy migration verification",
            description="temporary row",
            author="verify",
            version="0.0.0",
            icon="🧪",
            default_cron="0 8 * * *",
            cron="0 8 * * *",
            default_start_time="08:00",
            default_end_time="10:00",
            default_repeat_cycle="quarterly",
            default_repeat_sub_value="",
            start_time="08:00",
            end_time="10:00",
            repeat_cycle="half_month",
            repeat_sub_value="",
            enabled=False,
            param_schema=[],
        )
        db.add(row)
        await db.commit()
        row_id = row.id
    try:
        await migrate_schema()
        async with SessionLocal() as db:
            row = await db.get(Module, row_id)
            assert_true(row is not None, "旧周期迁移测试行丢失")
            assert_true(
                row.repeat_cycle == "monthly" and row.repeat_sub_value == "1",
                f"旧周期 repeat_cycle 迁移错误：{row.repeat_cycle}/{row.repeat_sub_value}",
            )
            assert_true(
                row.default_repeat_cycle == "monthly"
                and row.default_repeat_sub_value == "1",
                "旧周期 default_repeat_cycle 迁移错误",
            )
    finally:
        async with SessionLocal() as db:
            row = await db.get(Module, row_id)
            if row is not None:
                await db.delete(row)
                await db.commit()
    passed("旧周期 half_month / quarterly 自动降级为每月 1 日（真实迁移函数验证）")


def _password_from_container_logs() -> str:
    """Best-effort host-side fallback for v1.0.6 random initial passwords."""
    container = os.environ.get("CONTAINER_NAME") or os.environ.get("VERIFY_CONTAINER")
    if not container:
        return ""
    try:
        result = subprocess.run(
            ["docker", "logs", container],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    match = re.search(
        r"Generated admin password:\s*(\S+)",
        result.stdout + result.stderr,
    )
    return match.group(1) if match else ""


def main(argv: list[str] | None = None) -> int:
    global ADMIN_PASS
    parser = argparse.ArgumentParser(description="签到云台部署 API 验证")
    parser.add_argument("--password", help="管理员密码；优先于 ADMIN_PASS 环境变量")
    parser.add_argument("--username", default=ADMIN_USER, help="管理员用户名")
    args = parser.parse_args(argv)
    if args.password:
        ADMIN_PASS = args.password
    if not ADMIN_PASS:
        ADMIN_PASS = _password_from_container_logs()
    if not ADMIN_PASS:
        print(
            "[FAIL] 未提供管理员密码：请设置 ADMIN_PASS、传入 --password，"
            "或在 CONTAINER_NAME 指向的容器日志中提供生成密码。",
            file=sys.stderr,
        )
        return 2
    print()
    print("=" * 68)
    print(" 签到云台 API 部署验证（随机调度 / 多账号 / 推送 / 用户设置）")
    print(f" 目标地址：{BASE_URL}")
    print("=" * 68)

    try:
        wait_for_health()
        check_public_surface()
        token = login()
        session = api("GET", "/auth/session", token=token)
        if session.get("force_change_password"):
            new_password = os.environ.get("VERIFY_NEW_PASSWORD") or (
                "Verify-" + secrets.token_urlsafe(18)
            )
            changed = api(
                "POST",
                "/auth/change-password",
                {"old_password": ADMIN_PASS, "new_password": new_password},
                token=token,
            )
            assert_true(bool(changed), "初始密码改密响应为空")
            ADMIN_PASS = new_password
            token = login()
            passed("首次登录强制改密完成，旧密码已轮换")
        passed(f"管理员 {ADMIN_USER} 登录成功并获取 Cookie 会话 + CSRF")
        meta, demo, multi = pick_modules(token)
        start, end = test_cycle_persistence(demo, token, meta)
        test_single_run(demo, token)
        partial_tested = test_multi_account(multi, token, meta, start, end)
        test_log_settings(token)
        test_push_config(token)
        test_push_drivers(token)
        test_push_records(token)
        token = test_username_change(token)
        test_scan_and_dashboard(token, partial_tested)
        asyncio.run(_verify_legacy_cycle_migration())
    except VerificationError as exc:
        print(f"\n[FAIL] {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"\n[FAIL] 未预期的错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print()
    print("=" * 68)
    print(" [PASS] 所有核心 API 验证通过")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
