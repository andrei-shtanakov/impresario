"""Loading contract JSON Schemas and running schema validation."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .loader import CONTRACT_KINDS, Doc
from .report import Finding


def find_contracts_dir(start: Path) -> Path:
    """Walk upward from *start* to find the contracts/ directory."""
    for candidate in (start, *start.resolve().parents):
        contracts = candidate / "contracts"
        if (contracts / "idea" / "v1" / "schema.json").is_file():
            return contracts
    raise FileNotFoundError(
        f"contracts/ directory with v1 schemas not found above {start}"
    )


def load_validators(contracts_dir: Path) -> dict[str, Draft202012Validator]:
    """Load one Draft 2020-12 validator per contract kind."""
    validators: dict[str, Draft202012Validator] = {}
    for kind in CONTRACT_KINDS:
        schema_path = contracts_dir / kind / "v1" / "schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema, format_checker=FormatChecker())
    return validators


def check_schema(
    doc: Doc, validators: dict[str, Draft202012Validator]
) -> list[Finding]:
    """Validate a document against its contract schema."""
    errors = sorted(
        validators[doc.kind].iter_errors(doc.data), key=lambda e: list(e.path)
    )
    return [
        Finding(
            code="SCHEMA",
            path=str(doc.path),
            message=(
                f"[{doc.kind}] {'/'.join(str(p) for p in error.path) or '<root>'}: "
                f"{error.message}"
            ),
        )
        for error in errors
    ]
