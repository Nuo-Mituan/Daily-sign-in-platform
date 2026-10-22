"""Unified-push summary rendering."""

from __future__ import annotations

from ..config import settings
from ..models import PushPool
from .redaction import redact_text

POOL_SUCCESS = "success"
POOL_FAILED = "failed"
POOL_SKIPPED = "skipped"
POOL_PENDING = "pending"
POOL_TIMEOUT = "timeout"


def render_summary(
    cycle_id: str,
    rows: list[PushPool],
    counts: dict[str, int],
    *,
    timeout: bool = False,
) -> str:
    heading = (
        f"### ⚠️ 部分模块推送超时（兜底触发）｜{cycle_id}"
        if timeout
        else f"### 签到日报｜{cycle_id}"
    )
    lines = [
        heading,
        f"- 预期：{len(rows)} 个模块",
        f"- 成功：{counts['success']}",
        f"- 失败：{counts['failed']}",
        f"- 跳过：{counts['skipped']}",
        f"- 未完成：{counts.get('pending', 0)}",
        f"- 超时：{counts.get('timeout', 0)}",
        "",
    ]
    for row in rows:
        if row.status == POOL_SKIPPED and not settings.push_skip_notice:
            continue
        label = {
            POOL_SUCCESS: "成功",
            POOL_FAILED: "失败",
            POOL_SKIPPED: "跳过",
            POOL_PENDING: "未完成",
            POOL_TIMEOUT: "推送超时",
        }.get(row.status, row.status)
        detail = redact_text(row.message or row.details or "")
        lines.append(f"- {row.module_name}：{label}" + (f"（{detail}）" if detail else ""))
    return redact_text("\n".join(lines))
