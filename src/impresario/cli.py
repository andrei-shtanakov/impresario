"""CLI: deterministic validation with a JSON report and stable exit codes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .checks import run_bundle_checks
from .commands import cmd_hash, cmd_rank, cmd_select
from .loader import Doc, UnknownContractError, collect_doc_paths, load_doc
from .report import EXIT_USAGE, Finding, Report
from .schemas import check_schema, find_contracts_dir, load_validators
from .workspace import WorkspaceError


def validate_paths(paths: list[Path], contracts_dir: Path, bundle: bool) -> Report:
    """Validate documents; run cross-artifact checks in bundle mode."""
    validators = load_validators(contracts_dir)
    report = Report()
    docs: list[Doc] = []
    for path in collect_doc_paths(paths):
        try:
            doc = load_doc(path)
        except (UnknownContractError, ValueError, yaml.YAMLError) as exc:
            report.errors.append(Finding(code="LOAD", path=str(path), message=str(exc)))
            continue
        report.checked += 1
        schema_findings = check_schema(doc, validators)
        report.errors.extend(schema_findings)
        if not schema_findings:
            docs.append(doc)
    if bundle:
        report.errors.extend(run_bundle_checks(docs))
    return report


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns a stable exit code (0 clean, 1 violations, 2 usage)."""
    parser = argparse.ArgumentParser(
        prog="impresario",
        description="Product-governance contracts and enforcement tooling.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate",
        help="validate artifacts against contracts v1",
        description=(
            "Validate product-governance artifacts against contracts v1. "
            "Directories are validated as bundles (schema + cross-artifact "
            "checks); single files are schema-only unless --bundle is given."
        ),
    )
    validate.add_argument("paths", nargs="+", type=Path, help="files or bundle dirs")
    validate.add_argument(
        "--contracts",
        type=Path,
        default=None,
        help="contracts/ dir (default: found upward from cwd)",
    )
    validate.add_argument(
        "--bundle",
        action="store_true",
        help="force cross-artifact checks even for a list of files",
    )

    hash_cmd = subparsers.add_parser(
        "hash",
        help="canonical input_hash of documents (for authoring assessments)",
    )
    hash_cmd.add_argument("paths", nargs="+", type=Path)

    backlog = subparsers.add_parser(
        "backlog", help="Stage 4: deterministic rank and typed QG-4"
    )
    backlog_sub = backlog.add_subparsers(dest="backlog_command", required=True)

    rank = backlog_sub.add_parser(
        "rank",
        help="materialize RankedBacklog from ideas + assessments",
        description=(
            "Dry-run (default) prints the proposed backlog and writes "
            "nothing; --apply verifies input hashes and the expected "
            "version, then atomically writes backlog.yaml and an "
            "immutable run record."
        ),
    )
    rank.add_argument("workspace", type=Path, help="workspace dir (ideas/, ...)")
    rank.add_argument("--apply", action="store_true")
    rank.add_argument("--expected-version", type=int, default=None)
    rank.add_argument("--backlog-id", default=None, help="required for the first apply")
    rank.add_argument("--policy", type=Path, default=None)
    rank.add_argument("--actor", default=None)
    rank.add_argument("--contracts", type=Path, default=None)

    select = backlog_sub.add_parser(
        "select",
        help="typed QG-4: record a human select decision",
    )
    select.add_argument("workspace", type=Path)
    select.add_argument("idea_id", help="e.g. IDEA-101")
    select.add_argument("--expected-version", type=int, required=True)
    select.add_argument("--actor", required=True)
    select.add_argument("--reason", required=True)
    select.add_argument("--role", default=None)
    select.add_argument("--contracts", type=Path, default=None)

    forconcept = subparsers.add_parser(
        "forconcept", help="M2: reference runner of the researcher ↔ creator loop"
    )
    fc_sub = forconcept.add_subparsers(dest="fc_command", required=True)

    fc_init = fc_sub.add_parser(
        "init", help="create a loop workspace from a selected idea card"
    )
    fc_init.add_argument("workspace", type=Path)
    fc_init.add_argument("--idea-file", type=Path, required=True)
    fc_init.add_argument("--loop-id", required=True)
    fc_init.add_argument("--proposal-id", required=True)
    fc_init.add_argument("--exchange-log-id", required=True)
    fc_init.add_argument("--max-iterations", type=int, default=3)
    fc_init.add_argument("--contracts", type=Path, default=None)

    fc_run = fc_sub.add_parser(
        "run",
        help="run or resume the loop until a verdict",
        description=(
            "Idempotent: stage completion is derived from durable artifacts, "
            "so re-invoking after a crash resumes without double-applying. "
            "Terminal verdicts are recorded; re-running reports them."
        ),
    )
    fc_run.add_argument("workspace", type=Path)
    fc_run.add_argument("--script", type=Path, required=True)
    fc_run.add_argument(
        "--stop-after",
        default=None,
        help="pause boundary (start | research:N | concept:N | apply:N | "
        "evaluate:N) — for crash/resume drills",
    )
    fc_run.add_argument("--contracts", type=Path, default=None)

    fc_resume = fc_sub.add_parser(
        "resume",
        help="reopen a needs_human loop after a human addressed the blocker",
    )
    fc_resume.add_argument("workspace", type=Path)
    fc_resume.add_argument("--max-iterations", type=int, required=True)
    fc_resume.add_argument("--actor", required=True)
    fc_resume.add_argument("--reason", required=True)
    fc_resume.add_argument("--contracts", type=Path, default=None)

    gate = subparsers.add_parser(
        "gate", help="M4: typed QG-5 gates (readiness + immutable decisions)"
    )
    gate_sub = gate.add_subparsers(dest="gate_command", required=True)

    gate_ready = gate_sub.add_parser(
        "readiness",
        help="computed Gate B precondition (ok | blocked + reasons); never persisted",
    )
    gate_ready.add_argument("workspace", type=Path)

    gate_decide = gate_sub.add_parser(
        "decide", help="record an immutable human gate decision (FSM applies)"
    )
    gate_decide.add_argument("workspace", type=Path)
    gate_decide.add_argument(
        "--gate", required=True, choices=["qg5_business", "qg5_committee"]
    )
    gate_decide.add_argument(
        "--decision",
        required=True,
        choices=["approve", "recycle", "hold", "kill", "resume"],
    )
    gate_decide.add_argument("--expected-version", type=int, required=True)
    gate_decide.add_argument("--actor", required=True)
    gate_decide.add_argument("--reason", required=True)
    gate_decide.add_argument("--role", default=None)
    gate_decide.add_argument("--return-to", default=None)
    gate_decide.add_argument(
        "--required-change", action="append", default=None, dest="required_changes"
    )
    gate_decide.add_argument("--review-after", default=None)
    gate_decide.add_argument("--supersedes", default=None)
    gate_decide.add_argument("--contracts", type=Path, default=None)

    assess = subparsers.add_parser(
        "assess", help="prompt harness: render briefs / ingest answers"
    )
    assess_sub = assess.add_subparsers(dest="assess_command", required=True)
    a_render = assess_sub.add_parser(
        "render", help="deterministically render evaluation briefs"
    )
    a_render.add_argument("workspace", type=Path)
    a_render.add_argument("--idea", default=None)
    a_render.add_argument("--prompts", type=Path, default=None)
    a_render.add_argument("--contracts", type=Path, default=None)
    a_ingest = assess_sub.add_parser(
        "ingest", help="validate brief+answer pairs and materialize assessments"
    )
    a_ingest.add_argument("workspace", type=Path)
    a_ingest.add_argument("--run-id", required=True)
    a_ingest.add_argument("--actor", required=True)
    a_ingest.add_argument("--model", required=True)
    a_ingest.add_argument("--brief", action="append", required=True, type=Path)
    a_ingest.add_argument("--answer", action="append", required=True, type=Path)
    a_ingest.add_argument("--contracts", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "gate":
        return _run_gate(args)
    if args.command == "hash":
        print(json.dumps(cmd_hash(args.paths), ensure_ascii=False, indent=2))
        return 0
    if args.command == "backlog":
        return _run_backlog(args)
    if args.command == "forconcept":
        return _run_forconcept(args)
    if args.command == "assess":
        return _run_assess(args)

    def usage_error(message: str) -> int:
        report = Report()
        report.errors.append(Finding(code="USAGE", path="", message=message))
        _print_report(report)
        return EXIT_USAGE

    missing = [p for p in args.paths if not p.exists()]
    if missing:
        return usage_error(f"path not found: {missing[0]}")
    try:
        contracts_dir = args.contracts or find_contracts_dir(Path.cwd())
    except FileNotFoundError as exc:
        return usage_error(str(exc))

    bundle = args.bundle or any(p.is_dir() for p in args.paths)
    report = validate_paths(args.paths, contracts_dir, bundle=bundle)
    _print_report(report)
    return report.exit_code


def _print_report(report: Report) -> None:
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))


