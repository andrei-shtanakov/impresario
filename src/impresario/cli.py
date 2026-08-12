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

    args = parser.parse_args(argv)

    if args.command == "hash":
        print(json.dumps(cmd_hash(args.paths), ensure_ascii=False, indent=2))
        return 0
    if args.command == "backlog":
        return _run_backlog(args)

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


def cli_entry() -> None:
    """Console-script entry point."""
    raise SystemExit(main())
