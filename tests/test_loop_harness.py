"""Researcher/creator-харнесс цикла (spec 2026-08-16-loop-agent-harness)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from impresario.loader import load_doc

from .conftest import CONTRACTS_DIR, REPO_ROOT
from .test_loop import (
    HAPPY_SCRIPT,
    NOW,
    STUCK_SCRIPT,
    loop_ws,  # noqa: F401 - fixture reuse
)
from .test_loop import _run as run_scripted

PROMPTS_DIR = REPO_ROOT / "prompts"

RA_CONTENT_IT0 = {
    "schema_version": "research-answer/v1",
    "findings": [{"claim": "claim", "source_ref": "ref://x", "confidence": "high"}],
    "constraints": [],
    "gaps": [{"what": "critical gap", "blocks_approval": True}],
    "brief_for_creator": "brief",
    "requests_to_creator": [],
}

CA_CONTENT_IT0 = {
    "schema_version": "concept-answer/v1",
    "value_prop": "value",
    "alternatives": [
        {"direction": "a", "summary": "s"},
        {"direction": "b", "summary": "s"},
        {"direction": "c", "summary": "s"},
    ],
    "chosen_direction": {"direction": "a", "why": "w"},
    "business_models": ["m"],
    "assumptions": [{"text": "critical assumption", "blocks_approval": True}],
    "requests_to_researcher": ["check the gap"],
    "proposal_delta": "delta 0",
}

# Итерация 1: контент из tests/test_loop.py's _rp(2, 1, gap_open=False) /
# _cd(2, 1, 2, assumption_open=False), с bookkeeping (id, idea_ref,
# proposal_ref, iteration, based_on_research, produced_by, produced_at)
# отброшен — step авторит всё это сам.
RA_CONTENT_IT1 = {
    "schema_version": "research-answer/v1",
    "findings": [{"claim": "claim", "source_ref": "ref://x", "confidence": "high"}],
    "constraints": [],
    "gaps": [{"what": "critical gap", "blocks_approval": True, "closed": True}],
    "brief_for_creator": "brief",
    "requests_to_creator": [],
}

CA_CONTENT_IT1 = {
    "schema_version": "concept-answer/v1",
    "value_prop": "value",
    "alternatives": [
        {"direction": "a", "summary": "s"},
        {"direction": "b", "summary": "s"},
        {"direction": "c", "summary": "s"},
    ],
    "chosen_direction": {"direction": "a", "why": "w"},
    "business_models": ["m"],
    "assumptions": [
        {
            "text": "critical assumption",
            "blocks_approval": True,
            "answered_by": "research-pack://RP-002",
        }
    ],
    "requests_to_researcher": [],
    "proposal_delta": "delta 1",
}


def _write_yaml(path: Path, data: dict) -> Path:
    import yaml as _yaml

    path.write_text(
        _yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _step(ws_path: Path, brief: Path, answer: Path, **kw):
    from impresario.loop_harness import step_loop

    defaults = dict(actor="claude", model="claude-fable-5", now_iso=NOW)
    defaults.update(kw)
    return step_loop(
        ws_path,
        CONTRACTS_DIR,
        PROMPTS_DIR,
        brief_path=brief,
        answer_path=answer,
        **defaults,
    )


@pytest.mark.parametrize("role", ["researcher", "creator"])
def test_role_prompt_pack_placeholders(role: str) -> None:
    text = (PROMPTS_DIR / role / "v1" / "prompt.md").read_text(encoding="utf-8")
    for token in ("{idea}", "{proposal}", "{history}"):
        assert token in text
    assert (
        f"{role}-answer/v1".replace("researcher", "research").replace(
            "creator", "concept"
        )
        in text
    )


@pytest.mark.parametrize(
    ("role", "contract"),
    [("researcher", "research-answer"), ("creator", "concept-answer")],
)
def test_role_prompt_pins_answer_schema(role: str, contract: str) -> None:
    schema = json.loads(
        (CONTRACTS_DIR / contract / "v1" / "schema.json").read_text(encoding="utf-8")
    )
    text = (PROMPTS_DIR / role / "v1" / "prompt.md").read_text(encoding="utf-8")
    for field in schema["required"]:
        assert field in text, f"{role} prompt missing required field {field}"


def test_derive_next_call_walks_the_stages(loop_ws: Path) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.agents import ScriptedAgent
    from impresario.loop import run_loop
    from impresario.loop_harness import derive_next_call

    assert derive_next_call(loop_ws, CONTRACTS_DIR) == ("researcher", 0)

    run_loop(
        loop_ws,
        CONTRACTS_DIR,
        ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW,
        stop_after="research:0",
    )
    assert derive_next_call(loop_ws, CONTRACTS_DIR) == ("creator", 0)

    run_loop(
        loop_ws,
        CONTRACTS_DIR,
        ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW,
        stop_after="iteration:0",
    )
    assert derive_next_call(loop_ws, CONTRACTS_DIR) == ("researcher", 1)


def test_derive_next_call_terminal_and_hold(loop_ws: Path) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.harness import HarnessError
    from impresario.loop_harness import derive_next_call

    result = run_scripted(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    with pytest.raises(HarnessError, match="NEEDS_HUMAN"):
        derive_next_call(loop_ws, CONTRACTS_DIR)


def test_derive_next_call_evaluator_pending(loop_ws: Path) -> None:  # noqa: F811 - pytest fixture reuse
    """cd есть, evaluate не прошёл (пауза concept:0) — вызова агента нет."""
    from impresario.agents import ScriptedAgent
    from impresario.harness import HarnessError
    from impresario.loop import run_loop
    from impresario.loop_harness import derive_next_call

    run_loop(
        loop_ws,
        CONTRACTS_DIR,
        ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW,
        stop_after="concept:0",
    )
    with pytest.raises(HarnessError, match="EVALUATOR_PENDING"):
        derive_next_call(loop_ws, CONTRACTS_DIR)


def test_history_order_and_hash_deterministic(loop_ws: Path) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.loop_harness import history_entries, history_hash

    run_scripted(loop_ws, HAPPY_SCRIPT)
    entries = history_entries(loop_ws)
    keys = [(e["iteration"], e["role"], e["id"]) for e in entries]
    assert keys == sorted(
        keys, key=lambda k: (k[0], 0 if k[1] == "researcher" else 1, k[2])
    )
    assert history_hash(entries) == history_hash(history_entries(loop_ws))


def test_render_stage_brief_deterministic_and_valid(loop_ws: Path) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.loader import load_doc
    from impresario.loop_harness import render_stage_brief
    from impresario.schemas import check_schema, load_validators

    report1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report1["role"] == "researcher" and report1["iteration"] == 0
    path = Path(report1["path"])
    bytes1 = path.read_bytes()
    report2 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report2 == report1 and path.read_bytes() == bytes1

    doc = load_doc(path)
    assert doc.kind == "stage-brief"
    assert check_schema(doc, load_validators(CONTRACTS_DIR)) == []


def test_render_stage_brief_rejects_tampered_bytes(loop_ws: Path) -> None:  # noqa: F811 - pytest fixture reuse
    """Divergent bytes under the same brief_id refuse the render, file kept.

    Carried from the Task 4 review: no automated test covered render's
    tamper refusal (§render_stage_brief: "existing brief bytes diverge
    from a fresh render under the same brief_id").
    """
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    report = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    path = Path(report["path"])
    original = path.read_bytes()
    path.write_text(
        path.read_text(encoding="utf-8") + "\ntampered: true\n", encoding="utf-8"
    )
    tampered = path.read_bytes()
    assert tampered != original
    with pytest.raises(HarnessError, match="diverge"):
        render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert path.read_bytes() == tampered  # unchanged by the refused render


def test_step_researcher_then_creator_advances(loop_ws: Path, tmp_path: Path) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    out = _step(loop_ws, Path(r1["path"]), ans)
    assert out["runner"]["verdict"] == "paused"
    rp = load_doc(Path(out["artifact"]["path"]))
    assert rp.kind == "research-pack" and rp.data["iteration"] == 0
    assert rp.data["provenance"]["brief_id"] == r1["brief_id"]
    assert rp.data["produced_by"] == {
        "kind": "agent",
        "id": "claude",
        "model": "claude-fable-5",
        "prompt_version": "researcher/v1",
    }

    r2 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert r2["role"] == "creator" and r2["iteration"] == 0
    ans2 = _write_yaml(tmp_path / "ca.yaml", CA_CONTENT_IT0)
    out2 = _step(loop_ws, Path(r2["path"]), ans2)
    # continue-вердикт итерации 0: paused перед researcher 1
    assert out2["runner"]["verdict"] == "paused"
    cd = load_doc(Path(out2["artifact"]["path"]))
    assert cd.data["based_on_research"]["ref"].startswith("research-pack://RP-")


def test_step_idempotent_retry_before_freshness(loop_ws: Path, tmp_path: Path) -> None:  # noqa: F811 - pytest fixture reuse
    """Потреблённый brief повторно — no-op, хотя workspace продвинулся."""
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    first = _step(loop_ws, Path(r1["path"]), ans)
    artifact_path = Path(first["artifact"]["path"])
    bytes_before = artifact_path.read_bytes()

    retry = _step(loop_ws, Path(r1["path"]), ans, now_iso="2026-08-16T20:00:00Z")
    assert retry["noop"] is True
    assert artifact_path.read_bytes() == bytes_before  # id/produced_at живы

    divergent = dict(RA_CONTENT_IT0, brief_for_creator="другой")
    ans2 = _write_yaml(tmp_path / "ra2.yaml", divergent)
    with pytest.raises(HarnessError, match="STEP_CONFLICT"):
        _step(loop_ws, Path(r1["path"]), ans2)


def test_step_stale_brief_and_mispairing(loop_ws: Path, tmp_path: Path) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    # продвигаем workspace ДРУГИМ путём (scripted), brief r1 не потреблён
    from impresario.agents import ScriptedAgent
    from impresario.loop import run_loop

    run_loop(
        loop_ws,
        CONTRACTS_DIR,
        ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW,
        stop_after="research:0",
    )
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    with pytest.raises(HarnessError, match="STALE_BRIEF"):
        _step(loop_ws, Path(r1["path"]), ans)


def test_step_answer_schema_rejects_bad_content(loop_ws: Path, tmp_path: Path) -> None:  # noqa: F811 - pytest fixture reuse
    """Невалидный контент answer — step 4 (answer schema), state не тронут.

    `research-answer/v1` shares the same `gap.answered_by` pattern as
    `research-pack/v1`, so this fires at step 4 (raw answer schema check)
    rather than step 5 (assembled-artifact pre-validation) — step 5 has
    its own dedicated test below.
    """
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    bad = dict(RA_CONTENT_IT0)
    bad["gaps"] = [
        {
            "what": "g",
            "blocks_approval": True,
            "closed": True,
            "answered_by": "not-a-ref",
        }
    ]
    ans = _write_yaml(tmp_path / "ra.yaml", bad)
    with pytest.raises(HarnessError, match="invalid answer"):
        _step(loop_ws, Path(r1["path"]), ans)
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"] is None  # никакого verdict=failed


def test_step_prevalidates_assembled_artifact(
    loop_ws: Path,  # noqa: F811 - pytest fixture reuse
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 5 (assembled-artifact pre-validation) actually fires.

    research-answer/v1 and concept-answer/v1 mirror every content-level
    sub-schema of research-pack/v1 and concept-draft/v1, so any
    content-level defect is already caught at step 4 (raw answer schema)
    — step 5 never runs on it. The only defect class step 5 alone can
    catch is a bug in assembly itself: a bookkeeping field the answer
    schema never sees. Simulate that by monkeypatching
    `loop_harness._assemble_artifact` to corrupt `idea_ref` on the doc
    it returns (answer + brief stay untouched and schema-valid on their
    own), then assert the typed step-5 error fires, the runner is never
    invoked, and nothing is persisted.
    """
    import impresario.loop_harness as loop_harness_mod
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)

    original_assemble = loop_harness_mod._assemble_artifact

    def _corrupting_assemble(*args: object, **kwargs: object) -> dict:
        doc = original_assemble(*args, **kwargs)  # type: ignore[arg-type]
        doc["idea_ref"] = "BOGUS"  # invisible to research-answer/v1
        return doc

    monkeypatch.setattr(loop_harness_mod, "_assemble_artifact", _corrupting_assemble)

    state_path = loop_ws / "loop.state"
    state_before = state_path.read_bytes()
    artifacts_before = sorted(loop_ws.glob("rp-*.yaml"))
    assert artifacts_before == []

    with pytest.raises(HarnessError, match="refusing to run"):
        _step(loop_ws, Path(r1["path"]), ans)

    assert state_path.read_bytes() == state_before  # runner never invoked
    assert sorted(loop_ws.glob("rp-*.yaml")) == []  # nothing persisted


