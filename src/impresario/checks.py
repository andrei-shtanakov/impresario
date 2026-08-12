"""Cross-artifact (bundle) checks: refs, backlog, FSM/gates, freshness."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .loader import Doc
from .report import Finding

_REF_RE = re.compile(
    r"^(idea|assessment|backlog|research-pack|concept-draft"
    r"|exchange-log|proposal|gate-decision)://\S+$"
)

_KIND_TO_SCHEME = {
    "idea": "idea",
    "axis-assessment": "assessment",
    "ranked-backlog": "backlog",
    "research-pack": "research-pack",
    "concept-draft": "concept-draft",
    "exchange-log": "exchange-log",
    "product-proposal": "proposal",
    "gate-decision": "gate-decision",
    # run:// is not a resolvable ref scheme (last_run_id is a plain id), but
    # every doc needs a canonical ref for the known-set in check_refs.
    "run-record": "run",
}

_ID_FIELDS = ("id", "assessment_id", "proposal_id", "decision_id")

GATED_STATUSES = ("ready_for_business", "business_approved", "approved")


def _doc_id(doc: Doc) -> str:
    for f in _ID_FIELDS:
        value = doc.data.get(f)
        if isinstance(value, str):
            return value
    return "<no-id>"


def _doc_ref(doc: Doc) -> str:
    return f"{_KIND_TO_SCHEME[doc.kind]}://{_doc_id(doc)}"


def _iter_ref_strings(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, str):
        if _REF_RE.match(value):
            refs.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            refs.extend(_iter_ref_strings(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_iter_ref_strings(child))
    return refs


def check_refs(docs: list[Doc]) -> list[Finding]:
    """Every internal ref of a known scheme must resolve within the bundle."""
    known = {_doc_ref(doc) for doc in docs}
    findings = []
    for doc in docs:
        unique_refs = dict.fromkeys(_iter_ref_strings(doc.data))
        findings.extend(
            Finding(
                code="REF_DANGLING",
                path=str(doc.path),
                message=f"unresolved internal ref {ref}",
            )
            for ref in unique_refs
            if ref not in known
        )
    return findings


def check_backlogs(docs: list[Doc]) -> list[Finding]:
    """Rank uniqueness among fully scored backlog items."""
    findings = []
    for doc in docs:
        if doc.kind != "ranked-backlog":
            continue
        seen: dict[int, str] = {}
        for item in doc.data.get("items", []):
            rank, idea = item.get("rank"), item.get("idea_ref", "?")
            if rank in seen:
                findings.append(
                    Finding(
                        code="BL_RANK_DUP",
                        path=str(doc.path),
                        message=f"rank {rank} used by {seen[rank]} and {idea}",
                    )
                )
            elif isinstance(rank, int):
                seen[rank] = idea
    return findings


def parse_ts(value: Any) -> datetime:
    """Parse an RFC 3339 timestamp; naive/broken values sort first."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def _decisions_for(docs: list[Doc], subject_ref: str) -> list[dict[str, Any]]:
    return sorted(
        (
            doc.data
            for doc in docs
            if doc.kind == "gate-decision"
            and doc.data.get("subject", {}).get("ref") == subject_ref
        ),
        key=lambda d: parse_ts(d.get("decided_at")),
    )


def _active_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop decisions superseded by a later record's `supersedes` ref."""
    superseded = {
        d["supersedes"] for d in decisions if isinstance(d.get("supersedes"), str)
    }
    return [
        d
        for d in decisions
        if f"gate-decision://{d.get('decision_id')}" not in superseded
    ]


def _has(decisions: list[dict[str, Any]], gate_id: str, decision: str) -> bool:
    return any(
        d.get("gate_id") == gate_id and d.get("decision") == decision for d in decisions
    )


