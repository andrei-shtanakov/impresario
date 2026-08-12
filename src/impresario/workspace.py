"""Workspace layout, single-writer lock and atomic writes for Stage 4.

Layout of a workspace directory:
    ideas/         Idea cards (idea/v1)
    assessments/   AxisAssessment docs (axis-assessment/v1)
    backlog.yaml   current RankedBacklog version (ranked-backlog/v1)
    runs/          immutable materialization records (run-record/v1)
    decisions/     immutable gate decisions (gate-decision/v1)
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml


class WorkspaceError(Exception):
    """A workspace-level failure (lock busy, missing layout, write race)."""


def ideas_dir(workspace: Path) -> Path:
    """Path of the idea cards directory."""
    return workspace / "ideas"


def assessments_dir(workspace: Path) -> Path:
    """Path of the assessments directory."""
    return workspace / "assessments"


def backlog_path(workspace: Path) -> Path:
    """Path of the current backlog document."""
    return workspace / "backlog.yaml"


def runs_dir(workspace: Path) -> Path:
    """Path of the immutable run records directory."""
    return workspace / "runs"


def decisions_dir(workspace: Path) -> Path:
    """Path of the immutable gate decisions directory."""
    return workspace / "decisions"


def dump_yaml(data: dict[str, Any]) -> str:
    """Serialize a document as YAML preserving insertion order."""
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=88)


def write_atomic(path: Path, content: str) -> None:
    """Validate-then-atomic-replace: write a sibling temp file, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def single_writer_lock(workspace: Path):
    """O_EXCL lock file: concurrent apply/select on one workspace fails fast."""
    lock = workspace / ".lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise WorkspaceError(f"workspace is locked by another writer: {lock}") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


_ID_RE = re.compile(r"([A-Z]+)-([0-9]{3,})")


def next_id(prefix: str, *, existing_ids: set[str]) -> str:
    """Smallest unused `PREFIX-NNN` above every id already in use."""
    highest = 0
    for raw in existing_ids:
        match = _ID_RE.fullmatch(raw)
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)))
    return f"{prefix}-{highest + 1:03d}"


_STATUS_LINE_RE = re.compile(
    r"^status:[ \t]*(?:\"[^\"]*\"|'[^']*'|[^#\n]*?)[ \t]*(?P<comment>#[^\n]*)?$",
    flags=re.MULTILINE,
)


def prepare_idea_status(idea_path: Path, new_status: str) -> str:
    """Return the card text with only the `status:` line rewritten.

    A YAML round-trip would drop comments and reorder keys (the ruamel
    block-rewrite lesson); the funnel status is a single scalar line, so a
    targeted line edit is the safe write. Quoted values and inline comments
    are supported; the comment is preserved. Raising here (before any write)
    lets callers pre-flight the edit and keep multi-file updates all-or-
    nothing up to I/O failures.
    """
    text = idea_path.read_text(encoding="utf-8")

    def _replace(match: re.Match[str]) -> str:
        comment = match.group("comment")
        suffix = f"  {comment}" if comment else ""
        return f"status: {new_status}{suffix}"

    updated, count = _STATUS_LINE_RE.subn(_replace, text, count=1)
    if count != 1:
        raise WorkspaceError(f"{idea_path}: top-level 'status:' line not found")
    return updated


def set_idea_status(idea_path: Path, new_status: str) -> None:
    """Rewrite only the top-level `status:` line, preserving all other bytes."""
    write_atomic(idea_path, prepare_idea_status(idea_path, new_status))
