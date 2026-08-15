"""Typed QG-5 gates: computed readiness and immutable human decisions.

Gate semantics (docs/semantics.md): Gate A (qg5_business) takes
ready_for_business to business_approved; Gate B (qg5_committee) takes
business_approved to approved and opens only when the computed readiness
is ok — readiness is a precondition, never a persisted status. Every
decision is an immutable GateDecision; the proposal status after a
decision is defined by the FSM transition table, not by the decision name.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import workspace as ws
from .checks import parse_ts
from .loader import Doc, load_doc
from .report import Finding, Report
from .schemas import check_schema, load_validators

GATE_A = "qg5_business"
GATE_B = "qg5_committee"

# FSM transition table for gate decisions: (gate, decision, status_from)
# -> status_to; None means "return_to names the target explicitly".
_TRANSITIONS: dict[tuple[str, str, str], str | None] = {
    (GATE_A, "approve", "ready_for_business"): "business_approved",
    (GATE_B, "approve", "business_approved"): "approved",
    (GATE_A, "recycle", "ready_for_business"): None,
    (GATE_A, "recycle", "business_approved"): None,
    (GATE_B, "recycle", "business_approved"): None,
    (GATE_A, "hold", "ready_for_business"): "on_hold",
    (GATE_A, "hold", "business_approved"): "on_hold",
    (GATE_B, "hold", "business_approved"): "on_hold",
    (GATE_A, "kill", "ready_for_business"): "killed",
    (GATE_A, "kill", "business_approved"): "killed",
    (GATE_B, "kill", "business_approved"): "killed",
    (GATE_A, "resume", "on_hold"): None,
    (GATE_B, "resume", "on_hold"): None,
}


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _looks_like_placeholder(reason: str) -> bool:
    """Copy-pasted example placeholders must not become immutable evidence."""
    stripped = reason.strip()
    return (stripped.startswith("<") and stripped.endswith(">")) or not stripped


def _decisions(workspace: Path) -> list[Doc]:
    directory = ws.decisions_dir(workspace)
    if not directory.is_dir():
        return []
    # decisions/ also holds loop-resume-decision records (resume
    # authorizations); gate logic must only ever see gate decisions.
    docs = (load_doc(p) for p in sorted(directory.glob("*.yaml")))
    return [doc for doc in docs if doc.kind == "gate-decision"]


def _active(decisions: list[Doc]) -> list[Doc]:
    """Drop decisions superseded via the append-only supersedes chain."""
    superseded = {
        d.data["supersedes"]
        for d in decisions
        if isinstance(d.data.get("supersedes"), str)
    }
    return [
        d
        for d in decisions
        if f"gate-decision://{d.data['decision_id']}" not in superseded
    ]


_ARTIFACT_REF_RE = re.compile(
    r"^(?:research-pack|concept-draft)://([A-Z]{2}-[0-9]{3,})$"
)


def _resolve_ref(workspace: Path, ref: str | None) -> Doc | None:
    """Resolve an artifact ref to a workspace file, refusing anything that
    is not a well-formed contract ref (no path fragments reach the FS)."""
    if not isinstance(ref, str):
        return None
    match = _ARTIFACT_REF_RE.match(ref)
    if match is None:
        return None
    path = workspace / f"{match.group(1).lower()}.yaml"
    return load_doc(path) if path.exists() else None


def readiness(workspace: Path) -> tuple[bool, list[str]]:
    """Computed Gate B precondition: ok/blocked + reasons. Never persisted."""
    proposal = load_doc(workspace / "proposal.yaml")
    data = proposal.data
    reasons: list[str] = []
    if data["status"] != "business_approved":
        reasons.append(
            f"proposal is {data['status']}, Gate B requires business_approved"
        )
    proposal_ref = f"proposal://{data['proposal_id']}"
    active = [
        d
        for d in _active(_decisions(workspace))
        if d.data["subject"]["ref"] == proposal_ref
    ]
    if not any(
        d.data["gate_id"] == GATE_A and d.data["decision"] == "approve" for d in active
    ):
        reasons.append("no active Gate A (qg5_business) approve decision")

    from .loop import open_criticals

    cd = _resolve_ref(workspace, data.get("refs", {}).get("latest_concept_draft"))
    rp = _resolve_ref(workspace, data.get("refs", {}).get("latest_research_pack"))
    if cd is None or rp is None:
        reasons.append("latest research pack / concept draft not resolvable")
    else:
        reasons.extend(f"open critical — {c}" for c in open_criticals(rp, cd))
    return (not reasons, reasons)


def decide(
    workspace: Path,
    contracts_dir: Path,
    *,
    gate_id: str,
    decision: str,
    expected_version: int,
    actor: str,
    reason: str,
    role: str | None = None,
    return_to: str | None = None,
    required_changes: list[str] | None = None,
    review_after: str | None = None,
    supersedes: str | None = None,
    now_iso: str | None = None,
) -> tuple[Report, dict[str, Any] | None]:
    """Record an immutable human gate decision and apply the FSM transition.

    Fail-closed CAS: expected version, legal (gate, decision, status)
    transition, Gate B readiness, resume-after-hold — all verified under
    the single-writer lock before anything is written.
    """
    with ws.single_writer_lock(workspace):
        return _decide_locked(
            workspace,
            contracts_dir,
            gate_id=gate_id,
            decision=decision,
            expected_version=expected_version,
            actor=actor,
            reason=reason,
            role=role,
            return_to=return_to,
            required_changes=required_changes,
            review_after=review_after,
            supersedes=supersedes,
            now_iso=now_iso,
        )


def _decide_locked(
    workspace: Path,
    contracts_dir: Path,
    *,
    gate_id: str,
    decision: str,
    expected_version: int,
    actor: str,
    reason: str,
    role: str | None,
    return_to: str | None,
    required_changes: list[str] | None,
    review_after: str | None,
    supersedes: str | None,
    now_iso: str | None,
) -> tuple[Report, dict[str, Any] | None]:
    validators = load_validators(contracts_dir)
    report = Report()
    now = now_iso or _now_iso()

    def err(code: str, message: str) -> tuple[Report, None]:
        report.errors.append(
            Finding(code=code, path=str(workspace / "proposal.yaml"), message=message)
        )
        return report, None

    if _looks_like_placeholder(reason):
        return err(
            "USAGE",
            f"reason looks like an unfilled placeholder: {reason!r}; an "
            "immutable decision record needs the actual motivation",
        )

    proposal = load_doc(workspace / "proposal.yaml")
    data = proposal.data
    if data["version"] != expected_version:
        return err(
            "VERSION_CONFLICT",
            f"expected version {expected_version}, current is {data['version']}",
        )

    status = data["status"]
    transition = _TRANSITIONS.get((gate_id, decision, status))
    if (gate_id, decision, status) not in _TRANSITIONS:
        return err(
            "FSM_ILLEGAL",
            f"({gate_id}, {decision}) is not a legal transition from status {status}",
        )
    target = transition if transition is not None else return_to
    if target is None:
        return err("USAGE", f"decision {decision} requires --return-to")
    if decision == "recycle" and not required_changes:
        return err("USAGE", "decision recycle requires --required-change")

    proposal_ref = f"proposal://{data['proposal_id']}"
    all_decisions = _decisions(workspace)
    active = [
        d for d in _active(all_decisions) if d.data["subject"]["ref"] == proposal_ref
    ]

    if gate_id == GATE_B and decision == "approve":
        ok, reasons = readiness(workspace)
        if not ok:
            # Blocked readiness: the gate does not open and no decision
            # record is created (semantics: no false gate decisions).
            for blocked_reason in reasons:
                report.errors.append(
                    Finding(
                        code="READINESS_BLOCKED",
                        path=str(workspace / "proposal.yaml"),
                        message=blocked_reason,
                    )
                )
            return report, None

    if decision == "resume" and not any(
        d.data["gate_id"] == gate_id
        and d.data["decision"] == "hold"
        and parse_ts(d.data["decided_at"]) < parse_ts(now)
        for d in active
    ):
        return err(
            "RESUME_WITHOUT_HOLD",
            f"no active prior hold on {gate_id} to resume from",
        )

    existing_ids = {d.data["decision_id"] for d in all_decisions}
    decision_id = ws.next_id("GD", existing_ids=existing_ids)
    record: dict[str, Any] = {
        "decision_id": decision_id,
        "gate_id": gate_id,
        "subject": {
            "kind": "product_proposal",
            "ref": proposal_ref,
            "version": data["version"],
        },
        "decision": decision,
        "decided_by": {
            "kind": "human",
            "id": actor,
            **({"role": role} if role else {}),
        },
        "decided_at": now,
        "reason": reason,
        **({"required_changes": required_changes} if required_changes else {}),
        **({"return_to": return_to} if return_to else {}),
        **({"review_after": review_after} if review_after else {}),
        **({"supersedes": supersedes} if supersedes else {}),
        "artifacts_reviewed": [
            proposal_ref,
            *filter(
                None,
                (
                    data.get("refs", {}).get("latest_research_pack"),
                    data.get("refs", {}).get("latest_concept_draft"),
                ),
            ),
        ],
    }
    decision_path = ws.decisions_dir(workspace) / f"{decision_id.lower()}.yaml"
    report.errors.extend(
        check_schema(
            Doc(path=decision_path, kind="gate-decision", data=record),
            validators,
        )
    )

    new_proposal = dict(data)
    new_proposal["status"] = target
    new_proposal["version"] = data["version"] + 1
    new_proposal["updated_at"] = now
    report.errors.extend(
        check_schema(
            Doc(
                path=workspace / "proposal.yaml",
                kind="product-proposal",
                data=new_proposal,
            ),
            validators,
        )
    )
    if report.errors:
        return report, None

    ws.write_atomic(decision_path, ws.dump_yaml(record))
    ws.write_atomic(workspace / "proposal.yaml", ws.dump_yaml(new_proposal))
    return report, record
