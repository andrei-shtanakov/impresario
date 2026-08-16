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
from typing import Any

from . import workspace as ws
from .hashing import canonical_doc_hash
from .loader import Doc, load_doc
from .schemas import check_schema, load_validators

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


_IDENTITY_FIELDS = (
    "idea_ref",
    "input_hash",
    "prompt_version",
    "prompt_pack_hash",
    "policy_version",
    "strategy_hash",
    "standards_hash",
    "prompt_hash",
)


def briefs_dir(workspace: Path) -> Path:
    """Immutable evidence directory of rendered briefs."""
    return workspace / "briefs"


def brief_identity(fields: dict[str, str]) -> str:
    """Derived brief id: canonical hash of exactly the identity fields.

    prompt_hash is part of the tuple on purpose: without it a tampered
    prompt with untouched sibling fields would pass the recompute
    (spec review, 2026-08-16).
    """
    identity = {name: fields[name] for name in _IDENTITY_FIELDS}
    return "BRF-" + canonical_doc_hash(identity).removeprefix("sha256:")[:12]


def build_brief(
    idea_doc: dict[str, Any],
    *,
    idea_text: str,
    prompt_template: str,
    prompt_pack_hash: str,
    strategy_text: str,
    standards_text: str,
) -> dict[str, Any]:
    """A complete, schema-valid EvaluationBrief document (no I/O)."""
    prompt = (
        prompt_template.replace("{idea}", idea_text)
        .replace("{strategy}", strategy_text)
        .replace("{standards}", standards_text)
    )
    fields = {
        "idea_ref": f"idea://{idea_doc['id']}",
        "input_hash": canonical_doc_hash(idea_doc),
        "prompt_version": PROMPT_VERSION,
        "prompt_pack_hash": prompt_pack_hash,
        "policy_version": POLICY_VERSION,
        "strategy_hash": sha256_bytes(strategy_text.encode("utf-8")),
        "standards_hash": sha256_bytes(standards_text.encode("utf-8")),
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    return {"brief_id": brief_identity(fields), **fields, "prompt": prompt}


def render_briefs(
    workspace: Path,
    contracts_dir: Path,
    prompts_dir: Path,
    *,
    idea_id: str | None = None,
) -> dict[str, Any]:
    """Deterministically render briefs for the workspace's idea cards.

    Re-running on unchanged inputs is a byte-level no-op; a changed
    input yields a NEW brief while the old one stays (immutable
    evidence). An existing file whose bytes diverge from the fresh
    render under the same id is tampering — a typed error, no write.
    """
    pack_path = prompts_dir / "prioritizer" / "v1" / "prompt.md"
    prompt_template = pack_path.read_text(encoding="utf-8")
    prompt_pack_hash = sha256_bytes(pack_path.read_bytes())
    strategy_text = (workspace / "strategy.md").read_text(encoding="utf-8")
    standards_text = (workspace / "standards.md").read_text(encoding="utf-8")
    validators = load_validators(contracts_dir)

    idea_paths = sorted((workspace / "ideas").glob("*.yaml"))
    briefs: list[dict[str, str]] = []
    for idea_path in idea_paths:
        idea = load_doc(idea_path)
        if idea.kind != "idea":
            continue
        if idea_id is not None and idea.data.get("id") != idea_id:
            continue
        brief = build_brief(
            idea.data,
            idea_text=ws.dump_yaml(idea.data),
            prompt_template=prompt_template,
            prompt_pack_hash=prompt_pack_hash,
            strategy_text=strategy_text,
            standards_text=standards_text,
        )
        findings = check_schema(
            Doc(path=briefs_dir(workspace), kind="evaluation-brief", data=brief),
            validators,
        )
        if findings:
            raise HarnessError(
                "refusing to write invalid brief: "
                + "; ".join(f.message for f in findings)
            )
        path = briefs_dir(workspace) / f"{brief['brief_id'].lower()}.yaml"
        content = ws.dump_yaml(brief)
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise HarnessError(
                    f"{path}: existing brief bytes diverge from a fresh "
                    "render under the same brief_id (tampering?)"
                )
        else:
            ws.write_atomic(path, content)
        briefs.append(
            {
                "brief_id": brief["brief_id"],
                "idea_ref": brief["idea_ref"],
                "path": str(path),
            }
        )
    return {"ok": True, "briefs": briefs}
