"""Every valid fixture passes its schema; every invalid one fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from impresario.loader import load_doc
from impresario.schemas import check_schema

from .conftest import CONTRACTS_DIR


def _fixture_paths(polarity: str) -> list[Path]:
    return sorted(CONTRACTS_DIR.glob(f"*/v1/fixtures/{polarity}/*.yaml"))


def _fixture_id(path: Path) -> str:
    return f"{path.parents[3].name}/{path.parent.name}/{path.name}"


@pytest.mark.parametrize("path", _fixture_paths("valid"), ids=_fixture_id)
def test_valid_fixture_passes(path: Path, validators) -> None:
    doc = load_doc(path)
    findings = check_schema(doc, validators)
    assert findings == [], [f.message for f in findings]


@pytest.mark.parametrize("path", _fixture_paths("invalid"), ids=_fixture_id)
def test_invalid_fixture_fails(path: Path, validators) -> None:
    doc = load_doc(path)
    assert check_schema(doc, validators), (
        f"{path} unexpectedly passed schema validation"
    )


def test_fixture_coverage() -> None:
    """Every contract ships at least one valid and one invalid fixture."""
    for contract_dir in sorted(CONTRACTS_DIR.glob("*/v1")):
        name = contract_dir.parent.name
        assert list((contract_dir / "fixtures" / "valid").glob("*.yaml")), (
            f"{name}: no valid fixtures"
        )
        assert list((contract_dir / "fixtures" / "invalid").glob("*.yaml")), (
            f"{name}: no invalid fixtures"
        )
