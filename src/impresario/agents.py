"""Agent interface for the forconcept reference loop.

The runner owns the semantics (stages, validation, FSM); agents only
author artifact content. The reference implementation is a scripted agent
reading pre-authored, contract-valid artifacts — it makes the loop fully
deterministic and doubles as the golden-trace fixture format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .loader import parse_yaml_plain


class AgentError(Exception):
    """An agent could not produce the requested artifact."""


class Agent(Protocol):
    """Produces one artifact document per (role, iteration) call."""

    def produce(self, role: str, iteration: int) -> dict[str, Any]:
        """Return the full artifact document for the given call."""
        ...


class ScriptedAgent:
    """Replays complete artifact documents from a script mapping.

    Script shape: {"researcher": {0: {...ResearchPack...}, ...},
    "creator": {0: {...ConceptDraft...}, ...}} — iteration keys may be
    ints or digit strings. Replaying the same key returns the same
    document, which is what makes agent calls idempotent under resume.
    """

    def __init__(self, script: dict[str, Any]) -> None:
        self._script = script

    @classmethod
    def from_file(cls, path: Path) -> ScriptedAgent:
        """Load a script from a YAML file (dates stay strings, as in docs)."""
        data = parse_yaml_plain(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise AgentError(f"{path}: script is not a mapping")
        return cls(data)

    def produce(self, role: str, iteration: int) -> dict[str, Any]:
        """Return the scripted artifact for (role, iteration)."""
        by_role = self._script.get(role, {})
        entry = by_role.get(iteration, by_role.get(str(iteration)))
        if entry is None:
            raise AgentError(
                f"script has no entry for role={role} iteration={iteration}"
            )
        if not isinstance(entry, dict):
            raise AgentError(f"script entry {role}/{iteration} is not a document")
        return entry


class SingleAnswerAgent:
    """Serves exactly one pre-built artifact for one (role, iteration).

    The step harness feeds the runner through this agent so the runner
    stays the sole executor of loop semantics; any unexpected call is a
    typed error (unreachable under the harness's stop_after boundaries).
    """

    def __init__(self, role: str, iteration: int, doc: dict[str, Any]) -> None:
        self._role = role
        self._iteration = iteration
        self._doc = doc

    def produce(self, role: str, iteration: int) -> dict[str, Any]:
        """Return the single answer document or fail typed."""
        if role != self._role or iteration != self._iteration:
            raise AgentError(
                f"single-answer agent holds {self._role}:{self._iteration}, "
                f"got unexpected call {role}:{iteration}"
            )
        return self._doc
