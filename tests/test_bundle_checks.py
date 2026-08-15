"""Cross-artifact checks: the canonical bundle passes, broken variants fail."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from impresario.checks import run_bundle_checks
from impresario.loader import Doc, load_doc

from .conftest import EXAMPLE_BUNDLE


@pytest.fixture()
def bundle() -> list[Doc]:
    return [load_doc(path) for path in sorted(EXAMPLE_BUNDLE.glob("*.yaml"))]


def _mutate(docs: list[Doc], doc_id: str, **changes: Any) -> list[Doc]:
    """Return a copy of the bundle with one document's fields replaced."""
    result = []
    for doc in docs:
        ids = {doc.data.get(k) for k in ("id", "proposal_id", "decision_id")}
        if doc_id in ids:
            data = copy.deepcopy(doc.data)
            data.update(copy.deepcopy(changes))
            doc = Doc(path=doc.path, kind=doc.kind, data=data)
        result.append(doc)
    return result


def _drop(docs: list[Doc], doc_id: str) -> list[Doc]:
    return [
        doc
        for doc in docs
        if doc_id not in {doc.data.get(k) for k in ("id", "proposal_id", "decision_id")}
    ]


def _codes(docs: list[Doc]) -> set[str]:
    return {finding.code for finding in run_bundle_checks(docs)}


def test_canonical_bundle_is_clean(bundle: list[Doc]) -> None:
    findings = run_bundle_checks(bundle)
    assert findings == [], [f"{f.code}: {f.message}" for f in findings]


def test_dangling_ref(bundle: list[Doc]) -> None:
    broken = _mutate(
        bundle,
        "PP-001",
        refs={
            "latest_research_pack": "research-pack://RP-002",
            "latest_concept_draft": "concept-draft://CD-999",
            "exchange_log": "exchange-log://XL-001",
        },
    )
    assert "REF_DANGLING" in _codes(broken)


def test_approved_without_committee_decision(bundle: list[Doc]) -> None:
    assert "FSM_EVIDENCE" in _codes(_drop(bundle, "GD-102"))


def test_gate_b_before_gate_a(bundle: list[Doc]) -> None:
    broken = _mutate(bundle, "GD-102", decided_at="2026-08-12T10:30:00Z")
    assert "GATE_ORDER" in _codes(broken)


def test_decision_version_ahead_of_proposal(bundle: list[Doc]) -> None:
    broken = _mutate(
        bundle,
        "GD-102",
        subject={"kind": "product_proposal", "ref": "proposal://PP-001", "version": 99},
    )
    assert "GD_VERSION_AHEAD" in _codes(broken)


def test_duplicate_rank(bundle: list[Doc]) -> None:
    backlog = next(d for d in bundle if d.kind == "ranked-backlog")
    items = copy.deepcopy(backlog.data["items"])
    second = copy.deepcopy(items[0])
    items.append(second)
    assert "BL_RANK_DUP" in _codes(_mutate(bundle, "BL-portfolio", items=items))


def test_open_critical_assumption(bundle: list[Doc]) -> None:
    cd = next(d for d in bundle if d.data.get("id") == "CD-002")
    assumptions = copy.deepcopy(cd.data["assumptions"])
    assumptions[0].pop("answered_by")
    broken = _mutate(bundle, "CD-002", assumptions=assumptions)
    assert "ASSUMPTION_OPEN" in _codes(broken)


def test_open_critical_gap(bundle: list[Doc]) -> None:
    rp = next(d for d in bundle if d.data.get("id") == "RP-002")
    gaps = copy.deepcopy(rp.data["gaps"])
    gaps[0].pop("closed")
    assert "GAP_OPEN" in _codes(_mutate(bundle, "RP-002", gaps=gaps))


def test_stale_research_reference(bundle: list[Doc]) -> None:
    broken = _mutate(
        bundle,
        "CD-002",
        based_on_research={"ref": "research-pack://RP-001", "iteration": 0},
    )
    assert "RP_STALE" in _codes(broken)


def test_exchange_log_iteration_order(bundle: list[Doc]) -> None:
    log = next(d for d in bundle if d.kind == "exchange-log")
    entries = copy.deepcopy(log.data["entries"])
    entries.reverse()
    assert "XLOG_ORDER" in _codes(_mutate(bundle, "XL-001", entries=entries))


def _extra_decision(**changes: Any) -> Doc:
    """A new gate decision derived from the committee approve in the bundle."""
    base = load_doc(EXAMPLE_BUNDLE / "gd-102-qg5-committee.yaml")
    data = copy.deepcopy(base.data)
    data.update(copy.deepcopy(changes))
    return Doc(path=base.path, kind=base.kind, data=data)


def test_resume_without_hold(bundle: list[Doc]) -> None:
    extended = [
        *bundle,
        _extra_decision(
            decision_id="GD-103",
            decision="resume",
            return_to="business_approved",
            decided_at="2026-08-12T13:00:00Z",
        ),
    ]
    assert "RESUME_WITHOUT_HOLD" in _codes(extended)


