"""CLI: deterministic validation with a JSON report and stable exit codes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .checks import run_bundle_checks
from .loader import Doc, UnknownContractError, collect_doc_paths, load_doc
from .report import EXIT_USAGE, Finding, Report
from .schemas import check_schema, find_contracts_dir, load_validators


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
    args = parser.parse_args(argv)

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


def cli_entry() -> None:
    """Console-script entry point."""
    raise SystemExit(main())
