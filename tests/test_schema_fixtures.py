"""Every valid fixture passes its schema; every invalid one fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from impresario.loader import load_doc
from impresario.schemas import check_schema

from .conftest import CONTRACTS_DIR


def _fixture_paths(polarity: str) -> list[Path]:
    return sorted(
        path
        for suffix in ("yaml", "json")
        for path in CONTRACTS_DIR.glob(f"*/v1/fixtures/{polarity}/*.{suffix}")
    )


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
        for polarity in ("valid", "invalid"):
            found = [
                p
                for suffix in ("yaml", "json")
                for p in (contract_dir / "fixtures" / polarity).glob(f"*.{suffix}")
            ]
            assert found, f"{name}: no {polarity} fixtures"


def test_detect_kind_lrd_prefix() -> None:
    from impresario.loader import detect_kind

    assert (
        detect_kind({"decision_id": "LRD-001", "subject": {}}) == "loop-resume-decision"
    )


def test_detect_kind_gd_prefix_stays_gate_decision() -> None:
    from impresario.loader import detect_kind

    assert detect_kind({"decision_id": "GD-001"}) == "gate-decision"


def test_detect_kind_evaluation_brief() -> None:
    from impresario.loader import detect_kind

    assert detect_kind({"brief_id": "BRF-0123456789ab"}) == "evaluation-brief"


def test_detect_kind_assessment_answer() -> None:
    from impresario.loader import detect_kind

    assert (
        detect_kind({"schema_version": "assessment-answer/v1"}) == "assessment-answer"
    )


def test_answer_without_discriminator_is_unknown_kind() -> None:
    from impresario.loader import UnknownContractError, detect_kind

    answer_without = {"fit_strategy": 5, "rationale": {}}
    with pytest.raises(UnknownContractError):
        detect_kind(answer_without)

    with pytest.raises(UnknownContractError):
        detect_kind({"schema_version": "assessment-answer/v0"})


def test_detect_kind_loop_harness_discriminators() -> None:
    from impresario.loader import UnknownContractError, detect_kind

    assert detect_kind({"schema_version": "stage-brief/v1"}) == "stage-brief"
    assert detect_kind({"schema_version": "research-answer/v1"}) == "research-answer"
    assert detect_kind({"schema_version": "concept-answer/v1"}) == "concept-answer"
    with pytest.raises(UnknownContractError):
        detect_kind({"schema_version": "stage-brief/v0"})
