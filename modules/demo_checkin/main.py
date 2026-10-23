"""演示签到模块（单账号）。

所有流程均为本地模拟，不会访问任何真实平台。
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Any

logger = logging.getLogger("modules.demo_checkin")


def _mask_account(account: str) -> str:
    if "@" in account:
        name, domain = account.split("@", 1)
        return f"{name[:2]}***@{domain}"
    if len(account) <= 4:
        return account[:1] + "***"
    return f"{account[:2]}***{account[-2:]}"


async def run(params: dict[str, Any]) -> dict[str, Any]:
    account = str(params.get("account") or "").strip()
    password = str(params.get("password") or "")
    server = str(params.get("server") or "cn")
    mode = str(params.get("mode") or "success")
    retries = int(params.get("retries") or 1)
    verbose = bool(params.get("verbose", True))

    if not account or not password:
        return {"success": False, "message": "账号或密码为空，无法签到"}

    server_label = {"cn": "国服", "global": "国际服"}.get(server, server)
    masked = _mask_account(account)
    logger.info("开始演示签到：账号=%s，服务器=%s", masked, server_label)
    print(f"→ 目标账号：{masked}（密码已隐藏，长度 {len(password)}）")

    await asyncio.sleep(0.35)
    if verbose:
        print(f"→ 正在登录 {server_label} ...")
    await asyncio.sleep(0.35)

    attempts = 0
    max_attempts = max(1, min(5, retries))
    while attempts < max_attempts:
        attempts += 1
        if verbose:
            print(f"→ 第 {attempts}/{max_attempts} 次尝试签到 ...")
        await asyncio.sleep(0.45)
        if mode == "success":
            break
        if verbose:
            print("  ⚠ 本轮模拟网络波动，准备重试")

    if mode == "failure":
        message = "演示失败：当前为“模拟失败”模式，请将执行模式改为正常签到后重试"
        logger.warning(message)
        return {
            "success": False,
            "message": message,
            "attempts": attempts,
            "server": server_label,
        }

    points = random.randint(5, 18)
    total_days = random.randint(30, 120)
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"→ 签到成功，获得 {points} 积分，累计签到 {total_days} 天")
    logger.info("演示签到成功：+%s 积分", points)

    return {
        "success": True,
        "message": f"演示签到成功：+{points} 积分，累计 {total_days} 天",
        "points": points,
        "total_days": total_days,
        "server": server_label,
        "attempts": attempts,
        "checked_at": checked_at,
    }
