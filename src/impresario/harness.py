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
    strategy_hash: str,
    standards_hash: str,
) -> dict[str, Any]:
    """A complete, schema-valid EvaluationBrief document (no I/O).

    strategy_hash/standards_hash are computed by the caller from raw file
    bytes (not from strategy_text/standards_text.encode()) so the digest
    matches an external `sha256sum` regardless of newline translation
    performed while decoding the text used for prompt substitution.
    """
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
        "strategy_hash": strategy_hash,
        "standards_hash": standards_hash,
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
    strategy_raw = (workspace / "strategy.md").read_bytes()
    standards_raw = (workspace / "standards.md").read_bytes()
    strategy_text = strategy_raw.decode("utf-8")
    standards_text = standards_raw.decode("utf-8")
    strategy_hash = sha256_bytes(strategy_raw)
    standards_hash = sha256_bytes(standards_raw)
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
            strategy_hash=strategy_hash,
            standards_hash=standards_hash,
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
    if idea_id is not None and not briefs:
        raise HarnessError(f"--idea {idea_id}: no such card in workspace")
    return {"ok": True, "briefs": briefs}


def _write_assessment(path: Path, content: str) -> None:
    """Seam for crash-simulation tests; delegates to atomic write."""
    ws.write_atomic(path, content)


def _candidate_assessment(
    brief: dict[str, Any],
    answer: dict[str, Any],
    *,
    run_id: str,
    actor: str,
    model: str,
) -> dict[str, Any]:
    """AxisAssessment without assessment_id/evaluated_at (identity-free)."""
    candidate: dict[str, Any] = {
        "idea_ref": brief["idea_ref"],
        "run_id": run_id,
        "input_hash": brief["input_hash"],
        "policy_version": brief["policy_version"],
        "evidence_refs": answer["evidence_refs"],
        "fit_strategy": answer["fit_strategy"],
        "fit_market": answer["fit_market"],
        "fit_standards": answer["fit_standards"],
        "strategy_blocker": answer["strategy_blocker"],
        "standards_blocker": answer["standards_blocker"],
        "rationale": answer["rationale"],
        "confidence": answer["confidence"],
        "evaluator": {
            "kind": "agent",
            "id": actor,
            "model": model,
            "prompt_version": brief["prompt_version"],
        },
        "provenance": {
            "brief_id": brief["brief_id"],
            "prompt_pack_hash": brief["prompt_pack_hash"],
            "strategy_hash": brief["strategy_hash"],
            "standards_hash": brief["standards_hash"],
        },
    }
    for key in ("strategy_blocker_ref", "standards_blocker_ref"):
        if key in answer:
            candidate[key] = answer[key]
    return candidate


def _strip_identity(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in ("assessment_id", "evaluated_at")}


def ingest_pairs(
    workspace: Path,
    contracts_dir: Path,
    *,
    run_id: str,
    actor: str,
    model: str,
    pairs: list[tuple[Path, Path]],
    now_iso: str,
) -> dict[str, Any]:
    """Two-phase ingest under the single-writer lock (spec §assess ingest).

    Phase 1 validates EVERY pair (brief schema + identity recompute,
    STALE_INPUT against the current card, answer schema, in-call
    duplicates, (run_id, brief_id) idempotency/conflicts) and writes
    nothing on any failure. Phase 2 materializes the whole set;
    a crash mid-phase is recovered by re-running the same call —
    already-written pairs become no-ops.
    """
    try:
        with ws.single_writer_lock(workspace):
            return _ingest_locked(
                workspace,
                contracts_dir,
                run_id=run_id,
                actor=actor,
                model=model,
                pairs=pairs,
                now_iso=now_iso,
            )
    except ws.WorkspaceError as exc:
        raise HarnessError(str(exc)) from exc