def _run_backlog(args) -> int:
    """Dispatch `impresario backlog rank|select` with a JSON report."""
    try:
        contracts_dir = args.contracts or find_contracts_dir(Path.cwd())
    except FileNotFoundError as exc:
        report = Report()
        report.errors.append(Finding(code="USAGE", path="", message=str(exc)))
        _print_report(report)
        return EXIT_USAGE

    try:
        if args.backlog_command == "rank":
            report, payload = cmd_rank(
                args.workspace,
                contracts_dir,
                apply=args.apply,
                expected_version=args.expected_version,
                backlog_id=args.backlog_id,
                policy_file=args.policy,
                actor=args.actor,
            )
            key = "backlog"
            mode = "apply" if args.apply else "dry-run"
        else:
            report, payload = cmd_select(
                args.workspace,
                contracts_dir,
                idea_id=args.idea_id,
                expected_version=args.expected_version,
                actor=args.actor,
                reason=args.reason,
                role=args.role,
            )
            key = "decision"
            mode = "select"
    except WorkspaceError as exc:
        report = Report()
        report.errors.append(
            Finding(code="WORKSPACE", path=str(args.workspace), message=str(exc))
        )
        _print_report(report)
        return report.exit_code

    out = report.as_dict()
    out["mode"] = mode
    if payload is not None:
        out[key] = payload
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return report.exit_code


