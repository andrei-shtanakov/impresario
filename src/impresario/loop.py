"""Reference runner of the forconcept loop: researcher ↔ creator ↔ evaluator.

Semantics oracle for future execution backends. Design rules:

- Materialized artifacts are the only durable state: stage completion is
  derived from the artifacts on disk, so a crash between any two stages
  resumes without double-applying anything.
- Every agent call has an idempotency key (loop:iteration:role); replaying
  a completed call is a no-op because completion is visible on disk.
- The evaluator is deterministic: verdicts (continue | ready_for_business
  | needs_human | failed) follow documented rules, never taste.
- Fail-closed: an invalid artifact is never persisted; the loop stops with
  verdict=failed and the workspace stays at the last consistent state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import workspace as ws
from .agents import Agent, AgentError
from .hashing import canonical_doc_hash
from .loader import Doc, load_doc
from .report import Finding, Report
from .schemas import check_schema, load_validators

STATE_FILE = "loop.state"
TRACE_FILE = "trace.jsonl"

READY = "ready_for_business"
CONTINUE = "continue"
NEEDS_HUMAN = "needs_human"
FAILED = "failed"
PAUSED = "paused"


class LoopError(Exception):
    """A loop-workspace failure that is not an artifact finding."""


@dataclass
class LoopResult:
    """Outcome of one runner invocation."""

    verdict: str
    stop_reason: str | None = None
    iteration: int = 0
    proposal_version: int = 0
    report: Report = field(default_factory=Report)


def state_path(workspace: Path) -> Path:
    """Runner state file (config + terminal verdict; not a contract doc)."""
    return workspace / STATE_FILE


def _read_state(workspace: Path) -> dict[str, Any]:
    path = state_path(workspace)
    if not path.exists():
        raise LoopError(f"{path}: loop workspace is not initialized")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(workspace: Path, state: dict[str, Any]) -> None:
    ws.write_atomic(
        state_path(workspace), json.dumps(state, ensure_ascii=False, indent=2)
    )


def _trace(workspace: Path, event: dict[str, Any]) -> None:
    """Append a trace event; identical events are recorded once.

    Events are deterministic (fixed now, deterministic agents), so a resumed
    run re-deriving a step emits a byte-identical line — deduplication makes
    the trace itself idempotent and golden-comparable across crash/resume.
    """
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    path = workspace / TRACE_FILE
    if path.exists() and line in path.read_text(encoding="utf-8").splitlines():
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def init_loop(
    workspace: Path,
    idea_file: Path,
    *,
    loop_id: str,
    proposal_id: str,
    exchange_log_id: str,
    max_iterations: int,
    now_iso: str,
) -> None:
    """Create a loop workspace: pinned idea copy + draft proposal + state."""
    if state_path(workspace).exists():
        raise LoopError(f"{workspace}: already initialized")
    idea = load_doc(idea_file)
    if idea.kind != "idea":
        raise LoopError(f"{idea_file}: not an idea card")
    workspace.mkdir(parents=True, exist_ok=True)
    ws.write_atomic(workspace / "idea.yaml", idea_file.read_text(encoding="utf-8"))
    proposal = {
        "proposal_id": proposal_id,
        "idea_ref": f"idea://{idea.data['id']}",
        "version": 1,
        "status": "draft",
        "iteration": 0,
        "refs": {"exchange_log": f"exchange-log://{exchange_log_id}"},
        "content": {"delta_log": []},
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    ws.write_atomic(workspace / "proposal.yaml", ws.dump_yaml(proposal))
    _write_state(
        workspace,
        {
            "loop_id": loop_id,
            "idea_ref": f"idea://{idea.data['id']}",
            "idea_input_hash": canonical_doc_hash(idea.data),
            "proposal_id": proposal_id,
            "exchange_log_id": exchange_log_id,
            "max_iterations": max_iterations,
            "stop": None,
        },
    )


@dataclass
class _Ctx:
    workspace: Path
    validators: dict
    state: dict[str, Any]
    now: str
    report: Report

    @property
    def key_prefix(self) -> str:
        return str(self.state["loop_id"])

    def key(self, iteration: int, role: str) -> str:
        return f"{self.key_prefix}:{iteration}:{role}"


def _docs_of_kind(workspace: Path, kind: str) -> list[Doc]:
    docs = []
    for path in sorted(workspace.glob("*.yaml")):
        try:
            doc = load_doc(path)
        except Exception:  # noqa: BLE001 - non-contract files are not ours
            continue
        if doc.kind == kind:
            docs.append(doc)
    return docs


def _find_iteration(docs: list[Doc], iteration: int) -> Doc | None:
    return next((d for d in docs if d.data.get("iteration") == iteration), None)


def _load_exchange_log(ctx: _Ctx) -> dict[str, Any]:
    path = ctx.workspace / "exchange-log.yaml"
    if path.exists():
        return load_doc(path).data
    return {
        "id": ctx.state["exchange_log_id"],
        "proposal_ref": f"proposal://{ctx.state['proposal_id']}",
        "entries": [],
    }


def _append_exchange(
    ctx: _Ctx, iteration: int, actor: str, kind: str, ref: str
) -> None:
    """Idempotent append: one entry per (iteration, actor, artifact_ref)."""
    log = _load_exchange_log(ctx)
    if any(
        e["iteration"] == iteration and e["actor"] == actor and e["artifact_ref"] == ref
        for e in log["entries"]
    ):
        return
    log["entries"].append(
        {
            "iteration": iteration,
            "actor": actor,
            "artifact_kind": kind,
            "artifact_ref": ref,
            "at": ctx.now,
        }
    )
    ws.write_atomic(ctx.workspace / "exchange-log.yaml", ws.dump_yaml(log))


def _persist_artifact(
    ctx: _Ctx,
    produced: dict[str, Any],
    *,
    kind: str,
    role: str,
    iteration: int,
) -> Doc | None:
    """Validate an agent output fail-closed, then persist it durably."""
    doc = Doc(path=ctx.workspace / "candidate.yaml", kind=kind, data=produced)
    findings = check_schema(doc, ctx.validators)
    if produced.get("iteration") != iteration:
        findings.append(
            Finding(
                code="ITERATION_MISMATCH",
                path=str(ctx.workspace),
                message=(
                    f"{role} produced iteration "
                    f"{produced.get('iteration')} instead of {iteration}"
                ),
            )
        )
    if findings:
        ctx.report.errors.extend(findings)
        _trace(
            ctx.workspace,
            {
                "event": "artifact_rejected",
                "key": ctx.key(iteration, role),
                "kind": kind,
                "errors": [f.code for f in findings],
            },
        )
        return None
    artifact_id = produced.get("id", "artifact")
    path = ctx.workspace / f"{str(artifact_id).lower()}.yaml"
    ws.write_atomic(path, ws.dump_yaml(produced))
    _trace(
        ctx.workspace,
        {
            "event": "artifact_written",
            "key": ctx.key(iteration, role),
            "kind": kind,
            "artifact": artifact_id,
            "output_hash": canonical_doc_hash(produced),
        },
    )
    return Doc(path=path, kind=kind, data=produced)


def _apply_delta(ctx: _Ctx, proposal: Doc, rp: Doc, cd: Doc) -> Doc:
    """Apply a ConceptDraft to the proposal exactly once (idempotent).

    "Applied" is judged by the delta_log, not by the latest ref: a resume
    that re-walks earlier iterations must not re-apply their deltas just
    because a later draft became the latest one in the meantime.
    """
    cd_ref = f"concept-draft://{cd.data['id']}"
    delta_log = proposal.data.get("content", {}).get("delta_log", [])
    if any(entry.get("concept_draft") == cd.data["id"] for entry in delta_log):
        return proposal
    data = dict(proposal.data)
    refs = dict(data.get("refs", {}))
    refs["latest_research_pack"] = f"research-pack://{rp.data['id']}"
    refs["latest_concept_draft"] = cd_ref
    data["refs"] = refs
    data["iteration"] = cd.data["iteration"]
    data["version"] = data["version"] + 1
    data["updated_at"] = ctx.now
    content = dict(data.get("content", {}))
    delta_log = list(content.get("delta_log", []))
    delta_log.append(
        {
            "iteration": cd.data["iteration"],
            "concept_draft": cd.data["id"],
            "delta": cd.data["proposal_delta"],
        }
    )
    content["delta_log"] = delta_log
    data["content"] = content
    ctx.report.errors.extend(
        check_schema(
            Doc(path=proposal.path, kind="product-proposal", data=data),
            ctx.validators,
        )
    )
    if ctx.report.errors:
        return proposal
    ws.write_atomic(proposal.path, ws.dump_yaml(data))
    _append_exchange(
        ctx,
        cd.data["iteration"],
        "orchestration",
        "product_proposal_patch",
        f"proposal://{data['proposal_id']}",
    )
    _trace(
        ctx.workspace,
        {
            "event": "delta_applied",
            "iteration": cd.data["iteration"],
            "concept_draft": cd.data["id"],
            "proposal_version": data["version"],
        },
    )
    return Doc(path=proposal.path, kind="product-proposal", data=data)


def open_criticals(rp: Doc, cd: Doc) -> list[str]:
    """Open critical assumptions/gaps that block leaving the loop."""
    issues = [
        f"assumption: {a['text']}"
        for a in cd.data.get("assumptions", [])
        if a.get("blocks_approval")
        and not a.get("answered_by")
        and not a.get("human_waiver")
    ]
    issues.extend(
        f"gap: {g['what']}"
        for g in rp.data.get("gaps", [])
        if g.get("blocks_approval") and not g.get("closed")
    )
    return issues


def evaluate(rp: Doc, cd: Doc, iteration: int, max_iterations: int) -> tuple[str, str]:
    """Deterministic verdict for one completed iteration."""
    issues = open_criticals(rp, cd)
    requests = cd.data.get("requests_to_researcher", [])
    if not issues and not requests:
        return READY, "no open critical assumptions/gaps and no open requests"
    if iteration + 1 < max_iterations:
        return CONTINUE, (
            f"open: {len(issues)} critical(s), {len(requests)} request(s)"
        )
    return NEEDS_HUMAN, "max_iterations reached with open critical items: " + (
        "; ".join(issues) if issues else f"{len(requests)} open request(s)"
    )


def _set_status(ctx: _Ctx, proposal: Doc, status: str) -> Doc:
    if proposal.data["status"] == status:
        return proposal
    data = dict(proposal.data)
    old = data["status"]
    data["status"] = status
    data["version"] = data["version"] + 1
    data["updated_at"] = ctx.now
    ws.write_atomic(proposal.path, ws.dump_yaml(data))
    _trace(
        ctx.workspace,
        {
            "event": "transition",
            "from": old,
            "to": status,
            "proposal_version": data["version"],
        },
    )
    return Doc(path=proposal.path, kind="product-proposal", data=data)


def run_loop(
    workspace: Path,
    contracts_dir: Path,
    agent: Agent,
    *,
    now_iso: str,
    stop_after: str | None = None,
) -> LoopResult:
    """Run (or resume) the loop until a verdict or the stop_after boundary.

    Invoking again after a pause resumes exactly where the artifacts say
    the loop stopped; invoking after a terminal verdict is a no-op that
    reports the recorded verdict.
    """
    state = _read_state(workspace)
    if state.get("stop"):
        stop = state["stop"]
        proposal = load_doc(workspace / "proposal.yaml")
        return LoopResult(
            verdict=stop["verdict"],
            stop_reason=stop["reason"],
            iteration=proposal.data["iteration"],
            proposal_version=proposal.data["version"],
        )

    validators = load_validators(contracts_dir)
    ctx = _Ctx(
        workspace=workspace,
        validators=validators,
        state=state,
        now=now_iso,
        report=Report(),
    )
    max_iterations = int(state["max_iterations"])
    proposal = load_doc(workspace / "proposal.yaml")

    def paused(iteration: int) -> LoopResult:
        return LoopResult(
            verdict=PAUSED,
            stop_reason=f"stop_after={stop_after}",
            iteration=iteration,
            proposal_version=load_doc(workspace / "proposal.yaml").data["version"],
            report=ctx.report,
        )

    def fail(iteration: int, reason: str) -> LoopResult:
        state["stop"] = {"verdict": FAILED, "reason": reason}
        _write_state(workspace, state)
        _trace(
            workspace,
            {
                "event": "stopped",
                "verdict": FAILED,
                "reason": reason,
                "iteration": iteration,
            },
        )
        return LoopResult(
            verdict=FAILED,
            stop_reason=reason,
            iteration=iteration,
            proposal_version=proposal.data["version"],
            report=ctx.report,
        )

    proposal = _set_status(ctx, proposal, "in_iteration")
    if stop_after == "start":
        return paused(0)

    for iteration in range(max_iterations):
        rps = _docs_of_kind(workspace, "research-pack")
        rp = _find_iteration(rps, iteration)
        if rp is None:
            try:
                produced = agent.produce("researcher", iteration)
            except AgentError as exc:
                return fail(iteration, f"researcher: {exc}")
            rp = _persist_artifact(
                ctx,
                produced,
                kind="research-pack",
                role="researcher",
                iteration=iteration,
            )
            if rp is None:
                return fail(iteration, "researcher produced invalid artifact")
        _append_exchange(
            ctx,
            iteration,
            "researcher",
            "research_pack",
            f"research-pack://{rp.data['id']}",
        )
        if stop_after == f"research:{iteration}":
            return paused(iteration)

        cds = _docs_of_kind(workspace, "concept-draft")
        cd = _find_iteration(cds, iteration)
        if cd is None:
            try:
                produced = agent.produce("creator", iteration)
            except AgentError as exc:
                return fail(iteration, f"creator: {exc}")
            expected_rp = f"research-pack://{rp.data['id']}"
            if produced.get("based_on_research", {}).get("ref") != expected_rp:
                return fail(
                    iteration,
                    f"creator draft is not based on {expected_rp} "
                    "(stale research reference)",
                )
            cd = _persist_artifact(
                ctx,
                produced,
                kind="concept-draft",
                role="creator",
                iteration=iteration,
            )
            if cd is None:
                return fail(iteration, "creator produced invalid artifact")
        _append_exchange(
            ctx,
            iteration,
            "creator",
            "concept_draft",
            f"concept-draft://{cd.data['id']}",
        )
        if stop_after == f"concept:{iteration}":
            return paused(iteration)

        proposal = _apply_delta(ctx, proposal, rp, cd)
        if ctx.report.errors:
            return fail(iteration, "proposal delta failed validation")
        if stop_after == f"apply:{iteration}":
            return paused(iteration)

        verdict, reason = evaluate(rp, cd, iteration, max_iterations)
        _trace(
            workspace,
            {
                "event": "verdict",
                "iteration": iteration,
                "verdict": verdict,
                "reason": reason,
            },
        )
        if verdict == READY:
            proposal = _set_status(ctx, proposal, READY)
            state["stop"] = {"verdict": READY, "reason": reason}
            _write_state(workspace, state)
            return LoopResult(
                verdict=READY,
                stop_reason=reason,
                iteration=iteration,
                proposal_version=proposal.data["version"],
                report=ctx.report,
            )
        if verdict == NEEDS_HUMAN:
            state["stop"] = {"verdict": NEEDS_HUMAN, "reason": reason}
            _write_state(workspace, state)
            return LoopResult(
                verdict=NEEDS_HUMAN,
                stop_reason=reason,
                iteration=iteration,
                proposal_version=proposal.data["version"],
                report=ctx.report,
            )
        if stop_after == f"evaluate:{iteration}":
            return paused(iteration)

    raise LoopError("loop ended without a verdict")  # pragma: no cover
