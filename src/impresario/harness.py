"""Prompt harness for the Stage 4 prioritizer: render + ingest.

impresario never calls an LLM. render deterministically builds
EvaluationBrief documents (content-addressed, immutable evidence);
an external executor runs the brief's prompt and returns an
assessment-answer/v1 judgment; ingest validates pairs and materializes
immutable AxisAssessments, authoring every bookkeeping field itself
(spec: docs/superpowers/specs/2026-08-16-prioritizer-prompt-harness-design.md).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PROMPT_VERSION = "prioritizer/v1"
POLICY_VERSION = "scoring/v1"


class HarnessError(Exception):
    """A typed harness failure (usage, tampering, conflict)."""


def sha256_bytes(data: bytes) -> str:
    """`sha256:<hex>` digest in the contracts' hash format."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def find_prompts_dir(start: Path) -> Path:
    """Walk upward from *start* to find the prompts/ directory."""
    for candidate in (start, *start.resolve().parents):
        prompts = candidate / "prompts"
        if (prompts / "prioritizer" / "v1" / "prompt.md").is_file():
            return prompts
    raise FileNotFoundError(
        f"prompts/ directory with prioritizer/v1 not found above {start}"
    )