def test_resume_chronologically_before_hold(bundle: list[Doc]) -> None:
    hold = _extra_decision(
        decision_id="GD-103", decision="hold", decided_at="2026-08-12T14:00:00Z"
    )
    resume = _extra_decision(
        decision_id="GD-104",
        decision="resume",
        return_to="business_approved",
        decided_at="2026-08-12T13:00:00Z",
    )
    assert "RESUME_WITHOUT_HOLD" in _codes([*bundle, hold, resume])


def test_fractional_seconds_gate_order(bundle: list[Doc]) -> None:
    """Lexicographic comparison would miss this: 12:00:00.500Z > 12:00:00Z."""
    broken = _mutate(bundle, "GD-101", decided_at="2026-08-12T12:00:00.500Z")
    assert "GATE_ORDER" in _codes(broken)


def test_superseded_approve_is_not_evidence(bundle: list[Doc]) -> None:
    revoke = _extra_decision(
        decision_id="GD-103",
        decision="recycle",
        return_to="in_iteration",
        required_changes=["re-validate economics"],
        supersedes="gate-decision://GD-102",
        decided_at="2026-08-12T13:00:00Z",
    )
    assert "FSM_EVIDENCE" in _codes([*bundle, revoke])


def test_foreign_artifact_rejected(bundle: list[Doc]) -> None:
    broken = _mutate(bundle, "CD-002", proposal_ref="proposal://PP-999")
    assert "REF_FOREIGN" in _codes(broken)


def _lrd(
    decision_id: str,
    *,
    iteration: int = 1,
    budget: int = 3,
    supersedes: str | None = None,
    loop_id: str = "LOOP-001",
) -> Doc:
    data: dict[str, Any] = {
        "decision_id": decision_id,
        "subject": {"loop_id": loop_id, "iteration": iteration},
        "new_max_iterations": budget,
        "decided_by": {"kind": "human", "id": "andrei"},
        "decided_at": "2026-08-12T04:01:21Z",
        "reason": "r",
    }
    if supersedes is not None:
        data["supersedes"] = supersedes
    return Doc(
        path=Path(f"{decision_id.lower()}.yaml"),
        kind="loop-resume-decision",
        data=data,
    )


def _loop_state(loop_id: str = "LOOP-001") -> Doc:
    return Doc(
        path=Path("loop.state"),
        kind="loop-state",
        data={
            "loop_id": loop_id,
            "idea_ref": "idea://IDEA-001",
            "idea_input_hash": "sha256:" + "0" * 64,
            "proposal_id": "PP-001",
            "exchange_log_id": "XL-001",
            "max_iterations": 3,
            "stop": None,
        },
    )


def test_lrd_loop_unresolved(bundle: list[Doc]) -> None:
    docs = [*bundle, _lrd("LRD-001", loop_id="LOOP-999")]
    assert "LRD_LOOP" in _codes(docs)


def test_lrd_budget_below_iteration_floor(bundle: list[Doc]) -> None:
    docs = [*bundle, _loop_state(), _lrd("LRD-001", iteration=2, budget=3)]
    assert "LRD_BUDGET" in _codes(docs)  # needs >= iteration + 2 = 4


def test_lrd_self_supersedes(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001", supersedes="loop-resume-decision://LRD-001"),
    ]
    codes = _codes(docs)
    assert "LRD_SUPERSEDES" in codes
    # недопустимое ребро не деактивирует единственное решение
    assert "LRD_DUP" not in codes


def test_lrd_supersedes_cycle(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001", supersedes="loop-resume-decision://LRD-002"),
        _lrd("LRD-002", supersedes="loop-resume-decision://LRD-001"),
    ]
    assert "LRD_SUPERSEDES" in _codes(docs)


def test_lrd_foreign_identity_supersedes(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001", iteration=0),
        _lrd("LRD-002", iteration=1, supersedes="loop-resume-decision://LRD-001"),
    ]
    assert "LRD_SUPERSEDES" in _codes(docs)


def test_lrd_duplicate_active(bundle: list[Doc]) -> None:
    docs = [*bundle, _loop_state(), _lrd("LRD-001"), _lrd("LRD-002", budget=4)]
    assert "LRD_DUP" in _codes(docs)


def test_lrd_chain_single_active_is_clean(bundle: list[Doc]) -> None:
    """A <- B <- C: активна только C, нарушений нет."""
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001"),
        _lrd("LRD-002", budget=4, supersedes="loop-resume-decision://LRD-001"),
        _lrd("LRD-003", budget=5, supersedes="loop-resume-decision://LRD-002"),
    ]
    codes = _codes(docs)
    assert not codes & {"LRD_SUPERSEDES", "LRD_DUP", "LRD_LOOP", "LRD_BUDGET"}


def test_lrd_dangling_supersedes_is_ref_dangling(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-002", supersedes="loop-resume-decision://LRD-999"),
    ]
    assert "REF_DANGLING" in _codes(docs)
