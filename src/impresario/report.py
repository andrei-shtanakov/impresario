"""Machine-readable validation report with stable exit codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class Finding:
    """A single validation violation with a stable code."""

    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Serialize the finding for the JSON report."""
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass
class Report:
    """Aggregate result of a validation run."""

    checked: int = 0
    errors: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no violations were found."""
        return not self.errors

    @property
    def exit_code(self) -> int:
        """Stable exit code: 0 clean, 1 violations."""
        return EXIT_OK if self.ok else EXIT_VIOLATIONS

    def as_dict(self) -> dict[str, Any]:
        """Serialize the report for JSON output."""
        return {
            "ok": self.ok,
            "checked": self.checked,
            "errors": [finding.as_dict() for finding in self.errors],
        }
