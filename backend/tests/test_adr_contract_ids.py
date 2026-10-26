"""Bidirectional validation between ADR contract IDs and PBT tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PBT_DIR = ROOT / "backend" / "tests" / "property"
ADR = ROOT / "backend" / "app" / "DESIGN_DECISIONS.md"


def _property_docstrings() -> list[str]:
    values: list[str] = []
    for path in PBT_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            is_property = any(
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "property"
                for decorator in node.decorator_list
            )
            if is_property and node.body:
                doc = ast.get_docstring(node) or ""
                values.append(doc)
    return values


def test_adr_contract_ids_exist() -> None:
    test_ids = {
        match.group(1)
        for doc in _property_docstrings()
        for match in [re.search(r"ADR-INVARIANT:\s*([a-z0-9-]+)", doc)]
        if match
    }
    adr_ids = set(
        re.findall(r"Contract ID:\s*`([a-z0-9-]+)`", ADR.read_text(encoding="utf-8"))
    )
    assert test_ids == adr_ids, {
        "missing_in_tests": sorted(adr_ids - test_ids),
        "missing_in_adr": sorted(test_ids - adr_ids),
    }
