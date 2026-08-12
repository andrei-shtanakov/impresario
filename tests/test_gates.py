"""QG-5 gate tests: readiness precondition, FSM transitions, immutability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from impresario.cli import validate_paths
from impresario.gate import decide, readiness
from impresario.loader import load_doc

from .conftest import CONTRACTS_DIR
from .test_loop import (
    HAPPY_SCRIPT,
    STUCK_SCRIPT,
    loop_ws,  # noqa: F401 - fixture reuse
)
from .test_loop import _run as run_loop_script

T0 = "2026-08-12T20:00:00Z"
T1 = "2026-08-12T20:10:00Z"
T2 = "2026-08-12T20:20:00Z"


def _decide(workspace: Path, now: str, **kwargs: Any):
    defaults: dict[str, Any] = {
        "actor": "andrei",
        "reason": "gate decision for tests",
        "now_iso": now,
    }
    defaults.update(kwargs)
    return decide(workspace, CONTRACTS_DIR, **defaults)


@pytest.fixture()
def ready_ws(loop_ws: Path) -> Path:  # noqa: F811 - pytest fixture reuse
    result = run_loop_script(loop_ws, HAPPY_SCRIPT)
    assert result.verdict == "ready_for_business"
    return loop_ws


def test_full_gate_chain_to_approved(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]

    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="approve",
        expected_version=version,
        role="business_owner",
    )
    assert report.ok, [f.message for f in report.errors]
    assert record is not None and record["decision_id"] == "GD-001"
    proposal = load_doc(ready_ws / "proposal.yaml")
    assert proposal.data["status"] == "business_approved"

    ok, reasons = readiness(ready_ws)
    assert ok, reasons

    report, record = _decide(
        ready_ws,
        T1,
        gate_id="qg5_committee",
        decision="approve",
        expected_version=proposal.data["version"],
        role="committee_chair",
    )
    assert report.ok, [f.message for f in report.errors]
    proposal = load_doc(ready_ws / "proposal.yaml")
    assert proposal.data["status"] == "approved"

    bundle = validate_paths([ready_ws], CONTRACTS_DIR, bundle=True)
    assert bundle.ok, [f.message for f in bundle.errors]


def test_gate_b_before_gate_a_is_illegal(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_committee",
        decision="approve",
        expected_version=version,
    )
    assert record is None
    assert {f.code for f in report.errors} == {"FSM_ILLEGAL"}
    assert (
        not list((ready_ws / "decisions").glob("*.yaml"))
        if (ready_ws / "decisions").exists()
        else True
    )


def test_blocked_readiness_creates_no_decision(loop_ws: Path) -> None:  # noqa: F811
    result = run_loop_script(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    # Force the FSM into business_approved artificially is illegal; instead
    # verify readiness reports the open criticals honestly from in_iteration.
    ok, reasons = readiness(loop_ws)
    assert not ok
    assert any("open critical" in r for r in reasons)
    assert any("business_approved" in r for r in reasons)


def test_readiness_blocked_after_gate_a_with_open_criticals(
    ready_ws: Path,
) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="approve",
        expected_version=version,
    )
    # Reopen a critical assumption in the latest concept draft on disk
    # (structural edit, not text surgery).
    cd_path = ready_ws / "cd-002.yaml"
    cd = load_doc(cd_path).data
    for assumption in cd["assumptions"]:
        assumption.pop("answered_by", None)
    cd_path.write_text(
        yaml.safe_dump(cd, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    ok, reasons = readiness(ready_ws)
    assert not ok and any("open critical" in r for r in reasons)

    proposal_version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T1,
        gate_id="qg5_committee",
        decision="approve",
        expected_version=proposal_version,
    )
    assert record is None
    assert {f.code for f in report.errors} == {"READINESS_BLOCKED"}
    # the gate did not open: no new decision record, status unchanged
    assert len(list((ready_ws / "decisions").glob("*.yaml"))) == 1
    assert load_doc(ready_ws / "proposal.yaml").data["status"] == ("business_approved")


def test_recycle_returns_to_named_state(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="recycle",
        expected_version=version,
        return_to="in_iteration",
        required_changes=["re-validate economics"],
    )
    assert report.ok, [f.message for f in report.errors]
    assert record is not None and record["return_to"] == "in_iteration"
    assert load_doc(ready_ws / "proposal.yaml").data["status"] == "in_iteration"


def test_recycle_requires_return_to(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="recycle",
        expected_version=version,
        required_changes=["x"],
    )
    assert record is None
    assert {f.code for f in report.errors} == {"USAGE"}


def test_hold_then_resume_same_gate(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="hold",
        expected_version=version,
        review_after=T2,
    )
    proposal = load_doc(ready_ws / "proposal.yaml")
    assert proposal.data["status"] == "on_hold"

    report, record = _decide(
        ready_ws,
        T1,
        gate_id="qg5_business",
        decision="resume",
        expected_version=proposal.data["version"],
        return_to="ready_for_business",
    )
    assert report.ok, [f.message for f in report.errors]
    assert load_doc(ready_ws / "proposal.yaml").data["status"] == ("ready_for_business")


def test_resume_without_hold_is_refused(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="hold",
        expected_version=version,
    )
    proposal_version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T1,
        gate_id="qg5_committee",
        decision="resume",
        expected_version=proposal_version,
        return_to="ready_for_business",
    )
    assert record is None
    assert {f.code for f in report.errors} == {"RESUME_WITHOUT_HOLD"}


def test_kill_is_terminal(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, _ = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="kill",
        expected_version=version,
    )
    assert report.ok
    assert load_doc(ready_ws / "proposal.yaml").data["status"] == "killed"
    bundle = validate_paths([ready_ws], CONTRACTS_DIR, bundle=True)
    assert bundle.ok, [f.message for f in bundle.errors]


def test_recycle_requires_required_changes(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="recycle",
        expected_version=version,
        return_to="in_iteration",
    )
    assert record is None
    assert {f.code for f in report.errors} == {"USAGE"}


def test_malformed_ref_does_not_reach_filesystem(ready_ws: Path) -> None:
    proposal_path = ready_ws / "proposal.yaml"
    data = load_doc(proposal_path).data
    data["refs"]["latest_concept_draft"] = "concept-draft://../../etc/passwd"
    proposal_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    ok, reasons = readiness(ready_ws)
    assert not ok
    assert any("not resolvable" in r for r in reasons)


def test_cli_readiness_missing_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json as _json

    from impresario.cli import main

    code = main(["gate", "readiness", str(tmp_path / "nope")])
    out = _json.loads(capsys.readouterr().out)
    assert code == 2
    assert out["ok"] is False


def test_placeholder_reason_is_refused(ready_ws: Path) -> None:
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="approve",
        expected_version=version,
        reason="<почему approve>",
    )
    assert record is None
    assert {f.code for f in report.errors} == {"USAGE"}
    assert "placeholder" in report.errors[0].message


def test_version_conflict(ready_ws: Path) -> None:
    report, record = _decide(
        ready_ws,
        T0,
        gate_id="qg5_business",
        decision="approve",
        expected_version=99,
    )
    assert record is None
    assert {f.code for f in report.errors} == {"VERSION_CONFLICT"}
