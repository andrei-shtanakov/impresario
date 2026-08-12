"""CLI smoke tests: exit codes and JSON report shape."""

from __future__ import annotations

import json

import pytest

from impresario.cli import main
from impresario.report import EXIT_OK, EXIT_USAGE, EXIT_VIOLATIONS

from .conftest import CONTRACTS_DIR, EXAMPLE_BUNDLE

INVALID_FIXTURE = (
    CONTRACTS_DIR
    / "product-proposal"
    / "v1"
    / "fixtures"
    / "invalid"
    / "status-ready-for-committee.yaml"
)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = main(["validate", *argv, "--contracts", str(CONTRACTS_DIR)])
    return code, json.loads(capsys.readouterr().out)


def test_example_bundle_passes(capsys: pytest.CaptureFixture[str]) -> None:
    code, report = _run([str(EXAMPLE_BUNDLE)], capsys)
    assert code == EXIT_OK, report["errors"]
    assert report["ok"] is True
    assert report["checked"] == 12


def test_invalid_fixture_fails_distinctly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, report = _run([str(INVALID_FIXTURE)], capsys)
    assert code == EXIT_VIOLATIONS
    assert report["ok"] is False
    assert any(e["code"] == "SCHEMA" for e in report["errors"])


def test_missing_path_is_usage_error_with_json_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["validate", "/nonexistent/path.yaml"])
    report = json.loads(capsys.readouterr().out)
    assert code == EXIT_USAGE
    assert report["ok"] is False
    assert report["errors"][0]["code"] == "USAGE"


def test_malformed_yaml_is_load_finding(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed\n  nested: {", encoding="utf-8")
    code, report = _run([str(broken)], capsys)
    assert code == EXIT_VIOLATIONS
    assert any(e["code"] == "LOAD" for e in report["errors"])
