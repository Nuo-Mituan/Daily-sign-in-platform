"""Static upload validation for custom push drivers.

This is deliberately an upload guard, not a sandbox.  Custom drivers execute
in the server process and must only be installed by a trusted administrator.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path, PurePosixPath

from .base import DriverValidationError

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,39}$")
ALLOWED_IMPORTS = {
    "asyncio",
    "base64",
    "datetime",
    "hashlib",
    "hmac",
    "httpx",
    "json",
    "math",
    "re",
    "time",
    "typing",
    "urllib",
}
FORBIDDEN_NAMES = {
    "__builtins__",
    "__import__",
    "breakpoint",
    "getattr",
    "hasattr",
    "setattr",
    "delattr",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
FORBIDDEN_MODULES = {
    "builtins",
    "ctypes",
    "importlib",
    "marshal",
    "os",
    "pathlib",
    "pickle",
    "shutil",
    "signal",
    "socket",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
}
FORBIDDEN_ATTRS = {
    "chmod",
    "chown",
    "execv",
    "execve",
    "fork",
    "kill",
    "link",
    "mkdir",
    "makedirs",
    "popen",
    "remove",
    "removedirs",
    "rename",
    "renames",
    "replace",
    "rmdir",
    "rmtree",
    "spawn",
    "system",
    "unlink",
    "unlink",
    "walk",
    "write",
    "writelines",
}


def validate_manifest(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise DriverValidationError("manifest.json 必须是 JSON 对象")
    key = str(raw.get("key") or "").strip()
    if not KEY_RE.fullmatch(key):
        raise DriverValidationError(
            "manifest.key 只允许小写字母/数字/下划线，2-40 位且以字母开头"
        )
    version = str(raw.get("version") or "").strip()
    if not VERSION_RE.fullmatch(version):
        raise DriverValidationError("manifest.version 格式无效")
    name = str(raw.get("name") or "").strip()
    if not name or len(name) > 80:
        raise DriverValidationError("manifest.name 不能为空且不超过 80 字符")
    entry = str(raw.get("entry") or "driver.py").strip()
    if entry != "driver.py":
        raise DriverValidationError("自定义驱动入口必须是 driver.py")
    fields_raw = raw.get("fields") or []
    if not isinstance(fields_raw, list) or len(fields_raw) > 30:
        raise DriverValidationError("manifest.fields 必须是最多 30 项的数组")
    fields: list[dict[str, object]] = []
    for item in fields_raw:
        if not isinstance(item, dict):
            raise DriverValidationError("manifest.fields 每一项必须是对象")
        field_key = str(item.get("key") or "").strip()
        if not re.fullmatch(r"^[a-zA-Z][a-zA-Z0-9_]{0,39}$", field_key):
            raise DriverValidationError(f"字段 key 无效：{field_key}")
        label = str(item.get("label") or field_key).strip()[:80]
        fields.append(
            {
                "key": field_key,
                "label": label,
                "required": bool(item.get("required")),
                "secret": bool(item.get("secret", True)),
                "placeholder": str(item.get("placeholder") or "")[:200],
                "help": str(item.get("help") or "")[:300],
            }
        )
    return {
        "key": key,
        "name": name,
        "version": version,
        "description": str(raw.get("description") or "")[:500],
        "entry": entry,
        "fields": fields,
    }


def validate_driver_source(source: str) -> None:
    try:
        tree = ast.parse(source, filename="driver.py")
    except SyntaxError as exc:
        raise DriverValidationError(f"driver.py 语法错误：{exc}") from exc

    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".", 1)[0] for alias in node.names]
            elif node.module:
                modules = [node.module.split(".", 1)[0]]
            for module in modules:
                if module in FORBIDDEN_MODULES:
                    errors.append(f"禁止导入模块 {module}")
                elif module not in ALLOWED_IMPORTS:
                    errors.append(f"不在白名单的导入模块 {module}")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in FORBIDDEN_NAMES:
                errors.append(f"禁止调用/引用 {node.id}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
                errors.append(f"禁止调用 {node.func.id}()")
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_ATTRS:
                    errors.append(f"禁止调用属性 .{node.func.attr}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"禁止访问双下划线属性 {node.attr}")
    if errors:
        raise DriverValidationError("；".join(dict.fromkeys(errors)))


def validate_zip_member(name: str) -> str:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.name:
        raise DriverValidationError(f"ZIP 路径穿越/非法路径：{name}")
    return pure.as_posix()


def validate_driver_directory(directory: Path) -> dict[str, object]:
    manifest_path = directory / "manifest.json"
    driver_path = directory / "driver.py"
    if not manifest_path.is_file() or not driver_path.is_file():
        raise DriverValidationError("驱动目录必须包含 manifest.json 与 driver.py")
    try:
        manifest = validate_manifest(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise DriverValidationError("manifest.json 无法解析") from exc
    try:
        source = driver_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DriverValidationError("driver.py 无法读取") from exc
    if len(source.encode("utf-8")) > 512_000:
        raise DriverValidationError("driver.py 不能超过 500KB")
    validate_driver_source(source)
    return manifest