def _ingest_locked(
    workspace: Path,
    contracts_dir: Path,
    *,
    run_id: str,
    actor: str,
    model: str,
    pairs: list[tuple[Path, Path]],
    now_iso: str,
) -> dict[str, Any]:
    validators = load_validators(contracts_dir)
    existing_docs = (
        [load_doc(p) for p in sorted(ws.assessments_dir(workspace).glob("*.yaml"))]
        if ws.assessments_dir(workspace).is_dir()
        else []
    )
    existing_by_key: dict[tuple[Any, Any], Doc] = {}
    for d in existing_docs:
        if d.kind != "axis-assessment":
            continue
        key = (d.data.get("run_id"), (d.data.get("provenance") or {}).get("brief_id"))
        collision = existing_by_key.get(key)
        if collision is not None:
            raise HarnessError(
                f"duplicate assessment for (run_id, brief_id)={key}: "
                f"{collision.data.get('assessment_id')} and "
                f"{d.data.get('assessment_id')} both present in workspace "
                "(hand-edited?)"
            )
        existing_by_key[key] = d

    seen_brief_ids: set[str] = set()
    to_write: list[dict[str, Any]] = []
    noops: list[dict[str, str]] = []

    # -------- фаза 1: только чтение и проверки --------
    for brief_path, answer_path in pairs:
        brief_doc = load_doc(brief_path)
        if brief_doc.kind != "evaluation-brief":
            raise HarnessError(f"{brief_path}: not an evaluation-brief")
        findings = check_schema(brief_doc, validators)
        if findings:
            raise HarnessError(
                f"{brief_path}: invalid brief: "
                + "; ".join(f.message for f in findings)
            )
        brief = brief_doc.data
        if sha256_bytes(brief["prompt"].encode("utf-8")) != brief["prompt_hash"]:
            raise HarnessError(
                f"{brief_path}: BRIEF_IDENTITY: prompt bytes do not match prompt_hash"
            )
        if brief_identity(brief) != brief["brief_id"]:
            raise HarnessError(
                f"{brief_path}: BRIEF_IDENTITY: brief_id does not match the recompute"
            )
        if brief["brief_id"] in seen_brief_ids:
            raise HarnessError(f"duplicate brief {brief['brief_id']} in one invocation")
        seen_brief_ids.add(brief["brief_id"])

        idea_id = brief["idea_ref"].removeprefix("idea://")
        # Карточку ищем по её собственному id, не по имени файла:
        # имена файлов в workspace не законтрактованы.
        idea_docs = [
            d
            for d in (
                load_doc(p) for p in sorted(ws.ideas_dir(workspace).glob("*.yaml"))
            )
            if d.kind == "idea" and d.data.get("id") == idea_id
        ]
        if len(idea_docs) != 1:
            raise HarnessError(
                f"STALE_INPUT: {brief['idea_ref']} resolves to "
                f"{len(idea_docs)} card(s) in workspace (expected exactly 1)"
            )
        current_hash = canonical_doc_hash(idea_docs[0].data)
        if current_hash != brief["input_hash"]:
            raise HarnessError(
                f"STALE_INPUT: {brief['idea_ref']} changed since the brief "
                f"was rendered ({current_hash} != {brief['input_hash']})"
            )

        answer_doc = load_doc(answer_path)
        if answer_doc.kind != "assessment-answer":
            raise HarnessError(f"{answer_path}: not an assessment-answer")
        findings = check_schema(answer_doc, validators)
        if findings:
            raise HarnessError(
                f"{answer_path}: invalid answer: "
                + "; ".join(f.message for f in findings)
            )

        candidate = _candidate_assessment(
            brief, answer_doc.data, run_id=run_id, actor=actor, model=model
        )
        existing = existing_by_key.get((run_id, brief["brief_id"]))
        if existing is not None:
            if _strip_identity(existing.data) == candidate:
                noops.append(
                    {
                        "brief_id": brief["brief_id"],
                        "assessment_id": existing.data["assessment_id"],
                        "path": str(existing.path),
                    }
                )
                continue
            raise HarnessError(
                f"ASSESS_CONFLICT: ({run_id}, {brief['brief_id']}) already "
                f"materialized as {existing.data['assessment_id']} with a "
                "different answer/actor/model"
            )
        to_write.append(candidate)

    # -------- фаза 2: материализация набора --------
    existing_ids = {
        d.data["assessment_id"] for d in existing_docs if d.kind == "axis-assessment"
    }
    validator = validators["axis-assessment"]
    written: list[dict[str, str]] = []
    for candidate in to_write:
        assessment_id = ws.next_id("ASMT", existing_ids=existing_ids)
        existing_ids.add(assessment_id)
        full = {
            "assessment_id": assessment_id,
            **candidate,
            "evaluated_at": now_iso,
        }
        # Ремонт после частичной записи — идемпотентным повтором всего
        # вызова, не multi-file транзакцией (спека, §ingest): если эта
        # ревалидация здесь провалится ПОСЛЕ того, как предыдущие
        # кандидаты в to_write уже записаны на диск, они остаются
        # записанными — откат сознательно не делается.
        errors = sorted(validator.iter_errors(full), key=lambda e: list(e.path))
        if errors:
            raise HarnessError(
                "refusing to write invalid assessment: "
                + "; ".join(e.message for e in errors)
            )
        path = ws.assessments_dir(workspace) / f"{assessment_id.lower()}.yaml"
        _write_assessment(path, ws.dump_yaml(full))
        written.append(
            {
                "brief_id": candidate["provenance"]["brief_id"],
                "assessment_id": assessment_id,
                "path": str(path),
            }
        )
    return {"ok": True, "written": written, "noop": noops}
