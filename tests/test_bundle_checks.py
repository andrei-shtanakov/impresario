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


def test_pilot_pp101_bundle_is_clean_with_backfilled_lrd() -> None:
    """Живой пилот проходит валидатор; бэкфилл-LRD присутствует и активен."""
    from impresario.cli import validate_paths

    from .conftest import CONTRACTS_DIR, REPO_ROOT

    pilot_ws = REPO_ROOT / "pilot" / "forconcept" / "pp-101"
    lrd = load_doc(pilot_ws / "decisions" / "lrd-001.yaml")
    assert lrd.kind == "loop-resume-decision"
    assert lrd.data["subject"] == {"loop_id": "LOOP-101", "iteration": 1}
    assert lrd.data["decided_at"] == "2026-08-12T04:01:21Z"
    report = validate_paths([pilot_ws], CONTRACTS_DIR, bundle=True)
    assert report.ok, [f"{f.code}: {f.message}" for f in report.errors]


def _brief_doc() -> Doc:
    from impresario.harness import brief_identity, sha256_bytes

    prompt = "оцени идею\n"
    fields = {
        "idea_ref": "idea://IDEA-001",
        "input_hash": "sha256:" + "a" * 64,
        "prompt_version": "prioritizer/v1",
        "prompt_pack_hash": "sha256:" + "b" * 64,
        "policy_version": "scoring/v1",
        "strategy_hash": "sha256:" + "c" * 64,
        "standards_hash": "sha256:" + "d" * 64,
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    data = {"brief_id": brief_identity(fields), **fields, "prompt": prompt}
    return Doc(path=Path("brf.yaml"), kind="evaluation-brief", data=data)


def test_brief_identity_clean(bundle: list[Doc]) -> None:
    assert "BRIEF_IDENTITY" not in _codes([*bundle, _brief_doc()])


def test_brief_identity_tampered_prompt(bundle: list[Doc]) -> None:
    doc = _brief_doc()
    data = dict(doc.data, prompt=doc.data["prompt"] + "инъекция\n")
    docs = [*bundle, Doc(path=doc.path, kind=doc.kind, data=data)]
    findings = run_bundle_checks(docs)
    codes = {f.code for f in findings}
    assert "BRIEF_IDENTITY" in codes  # шаг 1: prompt_hash ≠ байты
    # Optional hardening: exactly one BRIEF_IDENTITY finding for the tampered doc.
    brief_findings = [f for f in findings if f.code == "BRIEF_IDENTITY"]
    assert len(brief_findings) == 1
    assert "prompt_hash" in brief_findings[0].message


def test_brief_identity_tampered_field(bundle: list[Doc]) -> None:
    doc = _brief_doc()
    data = dict(doc.data, policy_version="scoring/v2")
    docs = [*bundle, Doc(path=doc.path, kind=doc.kind, data=data)]
    assert "BRIEF_IDENTITY" in _codes(docs)  # шаг 2: brief_id ≠ пересчёт


def _assessment_with_provenance(brief: Doc) -> Doc:
    data = {
        "assessment_id": "ASMT-900",
        "idea_ref": brief.data["idea_ref"],
        "run_id": "RUN-900",
        "input_hash": brief.data["input_hash"],
        "policy_version": "scoring/v1",
        "evidence_refs": [],
        "fit_strategy": 4,
        "fit_market": 4,
        "fit_standards": 4,
        "strategy_blocker": False,
        "standards_blocker": False,
        "confidence": "medium",
        "evaluator": {
            "kind": "agent",
            "id": "claude",
            "model": "m",
            "prompt_version": brief.data["prompt_version"],
        },
        "evaluated_at": "2026-08-16T12:00:00Z",
        "provenance": {
            "brief_id": brief.data["brief_id"],
            "prompt_pack_hash": brief.data["prompt_pack_hash"],
            "strategy_hash": brief.data["strategy_hash"],
            "standards_hash": brief.data["standards_hash"],
        },
    }
    return Doc(path=Path("asmt-900.yaml"), kind="axis-assessment", data=data)


def test_assess_brief_clean(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    docs = [*bundle, brief, _assessment_with_provenance(brief)]
    assert "ASSESS_BRIEF" not in _codes(docs)


def test_assess_brief_dangling(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    docs = [*bundle, _assessment_with_provenance(brief)]  # brief не включён
    assert "ASSESS_BRIEF" in _codes(docs)


def test_assess_brief_hash_mismatch(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    asmt = _assessment_with_provenance(brief)
    data = dict(asmt.data)
    data["provenance"] = dict(data["provenance"], strategy_hash="sha256:" + "9" * 64)
    docs = [*bundle, brief, Doc(path=asmt.path, kind=asmt.kind, data=data)]
    assert "ASSESS_BRIEF" in _codes(docs)


def test_assess_brief_input_hash_mismatch(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    asmt = _assessment_with_provenance(brief)
    data = dict(asmt.data, input_hash="sha256:" + "9" * 64)
    docs = [*bundle, brief, Doc(path=asmt.path, kind=asmt.kind, data=data)]
    assert "ASSESS_BRIEF" in _codes(docs)


def test_assess_brief_skips_manual_v0(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    asmt = _assessment_with_provenance(brief)
    data = {k: v for k, v in asmt.data.items() if k != "provenance"}
    docs = [*bundle, Doc(path=asmt.path, kind=asmt.kind, data=data)]
    assert "ASSESS_BRIEF" not in _codes(docs)


def test_assess_brief_duplicate_brief_id_order_independent(
    bundle: list[Doc],
) -> None:
    """Duplicate brief_id detection is order-independent (exact-one constraint).

    Two briefs with the same brief_id but different strategy_hash values
    in different orderings should both report ASSESS_BRIEF for the matching
    assessment, not silently pick one (last-wins bug).
    """
    # Create two briefs with identical brief_id but different strategy_hash.
    base = _brief_doc()
    brief1 = base
    # Create a second brief with the same brief_id but tampered strategy_hash.
    brief2_data = dict(base.data, strategy_hash="sha256:" + "e" * 64)
    brief2 = Doc(path=Path("brf2.yaml"), kind=base.kind, data=brief2_data)

    # Ensure they have the same brief_id (they do via constructor).
    assert brief1.data["brief_id"] == brief2.data["brief_id"]

    asmt = _assessment_with_provenance(brief1)

    # Test order 1: [brief1, brief2, asmt]
    codes1 = _codes([*bundle, brief1, brief2, asmt])
    assert "ASSESS_BRIEF" in codes1, (
        "Expected ASSESS_BRIEF for duplicate brief_ids (order 1)"
    )

    # Test order 2: [brief2, brief1, asmt] — must also find ASSESS_BRIEF.
    codes2 = _codes([*bundle, brief2, brief1, asmt])
    assert "ASSESS_BRIEF" in codes2, (
        "Expected ASSESS_BRIEF for duplicate brief_ids (order 2)"
    )


def _stage_brief_doc() -> Doc:
    from impresario.harness import sha256_bytes
    from impresario.loop_harness import stage_brief_identity

    prompt = "исследуй\n"
    fields = {
        "loop_id": "LOOP-001",
        "iteration": 0,
        "role": "researcher",
        "prompt_version": "researcher/v1",
        "prompt_pack_hash": "sha256:" + "b" * 64,
        "idea_input_hash": "sha256:" + "a" * 64,
        "proposal_hash": "sha256:" + "c" * 64,
        "history_hash": "sha256:" + "d" * 64,
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    data = {
        "schema_version": "stage-brief/v1",
        "brief_id": stage_brief_identity(fields),
        **fields,
        "prompt": prompt,
    }
    return Doc(path=Path("sbr.yaml"), kind="stage-brief", data=data)


def test_stage_brief_identity_clean_and_tampered(bundle: list[Doc]) -> None:
    good = _stage_brief_doc()
    assert "BRIEF_IDENTITY" not in _codes([*bundle, good])
    t1 = Doc(
        path=good.path,
        kind=good.kind,
        data=dict(good.data, prompt=good.data["prompt"] + "x"),
    )
    assert "BRIEF_IDENTITY" in _codes([*bundle, t1])
    t2 = Doc(path=good.path, kind=good.kind, data=dict(good.data, role="creator"))
    assert "BRIEF_IDENTITY" in _codes([*bundle, t2])


def _rp_with_provenance(brief: Doc) -> Doc:
    data = {
        "id": "RP-900",
        "idea_ref": "idea://IDEA-001",
        "iteration": 0,
        "findings": [],
        "constraints": [],
        "gaps": [],
        "brief_for_creator": "b",
        "requests_to_creator": [],
        "produced_by": {
            "kind": "agent",
            "id": "claude",
            "model": "m",
            "prompt_version": brief.data["prompt_version"],
        },
        "produced_at": "2026-08-16T12:00:00Z",
        "provenance": {
            "brief_id": brief.data["brief_id"],
            "prompt_pack_hash": brief.data["prompt_pack_hash"],
        },
    }
    return Doc(path=Path("rp-900.yaml"), kind="research-pack", data=data)


def test_artifact_brief_clean(bundle: list[Doc]) -> None:
    brief = _stage_brief_doc()
    docs = [*bundle, brief, _rp_with_provenance(brief)]
    assert "ARTIFACT_BRIEF" not in _codes(docs)


def test_artifact_brief_dangling_and_mismatches(bundle: list[Doc]) -> None:
    brief = _stage_brief_doc()
    rp = _rp_with_provenance(brief)
    # висячий brief
    assert "ARTIFACT_BRIEF" in _codes([*bundle, rp])
    # расходящийся prompt_pack_hash
    d = dict(rp.data)
    d["provenance"] = dict(d["provenance"], prompt_pack_hash="sha256:" + "9" * 64)
    assert "ARTIFACT_BRIEF" in _codes(
        [*bundle, brief, Doc(path=rp.path, kind=rp.kind, data=d)]
    )
    # несовпадающая итерация артефакта с brief'ом
    d2 = dict(rp.data, iteration=1)
    assert "ARTIFACT_BRIEF" in _codes(
        [*bundle, brief, Doc(path=rp.path, kind=rp.kind, data=d2)]
    )
    # артефакт без provenance пропускается
    d3 = {k: v for k, v in rp.data.items() if k != "provenance"}
    assert "ARTIFACT_BRIEF" not in _codes(
        [*bundle, Doc(path=rp.path, kind=rp.kind, data=d3)]
    )


def test_artifact_brief_role_mismatch(bundle: list[Doc]) -> None:
    """A research-pack must be produced against a researcher-role brief."""
    brief = _stage_brief_doc()  # role: researcher
    creator_brief_data = dict(brief.data, role="creator")
    creator_brief = Doc(path=brief.path, kind=brief.kind, data=creator_brief_data)
    rp = _rp_with_provenance(brief)  # points at brief's brief_id (unchanged)
    assert "ARTIFACT_BRIEF" in _codes([*bundle, creator_brief, rp])


def test_artifact_brief_loop_id_mismatch(bundle: list[Doc]) -> None:
    """When a loop-state is present in the bundle, its loop_id must match."""
    brief = _stage_brief_doc()  # loop_id: LOOP-001
    rp = _rp_with_provenance(brief)
    foreign_loop_state = _loop_state(loop_id="LOOP-999")
    assert "ARTIFACT_BRIEF" in _codes([*bundle, brief, rp, foreign_loop_state])
