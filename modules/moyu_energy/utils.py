"""辅助函数，用于演示模块支持相对导入与多文件结构。"""

from __future__ import annotations

from datetime import datetime


def mask_cookie(cookie: str) -> str:
    cleaned = cookie.strip()
    if not cleaned:
        return "(空)"
    if len(cleaned) <= 12:
        return cleaned[:2] + "***"
    return f"{cleaned[:6]}...{cleaned[-4:]}（共 {len(cleaned)} 字符）"


def local_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def bool_label(value: bool) -> str:
    return "开启" if value else "关闭"