def test_step_oracle_equivalence_happy(loop_ws: Path, tmp_path: Path) -> None:  # noqa: F811 - pytest fixture reuse
    """Пошаговый happy эквивалентен ScriptedAgent-прогону (спека: не
    байт-равенство — модуло produced_by/produced_at/provenance/хеши)."""
    from impresario.agents import ScriptedAgent
    from impresario.loop import init_loop, run_loop
    from impresario.loop_harness import render_stage_brief

    # Эталонный workspace: тот же init, что в фикстуре loop_ws
    # (свериться с tests/test_loop.py и продублировать аргументы —
    # idea-файл, loop_id="LOOP-001", proposal/exchange ids,
    # max_iterations=2, now_iso=NOW).
    ref_ws = tmp_path / "ref"
    idea_file = tmp_path / "idea-source.yaml"
    idea_file.write_text(
        (loop_ws / "idea.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    init_loop(
        ref_ws,
        idea_file,
        CONTRACTS_DIR,
        loop_id="LOOP-001",
        proposal_id="PP-001",
        exchange_log_id="XL-001",
        max_iterations=2,
        now_iso=NOW,
    )
    scripted = run_loop(ref_ws, CONTRACTS_DIR, ScriptedAgent(HAPPY_SCRIPT), now_iso=NOW)
    assert scripted.verdict == "ready_for_business"

    # step-сторона: 4 стадии через brief/step (RA/CA итераций 0 и 1 —
    # контент из HAPPY_SCRIPT без bookkeeping), до терминального вердикта.
    answers = {
        ("researcher", 0): RA_CONTENT_IT0,
        ("creator", 0): CA_CONTENT_IT0,
        ("researcher", 1): RA_CONTENT_IT1,
        ("creator", 1): CA_CONTENT_IT1,
    }
    last = None
    for n in range(4):
        r = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
        ans = _write_yaml(tmp_path / f"a{n}.yaml", answers[(r["role"], r["iteration"])])
        last = _step(loop_ws, Path(r["path"]), ans)
    assert last is not None and last["runner"]["verdict"] == "ready_for_business"

    # (а) контент RP/CD: dict-сравнение после удаления produced_by,
    #     produced_at, provenance у step-артефактов и produced_by,
    #     produced_at у scripted (id сравнивать — совпадают: RP-001...).
    for artifact_id in ("RP-001", "RP-002", "CD-001", "CD-002"):
        step_doc = load_doc(loop_ws / f"{artifact_id.lower()}.yaml")
        ref_doc = load_doc(ref_ws / f"{artifact_id.lower()}.yaml")
        step_content = {
            k: v
            for k, v in step_doc.data.items()
            if k not in ("produced_by", "produced_at", "provenance")
        }
        ref_content = {
            k: v
            for k, v in ref_doc.data.items()
            if k not in ("produced_by", "produced_at")
        }
        assert step_content == ref_content, f"{artifact_id}: content diverges"

    # (б) delta_log proposal'ов равны.
    step_proposal = load_doc(loop_ws / "proposal.yaml")
    ref_proposal = load_doc(ref_ws / "proposal.yaml")
    assert (
        step_proposal.data["content"]["delta_log"]
        == ref_proposal.data["content"]["delta_log"]
    )

    # (в) последовательность событий trace (поле event) равна.
    def _events(workspace: Path) -> list[dict]:
        text = (workspace / "trace.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    step_trace = _events(loop_ws)
    ref_trace = _events(ref_ws)
    assert [e["event"] for e in step_trace] == [e["event"] for e in ref_trace]

    # (г) вердикты равны (ready_for_business) и loop.state равны модуло
    #     ничего (идея та же => idea_input_hash тот же; stop равны).
    step_state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    ref_state = json.loads((ref_ws / "loop.state").read_text(encoding="utf-8"))
    assert step_state["stop"]["verdict"] == "ready_for_business"
    assert ref_state["stop"]["verdict"] == "ready_for_business"
    assert step_state == ref_state

    # (д) события artifact_written равны модуло output_hash.
    def _artifact_written(events: list[dict]) -> list[dict]:
        return [
            {k: v for k, v in e.items() if k != "output_hash"}
            for e in events
            if e["event"] == "artifact_written"
        ]

    assert _artifact_written(step_trace) == _artifact_written(ref_trace)


def test_cli_forconcept_brief_and_step(loop_ws: Path, tmp_path: Path, capsys) -> None:  # noqa: F811 - pytest fixture reuse
    from impresario.cli import main

    code = main(["forconcept", "brief", str(loop_ws)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["role"] == "researcher"

    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    code = main(
        [
            "forconcept",
            "step",
            str(loop_ws),
            "--brief",
            out["path"],
            "--answer",
            str(ans),
            "--actor",
            "claude",
            "--model",
            "claude-fable-5",
        ]
    )
    out2 = json.loads(capsys.readouterr().out)
    assert code == 0 and out2["ok"] and out2["runner"]["verdict"] == "paused"


def test_cli_forconcept_step_typed_error_is_exit_2(
    loop_ws: Path,  # noqa: F811 - pytest fixture reuse
    tmp_path: Path,
    capsys,
) -> None:
    from impresario.cli import main

    code = main(
        [
            "forconcept",
            "step",
            str(loop_ws),
            "--brief",
            str(tmp_path / "нет.yaml"),
            "--answer",
            str(tmp_path / "нет2.yaml"),
            "--actor",
            "a",
            "--model",
            "m",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["ok"] is False
