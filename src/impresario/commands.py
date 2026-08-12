"""Stage 4 commands: rank (dry-run/CAS apply), typed QG-4 select, hash."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import workspace as ws
from .engine import Policy, build_backlog, normalize_assessments, policy_from_dict
from .hashing import canonical_doc_hash
from .loader import Doc, load_doc
from .report import Finding, Report
from .schemas import check_schema, load_validators


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_checked(
    path: Path, expect_kind: str, validators: dict, report: Report
) -> Doc | None:
    """Load one document, enforce its kind and schema; report violations."""
    try:
        doc = load_doc(path)
    except Exception as exc:  # noqa: BLE001 - every load failure is a finding
        report.errors.append(Finding(code="LOAD", path=str(path), message=str(exc)))
        return None
    report.checked += 1
    if doc.kind != expect_kind:
        report.errors.append(
            Finding(
                code="KIND",
                path=str(path),
                message=f"expected {expect_kind}, found {doc.kind}",
            )
        )
        return None
    findings = check_schema(doc, validators)
    report.errors.extend(findings)
    return None if findings else doc


def _load_dir(
    directory: Path, expect_kind: str, validators: dict, report: Report
) -> list[Doc]:
    docs = []
    for path in sorted(directory.glob("*.yaml")):
        doc = _load_checked(path, expect_kind, validators, report)
        if doc is not None:
            docs.append(doc)
    return docs


def cmd_hash(paths: list[Path]) -> dict[str, Any]:
    """Canonical input_hash of each document (for authoring assessments)."""
    return {str(path): canonical_doc_hash(load_doc(path).data) for path in paths}


def cmd_rank(
    workspace: Path,
    contracts_dir: Path,
    *,
    apply: bool,
    expected_version: int | None,
    backlog_id: str | None,
    policy_file: Path | None,
    actor: str | None,
    now_iso: str | None = None,
) -> tuple[Report, dict[str, Any] | None]:
    """Deterministic rank: dry-run proposes, apply materializes under CAS.

    Apply guards (each violation is a typed finding, nothing is written):
    schema of every input; assessment input_hash == current idea hash;
    expected backlog version; single-writer lock; validate-then-atomic-
    replace; monotonic version; immutable run record. In apply mode the
    whole read-check-write sequence runs under the lock so concurrent
    writers cannot invalidate the checks between reads and writes.
    """
    lock = ws.single_writer_lock(workspace) if apply else contextlib.nullcontext()
    with lock:
        return _rank_impl(
            workspace,
            contracts_dir,
            apply=apply,
            expected_version=expected_version,
            backlog_id=backlog_id,
            policy_file=policy_file,
            actor=actor,
            now_iso=now_iso,
        )


def _rank_impl(
    workspace: Path,
    contracts_dir: Path,
    *,
    apply: bool,
    expected_version: int | None,
    backlog_id: str | None,
    policy_file: Path | None,
    actor: str | None,
    now_iso: str | None,
) -> tuple[Report, dict[str, Any] | None]:
    validators = load_validators(contracts_dir)
    report = Report()
    now = now_iso or _now_iso()

    ideas = _load_dir(ws.ideas_dir(workspace), "idea", validators, report)
    assessments = _load_dir(
        ws.assessments_dir(workspace), "axis-assessment", validators, report
    )
    if not ideas:
        report.errors.append(
            Finding(
                code="USAGE",
                path=str(ws.ideas_dir(workspace)),
                message="no valid idea cards in workspace",
            )
        )
    if report.errors:
        return report, None

    idea_hashes = {f"idea://{d.data['id']}": canonical_doc_hash(d.data) for d in ideas}
    normalized = normalize_assessments([d.data for d in assessments])
    for idea_ref, assessment in sorted(normalized.items()):
        current = idea_hashes.get(idea_ref)
        if current is None:
            report.errors.append(
                Finding(
                    code="REF_DANGLING",
                    path=str(ws.assessments_dir(workspace)),
                    message=f"{assessment['assessment_id']}: {idea_ref} "
                    "is not in the workspace",
                )
            )
        elif assessment["input_hash"] != current:
            report.errors.append(
                Finding(
                    code="STALE_INPUT",
                    path=str(ws.assessments_dir(workspace)),
                    message=(
                        f"{assessment['assessment_id']}: idea {idea_ref} "
                        "changed after evaluation "
                        f"(evaluated {assessment['input_hash']}, "
                        f"current {current})"
                    ),
                )
            )

    current_backlog: Doc | None = None
    if ws.backlog_path(workspace).exists():
        current_backlog = _load_checked(
            ws.backlog_path(workspace), "ranked-backlog", validators, report
        )
        if current_backlog is None:
            return report, None

    version_before = current_backlog.data["version"] if current_backlog else None
    if apply and version_before is not None and expected_version != version_before:
        report.errors.append(
            Finding(
                code="VERSION_CONFLICT",
                path=str(ws.backlog_path(workspace)),
                message=(
                    f"expected version {expected_version}, current is {version_before}"
                ),
            )
        )
    if report.errors:
        return report, None

    resolved_backlog_id = current_backlog.data["id"] if current_backlog else backlog_id
    if resolved_backlog_id is None:
        report.errors.append(
            Finding(
                code="USAGE",
                path=str(workspace),
                message="--backlog-id is required for the first materialization",
            )
        )
        return report, None

    policy = _resolve_policy(policy_file)
    used_run_ids = {d.data["run_id"] for d in assessments} | {
        d.data["run_id"]
        for d in _load_dir(ws.runs_dir(workspace), "run-record", validators, Report())
    }
    run_id = ws.next_id("RUN", existing_ids=used_run_ids)

    proposed = build_backlog(
        backlog_id=resolved_backlog_id,
        version=(version_before or 0) + 1,
        ideas=[d.data for d in ideas],
        assessments_by_idea=normalized,
        policy=policy,
        run_id=run_id,
        now_iso=now,
    )
    proposed_doc = Doc(
        path=ws.backlog_path(workspace), kind="ranked-backlog", data=proposed
    )
    report.errors.extend(check_schema(proposed_doc, validators))
    if report.errors or not apply:
        return report, proposed

    run_record: dict[str, Any] = {
        "run_id": run_id,
        "at": now,
        "mode": "apply",
        "policy_version": policy.policy_version,
        "weights": dict(policy.weights),
        "backlog_ref": f"backlog://{resolved_backlog_id}",
        **(
            {"backlog_version_before": version_before}
            if version_before is not None
            else {}
        ),
        "backlog_version_after": proposed["version"],
        "inputs": [
            {
                "idea_ref": idea_ref,
                "input_hash": idea_hashes[idea_ref],
                **(
                    {
                        "assessment_ref": "assessment://"
                        + normalized[idea_ref]["assessment_id"]
                    }
                    if idea_ref in normalized
                    else {}
                ),
            }
            for idea_ref in sorted(idea_hashes)
        ],
        **({"actor": actor} if actor else {}),
    }
    run_path = ws.runs_dir(workspace) / f"{run_id.lower()}.yaml"
    report.errors.extend(
        check_schema(Doc(path=run_path, kind="run-record", data=run_record), validators)
    )
    if report.errors:
        return report, proposed

    # The caller already holds the single-writer lock in apply mode.
    ws.write_atomic(ws.backlog_path(workspace), ws.dump_yaml(proposed))
    ws.write_atomic(run_path, ws.dump_yaml(run_record))
    return report, proposed


def _resolve_policy(policy_file: Path | None) -> Policy:
    if policy_file is None:
        return Policy()
    data = yaml.safe_load(policy_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ws.WorkspaceError(f"{policy_file}: policy is not a mapping")
    return policy_from_dict(data)


def cmd_select(
    workspace: Path,
    contracts_dir: Path,
    *,
    idea_id: str,
    expected_version: int,
    actor: str,
    reason: str,
    role: str | None,
    now_iso: str | None = None,
) -> tuple[Report, dict[str, Any] | None]:
    """Typed QG-4: atomically record a human select decision.

    Verifies expected backlog version and that the idea is a selectable
    ranked item, then writes an immutable GateDecision, bumps the backlog
    version with the item marked selected, and updates the idea card's
    status line. Stale input fails the whole command; nothing is written.
    The whole read-check-write sequence runs under the single-writer lock,
    so a concurrent writer cannot invalidate the checks between the reads
    and the writes.
    """
    with ws.single_writer_lock(workspace):
        return _select_locked(
            workspace,
            contracts_dir,
            idea_id=idea_id,
            expected_version=expected_version,
            actor=actor,
            reason=reason,
            role=role,
            now_iso=now_iso,
        )


def _select_locked(
    workspace: Path,
    contracts_dir: Path,
    *,
    idea_id: str,
    expected_version: int,
    actor: str,
    reason: str,
    role: str | None,
    now_iso: str | None,
) -> tuple[Report, dict[str, Any] | None]:
    validators = load_validators(contracts_dir)
    report = Report()
    now = now_iso or _now_iso()

    backlog = _load_checked(
        ws.backlog_path(workspace), "ranked-backlog", validators, report
    )
    if backlog is None:
        return report, None
    data = backlog.data

    if data["version"] != expected_version:
        report.errors.append(
            Finding(
                code="VERSION_CONFLICT",
                path=str(ws.backlog_path(workspace)),
                message=(
                    f"expected version {expected_version}, current is {data['version']}"
                ),
            )
        )
        return report, None

    idea_ref = f"idea://{idea_id}"
    item = next((i for i in data.get("items", []) if i["idea_ref"] == idea_ref), None)
    if item is None:
        where = (
            "pending_unknown"
            if any(p["idea_ref"] == idea_ref for p in data.get("pending_unknown", []))
            else "excluded"
            if any(e["idea_ref"] == idea_ref for e in data.get("excluded", []))
            else "absent"
        )
        report.errors.append(
            Finding(
                code="NOT_SELECTABLE",
                path=str(ws.backlog_path(workspace)),
                message=f"{idea_ref} is not a ranked item ({where})",
            )
        )
        return report, None

    idea_files = sorted(ws.ideas_dir(workspace).glob("*.yaml"))
    idea_path = next(
        (p for p in idea_files if load_doc(p).data.get("id") == idea_id), None
    )
    if idea_path is None:
        report.errors.append(
            Finding(
                code="REF_DANGLING",
                path=str(ws.ideas_dir(workspace)),
                message=f"idea card {idea_id} not found in workspace",
            )
        )
        return report, None

    _check_selected_idea_freshness(
        workspace, data, idea_ref, idea_path, validators, report
    )
    if report.errors:
        return report, None

    existing_gd = {
        d.data["decision_id"]
        for d in _load_dir(
            ws.decisions_dir(workspace), "gate-decision", validators, Report()
        )
    }
    decision_id = ws.next_id("GD", existing_ids=existing_gd)
    decision: dict[str, Any] = {
        "decision_id": decision_id,
        "gate_id": "qg4_backlog",
        "subject": {
            "kind": "ranked_backlog",
            "ref": f"backlog://{data['id']}",
            "version": data["version"],
        },
        "decision": "select",
        "selected_idea_ref": idea_ref,
        "decided_by": {
            "kind": "human",
            "id": actor,
            **({"role": role} if role else {}),
        },
        "decided_at": now,
        "reason": reason,
        "artifacts_reviewed": [f"backlog://{data['id']}"],
    }
    decision_path = ws.decisions_dir(workspace) / f"{decision_id.lower()}.yaml"
    report.errors.extend(
        check_schema(
            Doc(path=decision_path, kind="gate-decision", data=decision),
            validators,
        )
    )

    new_backlog = dict(data)
    new_backlog["version"] = data["version"] + 1
    new_backlog["updated_at"] = now
    new_backlog["items"] = [
        {**i, "status": "selected"} if i["idea_ref"] == idea_ref else i
        for i in data["items"]
    ]
    report.errors.extend(
        check_schema(
            Doc(
                path=ws.backlog_path(workspace),
                kind="ranked-backlog",
                data=new_backlog,
            ),
            validators,
        )
    )
    if report.errors:
        return report, None

    # Pre-flight the card edit: every fallible step happens before the first
    # write, so a failure cannot leave decision/backlog/card half-applied.
    # The caller already holds the single-writer lock.
    updated_card = ws.prepare_idea_status(idea_path, "selected")

    ws.write_atomic(decision_path, ws.dump_yaml(decision))
    ws.write_atomic(ws.backlog_path(workspace), ws.dump_yaml(new_backlog))
    ws.write_atomic(idea_path, updated_card)
    return report, decision


def _check_selected_idea_freshness(
    workspace: Path,
    backlog: dict[str, Any],
    idea_ref: str,
    idea_path: Path,
    validators: dict,
    report: Report,
) -> None:
    """The selected card must be semantically what the rank evaluated.

    Equivalence is by canonical hash of the parsed document (comments and
    formatting do not count; field changes do). The run record behind the
    current backlog version (last_run_id) carries the input_hash of every
    idea; a mismatch means the card changed after ranking, so the rank the
    human is looking at is stale.
    """
    run_id = str(backlog.get("last_run_id"))
    run_path = ws.runs_dir(workspace) / f"{run_id.lower()}.yaml"
    if not run_path.exists():
        report.errors.append(
            Finding(
                code="RUN_RECORD_MISSING",
                path=str(run_path),
                message=(
                    f"run record {run_id} behind backlog version "
                    f"{backlog.get('version')} is missing; cannot prove the "
                    "rank is fresh"
                ),
            )
        )
        return
    run = _load_checked(run_path, "run-record", validators, report)
    if run is None:
        return
    recorded = next((i for i in run.data["inputs"] if i["idea_ref"] == idea_ref), None)
    current = canonical_doc_hash(load_doc(idea_path).data)
    if recorded is None or recorded["input_hash"] != current:
        report.errors.append(
            Finding(
                code="STALE_INPUT",
                path=str(idea_path),
                message=(
                    f"{idea_ref} changed after ranking run {run_id} "
                    f"(recorded {recorded['input_hash'] if recorded else 'nothing'}, "
                    f"current {current}); re-run backlog rank before selecting"
                ),
            )
        )