def _check_proposal_gates(doc: Doc, decisions: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    path, data = str(doc.path), doc.data
    status = data.get("status")

    def err(code: str, message: str) -> None:
        findings.append(Finding(code=code, path=path, message=message))

    version = data.get("version", 0)
    for d in decisions:
        if d.get("subject", {}).get("version", 0) > version:
            err(
                "GD_VERSION_AHEAD",
                f"{d.get('decision_id')} decides version "
                f"{d['subject']['version']} > proposal version {version}",
            )

    active = _active_decisions(decisions)
    business_approves = [
        d
        for d in active
        if d.get("gate_id") == "qg5_business" and d.get("decision") == "approve"
    ]
    for d in active:
        at = parse_ts(d.get("decided_at"))
        if d.get("gate_id") == "qg5_committee":
            prior = [
                b for b in business_approves if parse_ts(b.get("decided_at")) <= at
            ]
            if not prior:
                err(
                    "GATE_ORDER",
                    f"{d.get('decision_id')}: Gate B decision without prior "
                    "qg5_business approve",
                )
        if d.get("decision") == "resume":
            prior_holds = [
                h
                for h in active
                if h.get("gate_id") == d.get("gate_id")
                and h.get("decision") == "hold"
                and parse_ts(h.get("decided_at")) < at
            ]
            if not prior_holds:
                err(
                    "RESUME_WITHOUT_HOLD",
                    f"{d.get('decision_id')}: resume without a prior hold "
                    f"on {d.get('gate_id')}",
                )

    if status == "approved":
        if not business_approves:
            err("FSM_EVIDENCE", "status approved without qg5_business approve")
        if not _has(active, "qg5_committee", "approve"):
            err("FSM_EVIDENCE", "status approved without qg5_committee approve")
    elif status == "business_approved" and not business_approves:
        err(
            "FSM_EVIDENCE",
            "status business_approved without qg5_business approve",
        )
    elif status == "on_hold" and not any(d.get("decision") == "hold" for d in active):
        err("FSM_EVIDENCE", "status on_hold without a hold decision")
    elif status == "killed" and not any(d.get("decision") == "kill" for d in active):
        err("FSM_EVIDENCE", "status killed without a kill decision")
    return findings


def _resolve(docs: list[Doc], ref: str | None) -> Doc | None:
    if not ref:
        return None
    return next((doc for doc in docs if _doc_ref(doc) == ref), None)


def _check_ownership(
    proposal: Doc, artifact: Doc | None, findings: list[Finding]
) -> Doc | None:
    """An artifact used as gate evidence must belong to the same idea/proposal."""
    if artifact is None:
        return None
    same_idea = artifact.data.get("idea_ref") == proposal.data.get("idea_ref")
    artifact_pp = artifact.data.get("proposal_ref")
    same_proposal = artifact_pp is None or artifact_pp == _doc_ref(proposal)
    if same_idea and same_proposal:
        return artifact
    findings.append(
        Finding(
            code="REF_FOREIGN",
            path=str(proposal.path),
            message=(
                f"{_doc_ref(artifact)} belongs to "
                f"{artifact_pp or artifact.data.get('idea_ref')}, not to "
                f"{_doc_ref(proposal)} / {proposal.data.get('idea_ref')}"
            ),
        )
    )
    return None


def _check_proposal_readiness(doc: Doc, docs: list[Doc]) -> list[Finding]:
    findings: list[Finding] = []
    path, data = str(doc.path), doc.data
    if data.get("status") not in GATED_STATUSES:
        return findings
    refs = data.get("refs", {})

    latest_cd = _check_ownership(
        doc, _resolve(docs, refs.get("latest_concept_draft")), findings
    )
    if latest_cd is not None:
        for assumption in latest_cd.data.get("assumptions", []):
            if (
                assumption.get("blocks_approval")
                and not assumption.get("answered_by")
                and not assumption.get("human_waiver")
            ):
                findings.append(
                    Finding(
                        code="ASSUMPTION_OPEN",
                        path=path,
                        message=(
                            f"critical assumption open at status "
                            f"{data.get('status')}: {assumption.get('text')}"
                        ),
                    )
                )
        alternatives = latest_cd.data.get("alternatives", [])
        if len(alternatives) < 3 and not latest_cd.data.get(
            "single_path_justification"
        ):
            findings.append(
                Finding(
                    code="ALTERNATIVES_MISSING",
                    path=str(latest_cd.path),
                    message=(
                        f"{len(alternatives)} alternative(s) without "
                        "single_path_justification"
                    ),
                )
            )

    latest_rp = _check_ownership(
        doc, _resolve(docs, refs.get("latest_research_pack")), findings
    )
    if latest_rp is not None:
        findings.extend(
            Finding(
                code="GAP_OPEN",
                path=path,
                message=(
                    f"critical gap open at status {data.get('status')}: "
                    f"{gap.get('what')}"
                ),
            )
            for gap in latest_rp.data.get("gaps", [])
            if gap.get("blocks_approval") and not gap.get("closed")
        )
    return findings


def check_proposals(docs: list[Doc]) -> list[Finding]:
    """FSM evidence, gate order and readiness preconditions per proposal."""
    findings = []
    for doc in docs:
        if doc.kind != "product-proposal":
            continue
        decisions = _decisions_for(docs, _doc_ref(doc))
        findings.extend(_check_proposal_gates(doc, decisions))
        findings.extend(_check_proposal_readiness(doc, docs))
    return findings


def check_concept_drafts(docs: list[Doc]) -> list[Finding]:
    """ConceptDraft must reference the freshest ResearchPack it could see."""
    findings = []
    rps_by_idea: dict[str, list[Doc]] = {}
    for doc in docs:
        if doc.kind == "research-pack":
            rps_by_idea.setdefault(str(doc.data.get("idea_ref")), []).append(doc)
    for doc in docs:
        if doc.kind != "concept-draft":
            continue
        based_on = doc.data.get("based_on_research", {})
        based_iter = based_on.get("iteration", -1)
        referenced = _resolve(docs, based_on.get("ref"))
        if referenced is not None and referenced.data.get("iteration") != based_iter:
            findings.append(
                Finding(
                    code="RP_ITERATION_MISMATCH",
                    path=str(doc.path),
                    message=(
                        f"based_on_research.iteration={based_iter} but "
                        f"{based_on.get('ref')} has iteration "
                        f"{referenced.data.get('iteration')}"
                    ),
                )
            )
        cd_iter = doc.data.get("iteration", 0)
        stale_over = [
            rp
            for rp in rps_by_idea.get(str(doc.data.get("idea_ref")), [])
            if based_iter < rp.data.get("iteration", -1) <= cd_iter
        ]
        if stale_over:
            findings.append(
                Finding(
                    code="RP_STALE",
                    path=str(doc.path),
                    message=(
                        f"references iteration {based_iter} while "
                        f"{stale_over[0].data.get('id')} (iteration "
                        f"{stale_over[0].data.get('iteration')}) was available"
                    ),
                )
            )
    return findings


def check_exchange_logs(docs: list[Doc]) -> list[Finding]:
    """ExchangeLog iterations must be monotonically non-decreasing."""
    findings = []
    for doc in docs:
        if doc.kind != "exchange-log":
            continue
        iterations = [
            entry.get("iteration", 0) for entry in doc.data.get("entries", [])
        ]
        if any(a > b for a, b in zip(iterations, iterations[1:], strict=False)):
            findings.append(
                Finding(
                    code="XLOG_ORDER",
                    path=str(doc.path),
                    message=f"iterations not monotonic: {iterations}",
                )
            )
    return findings


def run_bundle_checks(docs: list[Doc]) -> list[Finding]:
    """Run all cross-artifact checks over a bundle."""
    findings: list[Finding] = []
    findings.extend(check_refs(docs))
    findings.extend(check_backlogs(docs))
    findings.extend(check_proposals(docs))
    findings.extend(check_concept_drafts(docs))
    findings.extend(check_exchange_logs(docs))
    return findings
