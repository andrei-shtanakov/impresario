"""Stage harness for the forconcept loop: brief rendering + step ingest.

The runner (impresario.loop) stays the sole executor of loop semantics;
this module derives the next expected agent call from the workspace
artifacts (the same evidence the runner reads), renders a content-
addressed StageBrief, and — in step — assembles a full artifact from an
executor's answer and feeds it back through run_loop via
SingleAnswerAgent (spec:
docs/superpowers/specs/2026-08-16-loop-agent-harness-design.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import workspace as ws
from .harness import HarnessError, sha256_bytes
from .hashing import canonical_doc_hash
from .loader import Doc, load_doc

# Внутрипакетные приватные хелперы раннера: деривация обязана читать
# ровно те же артефакты тем же способом, что и run_loop.
from .loop import _docs_of_kind, _find_iteration, state_path
from .schemas import check_schema, load_validators

ROLE_ORDER = {"researcher": 0, "creator": 1}
ROLE_PROMPT_VERSIONS = {"researcher": "researcher/v1", "creator": "creator/v1"}

_STAGE_IDENTITY_FIELDS = (
    "loop_id",
    "iteration",
    "role",
    "prompt_version",
    "prompt_pack_hash",
    "idea_input_hash",
    "proposal_hash",
    "history_hash",
    "prompt_hash",
)


def loop_briefs_dir(workspace: Path) -> Path:
    """Immutable evidence directory of rendered stage briefs."""
    return workspace / "briefs"


def _read_state(workspace: Path, contracts_dir: Path) -> dict[str, Any]:
    state = json.loads(state_path(workspace).read_text(encoding="utf-8"))
    validator = load_validators(contracts_dir)["loop-state"]
    errors = sorted(validator.iter_errors(state), key=lambda e: list(e.path))
    if errors:
        raise HarnessError(
            f"{state_path(workspace)}: invalid loop-state: "
            + "; ".join(e.message for e in errors)
        )
    return state


def derive_next_call(workspace: Path, contracts_dir: Path) -> tuple[str, int]:
    """(role, iteration) следующего ожидаемого вызова агента.

    Той же логикой, что раннер: RP итерации нет — researcher; CD нет —
    creator; оба есть, но evaluate-переход не завершён — EVALUATOR_PENDING
    (продвижение — forconcept run/step, не brief). Терминальный stop —
    TERMINAL; needs_human — NEEDS_HUMAN (путь resume).
    """
    state = _read_state(workspace, contracts_dir)
    stop = state.get("stop")
    if stop is not None:
        if stop.get("verdict") == "needs_human":
            raise HarnessError(
                "NEEDS_HUMAN: loop is holding for a human; use "
                "`forconcept resume` before the next brief"
            )
        raise HarnessError(f"TERMINAL: loop already stopped with {stop.get('verdict')}")
    proposal = load_doc(workspace / "proposal.yaml")
    delta_log = (proposal.data.get("content") or {}).get("delta_log") or []
    applied = {entry.get("iteration") for entry in delta_log}
    for iteration in range(int(state["max_iterations"])):
        rps = _docs_of_kind(workspace, "research-pack")
        if _find_iteration(rps, iteration) is None:
            return ("researcher", iteration)
        cds = _docs_of_kind(workspace, "concept-draft")
        if _find_iteration(cds, iteration) is None:
            return ("creator", iteration)
        if iteration not in applied:
            raise HarnessError(
                f"EVALUATOR_PENDING: iteration {iteration} has both "
                "artifacts but the delta is not applied; advance with "
                "`forconcept run` (or step) — no agent call is pending"
            )
    raise HarnessError(
        "EVALUATOR_PENDING: all iterations have artifacts but the loop "
        "has no verdict; advance with `forconcept run`"
    )


# Примечание к деривации: случай «оба артефакта есть, delta применена, но
# вердикт итерации не вынесен» в файловом раннере не существует отдельно
# от «вынесен continue» (evaluate и запись вердикта — один прогон
# run_loop), поэтому ветка после applied-проверки продолжает цикл —
# continue-итерация означает следующий researcher.


def history_entries(workspace: Path) -> list[dict[str, Any]]:
    """RP/CD история в детерминированном порядке (iteration, role, id)."""
    entries: list[tuple[tuple[int, int, str], Doc]] = []
    for kind, role in (("research-pack", "researcher"), ("concept-draft", "creator")):
        for doc in _docs_of_kind(workspace, kind):
            entries.append(
                (
                    (
                        int(doc.data.get("iteration", 0)),
                        ROLE_ORDER[role],
                        str(doc.data.get("id", "")),
                    ),
                    doc,
                )
            )
    entries.sort(key=lambda pair: pair[0])
    return [
        {
            "iteration": key[0],
            "role": "researcher" if key[1] == 0 else "creator",
            "id": key[2],
            "hash": canonical_doc_hash(doc.data),
            "doc": doc.data,
        }
        for key, doc in entries
    ]


def history_hash(entries: list[dict[str, Any]]) -> str:
    """Канонический хеш упорядоченной истории (без самих документов)."""
    return canonical_doc_hash(
        {
            "history": [
                {k: e[k] for k in ("iteration", "role", "id", "hash")} for e in entries
            ]
        }
    )


def stage_brief_identity(fields: dict[str, Any]) -> str:
    """SBR-<12hex> от ровно девяти identity-полей (включая prompt_hash)."""
    identity = {name: fields[name] for name in _STAGE_IDENTITY_FIELDS}
    return "SBR-" + canonical_doc_hash(identity).removeprefix("sha256:")[:12]


def render_stage_brief(
    workspace: Path, contracts_dir: Path, prompts_dir: Path
) -> dict[str, Any]:
    """Детерминированный рендер brief'а следующей ожидаемой стадии."""
    role, iteration = derive_next_call(workspace, contracts_dir)
    state = _read_state(workspace, contracts_dir)
    pack_path = prompts_dir / role / "v1" / "prompt.md"
    pack_raw = pack_path.read_bytes()
    template = pack_raw.decode("utf-8")

    idea = load_doc(workspace / "idea.yaml")
    proposal = load_doc(workspace / "proposal.yaml")
    entries = history_entries(workspace)
    history_text = (
        "\n\n".join(
            f"### {e['role']} — итерация {e['iteration']} — {e['id']}\n\n"
            + ws.dump_yaml(e["doc"])
            for e in entries
        )
        or "(история пуста — первая стадия цикла)"
    )
    substitutions = {
        "idea": ws.dump_yaml(idea.data),
        "proposal": ws.dump_yaml(proposal.data),
        "history": history_text,
    }
    prompt = re.sub(
        r"\{(idea|proposal|history)\}",
        lambda m: substitutions[m.group(1)],
        template,
    )
    fields: dict[str, Any] = {
        "loop_id": state["loop_id"],
        "iteration": iteration,
        "role": role,
        "prompt_version": ROLE_PROMPT_VERSIONS[role],
        "prompt_pack_hash": sha256_bytes(pack_raw),
        "idea_input_hash": canonical_doc_hash(idea.data),
        "proposal_hash": canonical_doc_hash(proposal.data),
        "history_hash": history_hash(entries),
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    brief = {
        "schema_version": "stage-brief/v1",
        "brief_id": stage_brief_identity(fields),
        **fields,
        "prompt": prompt,
    }
    validators = load_validators(contracts_dir)
    path = loop_briefs_dir(workspace) / f"{brief['brief_id'].lower()}.yaml"
    findings = check_schema(
        Doc(path=path, kind="stage-brief", data=brief),
        validators,
    )
    if findings:
        raise HarnessError(
            "refusing to write invalid stage brief: "
            + "; ".join(f.message for f in findings)
        )
    content = ws.dump_yaml(brief)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise HarnessError(
                f"{path}: existing brief bytes diverge from a fresh render "
                "under the same brief_id (tampering?)"
            )
    else:
        ws.write_atomic(path, content)
    return {
        "brief_id": brief["brief_id"],
        "role": role,
        "iteration": iteration,
        "path": str(path),
    }


def _assemble_artifact(
    brief: dict[str, Any],
    answer: dict[str, Any],
    workspace: Path,
    contracts_dir: Path,
    *,
    actor: str,
    model: str,
    now_iso: str,
) -> dict[str, Any]:
    """Полный RP/CD: контент из answer + bookkeeping из brief/loop.state."""
    state = _read_state(workspace, contracts_dir)
    role = brief["role"]
    if role == "researcher":
        kind, prefix = "research-pack", "RP"
    else:
        kind, prefix = "concept-draft", "CD"
    existing = {d.data["id"] for d in _docs_of_kind(workspace, kind)}
    artifact_id = ws.next_id(prefix, existing_ids=existing)
    content = {k: v for k, v in answer.items() if k != "schema_version"}
    doc: dict[str, Any] = {
        "id": artifact_id,
        "idea_ref": state["idea_ref"],
        "proposal_ref": f"proposal://{state['proposal_id']}",
        "iteration": brief["iteration"],
        **content,
        "produced_by": {
            "kind": "agent",
            "id": actor,
            "model": model,
            "prompt_version": brief["prompt_version"],
        },
        "produced_at": now_iso,
        "provenance": {
            "brief_id": brief["brief_id"],
            "prompt_pack_hash": brief["prompt_pack_hash"],
        },
    }
    if role == "creator":
        rps = _docs_of_kind(workspace, "research-pack")
        rp = _find_iteration(rps, brief["iteration"])
        if rp is None:
            raise HarnessError(
                "STALE_BRIEF: no research pack for the brief's iteration"
            )
        doc["based_on_research"] = {
            "ref": f"research-pack://{rp.data['id']}",
            "iteration": brief["iteration"],
        }
    return doc


def step_loop(
    workspace: Path,
    contracts_dir: Path,
    prompts_dir: Path,
    *,
    brief_path: Path,
    answer_path: Path,
    actor: str,
    model: str,
    now_iso: str,
) -> dict[str, Any]:
    """Нормативный протокол шага (спека): brief → идемпотентность →
    freshness → answer → пре-валидация сборки → раннер.

    `prompts_dir` is accepted for interface symmetry with the brief
    render (`forconcept step` takes the same flags as `forconcept
    brief`); step itself never re-renders a prompt pack.
    """
    from .agents import SingleAnswerAgent
    from .loop import run_loop

    validators = load_validators(contracts_dir)

    # 1. Brief: схема + двухслойный пересчёт identity.
    brief_doc = load_doc(brief_path)
    if brief_doc.kind != "stage-brief":
        raise HarnessError(f"{brief_path}: not a stage-brief")
    findings = check_schema(brief_doc, validators)
    if findings:
        raise HarnessError(
            f"{brief_path}: invalid brief: " + "; ".join(f.message for f in findings)
        )
    brief = brief_doc.data
    if sha256_bytes(brief["prompt"].encode("utf-8")) != brief["prompt_hash"]:
        raise HarnessError(
            f"{brief_path}: BRIEF_IDENTITY: prompt bytes do not match prompt_hash"
        )
    if stage_brief_identity(brief) != brief["brief_id"]:
        raise HarnessError(
            f"{brief_path}: BRIEF_IDENTITY: brief_id does not match the recompute"
        )

    role = brief["role"]
    kind = "research-pack" if role == "researcher" else "concept-draft"

    # 2. Идемпотентность — ДО freshness (спека: потреблённый brief после
    # продвижения workspace иначе был бы отвергнут как stale).
    answer_doc = load_doc(answer_path)
    expected_answer_kind = (
        "research-answer" if role == "researcher" else "concept-answer"
    )
    consumed = next(
        (
            d
            for d in _docs_of_kind(workspace, kind)
            if (d.data.get("provenance") or {}).get("brief_id") == brief["brief_id"]
        ),
        None,
    )
    if consumed is not None:
        if answer_doc.kind != expected_answer_kind:
            raise HarnessError(f"{answer_path}: not a {expected_answer_kind}")
        candidate = _assemble_artifact(
            brief,
            answer_doc.data,
            workspace,
            contracts_dir,
            actor=actor,
            model=model,
            now_iso=now_iso,
        )
        existing_cmp = {
            k: v for k, v in consumed.data.items() if k not in ("id", "produced_at")
        }
        candidate_cmp = {
            k: v for k, v in candidate.items() if k not in ("id", "produced_at")
        }
        if existing_cmp == candidate_cmp:
            return {
                "ok": True,
                "noop": True,
                "artifact": {
                    "id": consumed.data["id"],
                    "path": str(consumed.path),
                },
                "runner": None,
            }
        raise HarnessError(
            f"STEP_CONFLICT: brief {brief['brief_id']} already consumed as "
            f"{consumed.data['id']} with a different answer/actor/model"
        )

    # 3. Freshness + структурная проверка пары.
    expected_role, expected_iteration = derive_next_call(workspace, contracts_dir)
    state = _read_state(workspace, contracts_dir)
    idea = load_doc(workspace / "idea.yaml")
    proposal = load_doc(workspace / "proposal.yaml")
    fresh = {
        "loop_id": state["loop_id"],
        "iteration": expected_iteration,
        "role": expected_role,
        "idea_input_hash": canonical_doc_hash(idea.data),
        "proposal_hash": canonical_doc_hash(proposal.data),
        "history_hash": history_hash(history_entries(workspace)),
    }
    for field, value in fresh.items():
        if brief.get(field) != value:
            raise HarnessError(
                f"STALE_BRIEF: {field} of the brief does not match the "
                f"workspace's current expected stage ({brief.get(field)!r} "
                f"!= {value!r})"
            )

    # 4. Answer: схема роли.
    if answer_doc.kind != expected_answer_kind:
        raise HarnessError(f"{answer_path}: not a {expected_answer_kind}")
    findings = check_schema(answer_doc, validators)
    if findings:
        raise HarnessError(
            f"{answer_path}: invalid answer: " + "; ".join(f.message for f in findings)
        )

    # 5. Пре-валидация полностью собранного артефакта: путь раннера для
    # невалидного артефакта персистит терминальный failed — слишком
    # разрушительно для ошибки ingest; раннер остаётся defense-in-depth.
    artifact = _assemble_artifact(
        brief,
        answer_doc.data,
        workspace,
        contracts_dir,
        actor=actor,
        model=model,
        now_iso=now_iso,
    )
    findings = check_schema(
        Doc(
            path=workspace / f"{artifact['id'].lower()}.yaml",
            kind=kind,
            data=artifact,
        ),
        validators,
    )
    if findings:
        raise HarnessError(
            "refusing to run: assembled artifact is invalid: "
            + "; ".join(f.message for f in findings)
        )

    # 6. Раннер — единственный исполнитель.
    stop_after = (
        f"research:{expected_iteration}"
        if role == "researcher"
        else f"iteration:{expected_iteration}"
    )
    result = run_loop(
        workspace,
        contracts_dir,
        SingleAnswerAgent(role, expected_iteration, artifact),
        now_iso=now_iso,
        stop_after=stop_after,
    )
    return {
        "ok": True,
        "noop": False,
        "artifact": {
            "id": artifact["id"],
            "path": str(workspace / f"{artifact['id'].lower()}.yaml"),
        },
        "runner": {"verdict": result.verdict, "iteration": result.iteration},
    }