def _run_forconcept(args) -> int:
    """Dispatch `impresario forconcept init|run` with a JSON report."""
    from datetime import UTC, datetime

    from .agents import AgentError, ScriptedAgent
    from .loop import FAILED, LoopError, init_loop, resume_loop, run_loop

    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        contracts_dir = args.contracts or find_contracts_dir(Path.cwd())
        if args.fc_command == "resume":
            decision_ref = resume_loop(
                args.workspace,
                contracts_dir,
                max_iterations=args.max_iterations,
                actor=args.actor,
                reason=args.reason,
                now_iso=now,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "resumed": str(args.workspace),
                        "decision": decision_ref,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.fc_command == "init":
            init_loop(
                args.workspace,
                args.idea_file,
                contracts_dir,
                loop_id=args.loop_id,
                proposal_id=args.proposal_id,
                exchange_log_id=args.exchange_log_id,
                max_iterations=args.max_iterations,
                now_iso=now,
            )
            print(json.dumps({"ok": True, "initialized": str(args.workspace)}))
            return 0
        result = run_loop(
            args.workspace,
            contracts_dir,
            ScriptedAgent.from_file(args.script),
            now_iso=now,
            stop_after=args.stop_after,
        )
    except (LoopError, AgentError, FileNotFoundError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return EXIT_USAGE

    out = {
        "ok": result.verdict != FAILED,
        "verdict": result.verdict,
        "stop_reason": result.stop_reason,
        "iteration": result.iteration,
        "proposal_version": result.proposal_version,
        "errors": [f.as_dict() for f in result.report.errors],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if result.verdict != FAILED else 1


def _run_assess(args) -> int:
    """Dispatch `impresario assess render|ingest` with a JSON report."""
    from datetime import UTC, datetime

    from .harness import HarnessError, find_prompts_dir, ingest_pairs, render_briefs

    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        contracts = args.contracts or find_contracts_dir(Path.cwd())
        if args.assess_command == "render":
            prompts = args.prompts or find_prompts_dir(Path.cwd())
            report = render_briefs(
                args.workspace, contracts, prompts, idea_id=args.idea
            )
        else:
            if len(args.brief) != len(args.answer):
                raise HarnessError("--brief and --answer must come in pairs")
            report = ingest_pairs(
                args.workspace,
                contracts,
                run_id=args.run_id,
                actor=args.actor,
                model=args.model,
                pairs=list(zip(args.brief, args.answer, strict=True)),
                now_iso=now,
            )
    except (HarnessError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return EXIT_USAGE
    print(json.dumps(report, ensure_ascii=False))
    return 0


def _run_gate(args) -> int:
    """Dispatch `impresario gate readiness|decide` with a JSON report."""
    from .gate import decide, readiness
    from .workspace import WorkspaceError as WsError

    if args.gate_command == "readiness":
        try:
            ok, reasons = readiness(args.workspace)
        except (FileNotFoundError, UnknownContractError, yaml.YAMLError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return EXIT_USAGE
        print(
            json.dumps(
                {"readiness": "ok" if ok else "blocked", "reasons": reasons},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    try:
        contracts_dir = args.contracts or find_contracts_dir(Path.cwd())
        report, record = decide(
            args.workspace,
            contracts_dir,
            gate_id=args.gate,
            decision=args.decision,
            expected_version=args.expected_version,
            actor=args.actor,
            reason=args.reason,
            role=args.role,
            return_to=args.return_to,
            required_changes=args.required_changes,
            review_after=args.review_after,
            supersedes=args.supersedes,
        )
    except (WsError, FileNotFoundError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return EXIT_USAGE

    out = report.as_dict()
    if record is not None:
        out["decision"] = record
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return report.exit_code


def cli_entry() -> None:
    """Console-script entry point."""
    raise SystemExit(main())
