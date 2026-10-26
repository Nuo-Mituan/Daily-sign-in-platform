"""Tests for the PBT bootstrap generator."""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.pbt_bootstrap import generate


def test_pbt_bootstrap_generates_valid_structure(tmp_path: Path) -> None:
    result = generate(
        "rate_limiter",
        tmp_path,
        ["token_bucket_never_negative", "burst_respects_max"],
    )

    assert result.pbt_path.is_file()
    assert result.adr_path.is_file()
    pbt = result.pbt_path.read_text(encoding="utf-8")
    adr = result.adr_path.read_text(encoding="utf-8")
    assert "@pytest.mark.property" in pbt
    assert "ADR-INVARIANT: rate_limiter-token_bucket_never_negative" in pbt
    assert "rate_limiter-burst_respects_max" in adr
    assert "CI Enforcement" in adr
    assert "Observability" in adr

    workflow = yaml.safe_load(result.workflow_snippet)
    assert "rate_limiter-property-tests" in workflow
    assert workflow["rate_limiter-property-tests"]["runs-on"] == "ubuntu-latest"
    assert "addopts" in result.pytest_config_snippet
