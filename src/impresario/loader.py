"""Loading artifacts and detecting their contract kind."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONTRACT_KINDS: tuple[str, ...] = (
    "idea",
    "axis-assessment",
    "ranked-backlog",
    "research-pack",
    "concept-draft",
    "exchange-log",
    "product-proposal",
    "gate-decision",
    "loop-resume-decision",
    "run-record",
    "loop-state",
    "evaluation-brief",
    "assessment-answer",
)

_ID_PREFIX_TO_KIND: dict[str, str] = {
    "IDEA": "idea",
    "BL": "ranked-backlog",
    "RP": "research-pack",
    "CD": "concept-draft",
    "XL": "exchange-log",
}

_DOC_SUFFIXES = {".yaml", ".yml", ".json"}


class UnknownContractError(ValueError):
    """Raised when a document cannot be mapped to a known contract."""


@dataclass(frozen=True)
class Doc:
    """A loaded artifact with its detected contract kind."""

    path: Path
    kind: str
    data: dict[str, Any]


class _PlainDateLoader(yaml.SafeLoader):
    """SafeLoader that keeps dates and timestamps as plain strings.

    Derived from yaml.SafeLoader, so arbitrary Python object construction
    stays disabled; the only override is timestamp resolution. JSON Schema
    works on the JSON data model, where dates are strings; PyYAML's
    implicit timestamp resolution would break pattern checks.
    """


_PlainDateLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    lambda loader, node: loader.construct_scalar(node),
)


def detect_kind(data: dict[str, Any]) -> str:
    """Detect the contract kind of a document from its identifying fields."""
    if "brief_id" in data:
        return "evaluation-brief"
    if data.get("schema_version") == "assessment-answer/v1":
        return "assessment-answer"
    if "loop_id" in data:
        return "loop-state"
    if "assessment_id" in data:
        return "axis-assessment"
    if "proposal_id" in data:
        return "product-proposal"
    if "decision_id" in data:
        raw_decision_id = data["decision_id"]
        if isinstance(raw_decision_id, str) and raw_decision_id.startswith("LRD-"):
            return "loop-resume-decision"
        return "gate-decision"
    if "run_id" in data:  # after assessment_id: assessments carry run_id too
        return "run-record"
    raw_id = data.get("id")
    if isinstance(raw_id, str) and "-" in raw_id:
        kind = _ID_PREFIX_TO_KIND.get(raw_id.split("-", 1)[0])
        if kind is not None:
            return kind
    raise UnknownContractError(
        "cannot detect contract kind: no brief_id/schema_version/assessment_id/"
        "proposal_id/decision_id and no recognizable id prefix"
    )


def parse_yaml_plain(text: str) -> Any:
    """Parse YAML keeping dates/timestamps as strings (contract data model)."""
    return yaml.load(text, Loader=_PlainDateLoader)  # noqa: S506 - SafeLoader


def load_doc(path: Path) -> Doc:
    """Load a single YAML/JSON artifact and detect its kind."""
    text = path.read_text(encoding="utf-8")
    if path.name == "loop.state":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise UnknownContractError(f"{path}: document is not a mapping")
        return Doc(path=path, kind="loop-state", data=data)
    data = json.loads(text) if path.suffix == ".json" else parse_yaml_plain(text)
    if not isinstance(data, dict):
        raise UnknownContractError(f"{path}: document is not a mapping")
    return Doc(path=path, kind=detect_kind(data), data=data)


def collect_doc_paths(paths: list[Path]) -> list[Path]:
    """Expand files and directories into a sorted list of document paths."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file()
                and (child.suffix in _DOC_SUFFIXES or child.name == "loop.state")
            )
        else:
            found.append(path)
    return found
