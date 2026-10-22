"""Import architecture guard (python -m backend.app.check_imports)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
violations: list[str] = []
for path in (ROOT / "app/services").rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    if "from ..routers" in text or "import ..routers" in text:
        violations.append(f"{path}: services must not import routers")
for path in (ROOT / "app/models.py",):
    text = path.read_text(encoding="utf-8")
    if "from .services" in text or "from .routers" in text:
        violations.append(f"{path}: models must not import services/routers")
if violations:
    raise SystemExit("\n".join(violations))
print("import architecture OK")
