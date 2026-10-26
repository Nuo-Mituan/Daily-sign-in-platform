"""摸鱼能量签到（多账号示例）。

平台会为账号列表中的每个账号依次调用一次 run(params)，账号之间自动插入随机等待。
这个模块只模拟单个账号的签到流程，不访问任何真实接口。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .utils import bool_label, local_stamp, mask_cookie

logger = logging.getLogger("modules.moyu_energy")


async def run(params: dict[str, Any]) -> dict[str, Any]:
    cookie = str(params.get("cookie") or "").strip()
    target_level = int(params.get("target_level") or 3)
    verbose = bool(params.get("verbose", True))
    simulate_failure = bool(params.get("simulate_failure", False))

    if not cookie:
        return {"success": False, "message": "Cookie 为空，请先完成账号配置"}

    logger.info("摸鱼能量任务启动，目标等级 Lv.%s", target_level)
    print("=" * 50)
    print(f"任务时间：{local_stamp()}")
    print(f"Cookie：{mask_cookie(cookie)}")
    print(f"目标等级：Lv.{target_level}")
    print(f"详细日志：{bool_label(verbose)}")
    print("=" * 50)

    steps = ["加载用户信息", "领取每日能量", "完成分享任务", "领取等级奖励"]
    for index, step in enumerate(steps, start=1):
        await asyncio.sleep(0.35)
        if verbose:
            print(f"[{index}/{len(steps)}] {step} ✓")

    if simulate_failure:
        message = "模拟失败：该账号被标记为失败，用于测试多账号汇总"
        logger.warning(message)
        return {"success": False, "message": message, "simulated_failure": True}

    energy = 20 + target_level * 5
    level_after = min(10, target_level + 1)
    message = f"摸鱼能量签到完成，获得 {energy} 能量，当前等级 Lv.{level_after}"
    logger.info("摸鱼能量任务完成：+%s 能量", energy)
    return {
        "success": True,
        "message": message,
        "energy": energy,
        "level_after": level_after,
    }
