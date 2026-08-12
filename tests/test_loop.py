"""Reference-loop tests: verdicts, crash/resume, idempotency, fail-closed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from impresario.agents import ScriptedAgent
from impresario.cli import validate_paths
from impresario.loader import load_doc
from impresario.loop import init_loop, run_loop

from .conftest import CONTRACTS_DIR

NOW = "2026-08-12T18:00:00Z"


def _idea() -> dict[str, Any]:
    return {
        "id": "IDEA-001",
        "title": "Loop test idea",
        "date": "2026-08-12",
        "source": {"kind": "internal", "ref": "test"},
        "priority": "high",
        "business_attractiveness": 4,
        "status": "selected",
        "hypothesis": "h",
    }


def _actor(role: str) -> dict[str, Any]:
    return {
        "kind": "agent",
        "id": role,
        "model": "vendor/model-x",
        "prompt_version": f"{role}/v1",
    }


def _rp(num: int, iteration: int, *, gap_open: bool) -> dict[str, Any]:
    return {
        "id": f"RP-{num:03d}",
        "idea_ref": "idea://IDEA-001",
        "proposal_ref": "proposal://PP-001",
        "iteration": iteration,
        "findings": [{"claim": "claim", "source_ref": "ref://x", "confidence": "high"}],
        "constraints": [],
        "gaps": [
            {
                "what": "critical gap",
                "blocks_approval": True,
                **({} if gap_open else {"closed": True}),
            }
        ],
        "brief_for_creator": "brief",
        "requests_to_creator": [],
        "produced_by": _actor("researcher"),
        "produced_at": NOW,
    }


def _cd(
    num: int,
    iteration: int,
    rp_num: int,
    *,
    assumption_open: bool,
    requests: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"CD-{num:03d}",
        "idea_ref": "idea://IDEA-001",
        "proposal_ref": "proposal://PP-001",
        "iteration": iteration,
        "based_on_research": {
            "ref": f"research-pack://RP-{rp_num:03d}",
            "iteration": iteration,
        },
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
                **(
                    {}
                    if assumption_open
                    else {"answered_by": f"research-pack://RP-{rp_num:03d}"}
                ),
            }
        ],
        "requests_to_researcher": requests or [],
        "proposal_delta": f"delta {iteration}",
        "produced_by": _actor("creator"),
        "produced_at": NOW,
    }


HAPPY_SCRIPT = {
    "researcher": {
        0: _rp(1, 0, gap_open=True),
        1: _rp(2, 1, gap_open=False),
    },
    "creator": {
        0: _cd(1, 0, 1, assumption_open=True, requests=["check the gap"]),
        1: _cd(2, 1, 2, assumption_open=False),
    },
}

STUCK_SCRIPT = {
    "researcher": {0: _rp(1, 0, gap_open=True), 1: _rp(2, 1, gap_open=True)},
    "creator": {
        0: _cd(1, 0, 1, assumption_open=True),
        1: _cd(2, 1, 2, assumption_open=True),
    },
}


@pytest.fixture()
def loop_ws(tmp_path: Path) -> Path:
    idea_file = tmp_path / "idea-source.yaml"
    idea_file.write_text(
        yaml.safe_dump(_idea(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    workspace = tmp_path / "loop"
    init_loop(
        workspace,
        idea_file,
        CONTRACTS_DIR,
        loop_id="LOOP-001",
        proposal_id="PP-001",
        exchange_log_id="XL-001",
        max_iterations=2,
        now_iso=NOW,
    )
    return workspace


def _run(workspace: Path, script: dict, stop_after: str | None = None):
    return run_loop(
        workspace,
        CONTRACTS_DIR,
        ScriptedAgent(script),
        now_iso=NOW,
        stop_after=stop_after,
    )


def _trace_events(workspace: Path) -> list[dict[str, Any]]:
    lines = (workspace / "trace.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in lines.splitlines()]


def test_happy_path_reaches_ready(loop_ws: Path) -> None:
    result = _run(loop_ws, HAPPY_SCRIPT)
    assert result.verdict == "ready_for_business"
    proposal = load_doc(loop_ws / "proposal.yaml")
    assert proposal.data["status"] == "ready_for_business"
    # v1 draft -> v2 in_iteration -> v3 delta0 -> v4 delta1 -> v5 ready
    assert proposal.data["version"] == 5
    log = load_doc(loop_ws / "exchange-log.yaml")
    assert [e["iteration"] for e in log.data["entries"]] == [0, 0, 0, 1, 1, 1]
    report = validate_paths([loop_ws], CONTRACTS_DIR, bundle=True)
    assert report.ok, [f.message for f in report.errors]


def test_stuck_loop_needs_human(loop_ws: Path) -> None:
    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    assert result.stop_reason is not None
    assert "critical" in result.stop_reason
    proposal = load_doc(loop_ws / "proposal.yaml")
    assert proposal.data["status"] == "in_iteration"
    report = validate_paths([loop_ws], CONTRACTS_DIR, bundle=True)
    assert report.ok, [f.message for f in report.errors]


def test_invalid_artifact_fails_closed(loop_ws: Path) -> None:
    broken = {
        "researcher": {0: {**_rp(1, 0, gap_open=True), "brief_for_creator": ""}},
        "creator": {},
    }
    result = _run(loop_ws, broken)
    assert result.verdict == "failed"
    assert not list(loop_ws.glob("rp-*.yaml"))  # invalid artifact not persisted
    assert not (loop_ws / "exchange-log.yaml").exists()


def test_terminal_verdict_rerun_is_noop(loop_ws: Path) -> None:
    first = _run(loop_ws, HAPPY_SCRIPT)
    before = sorted(
        (p.name, p.read_text(encoding="utf-8")) for p in loop_ws.glob("*.yaml")
    )
    trace_before = _trace_events(loop_ws)
    second = _run(loop_ws, HAPPY_SCRIPT)
    assert (second.verdict, second.stop_reason) == (
        first.verdict,
        first.stop_reason,
    )
    after = sorted(
        (p.name, p.read_text(encoding="utf-8")) for p in loop_ws.glob("*.yaml")
    )
    assert after == before
    assert _trace_events(loop_ws) == trace_before


@pytest.mark.parametrize(
    "boundary",
    [
        "start",
        "research:0",
        "concept:0",
        "apply:0",
        "evaluate:0",
        "research:1",
        "concept:1",
        "apply:1",
        # terminal-iteration evaluate: crash between the verdict trace and
        # the status/state writes
        "evaluate:1",
    ],
)
def test_crash_resume_at_every_boundary(
    tmp_path: Path, loop_ws: Path, boundary: str
) -> None:
    paused = _run(loop_ws, HAPPY_SCRIPT, stop_after=boundary)
    assert paused.verdict == "paused"
    resumed = _run(loop_ws, HAPPY_SCRIPT)
    assert resumed.verdict == "ready_for_business"

    # A never-crashed control run must be byte-identical (incl. the trace).
    control_idea = tmp_path / "idea2.yaml"
    control_idea.write_text(
        yaml.safe_dump(_idea(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    control = tmp_path / "control"
    init_loop(
        control,
        control_idea,
        CONTRACTS_DIR,
        loop_id="LOOP-001",
        proposal_id="PP-001",
        exchange_log_id="XL-001",
        max_iterations=2,
        now_iso=NOW,
    )
    _run(control, HAPPY_SCRIPT)
    for path in sorted(control.glob("*.yaml")):
        assert (loop_ws / path.name).read_text(encoding="utf-8") == path.read_text(
            encoding="utf-8"
        ), path.name
    assert _trace_events(loop_ws) == _trace_events(control)


def test_creator_stale_research_reference_fails(loop_ws: Path) -> None:
    script = {
        "researcher": dict(HAPPY_SCRIPT["researcher"]),
        "creator": {0: _cd(1, 0, 99, assumption_open=True)},
    }
    result = _run(loop_ws, script)
    assert result.verdict == "failed"
    assert result.stop_reason is not None
    assert "stale research" in result.stop_reason


def test_missing_script_entry_fails(loop_ws: Path) -> None:
    result = _run(loop_ws, {"researcher": {}, "creator": {}})
    assert result.verdict == "failed"
    assert result.stop_reason is not None
    assert "researcher" in result.stop_reason


def test_needs_human_resume_path(loop_ws: Path) -> None:
    from impresario.loop import LoopError, resume_loop

    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"

    # failed budget: resume must widen the iteration budget
    with pytest.raises(LoopError, match="budget"):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=2,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )

    resume_loop(
        loop_ws,
        CONTRACTS_DIR,
        max_iterations=3,
        actor="andrei",
        reason="owner decided the exempt semantics",
        now_iso=NOW,
    )
    unstuck = {
        "researcher": {
            **STUCK_SCRIPT["researcher"],
            2: _rp(3, 2, gap_open=False),
        },
        "creator": {
            **STUCK_SCRIPT["creator"],
            2: _cd(3, 2, 3, assumption_open=False),
        },
    }
    result = _run(loop_ws, unstuck)
    assert result.verdict == "ready_for_business"
    events = [e["event"] for e in _trace_events(loop_ws)]
    assert "resumed" in events
    report = validate_paths([loop_ws], CONTRACTS_DIR, bundle=True)
    assert report.ok, [f.message for f in report.errors]


def test_resume_retry_after_partial_failure_is_idempotent(
    loop_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry после сбоя между evidence и replace не дублирует resumed.

    Первая попытка пишет resumed и падает на записи state; ожидание
    остаётся активным. Retry с ДРУГИМ now_iso обязан не создать второй
    resumed (identity-dedup по iteration), сохранить at первой попытки
    и довести replace до stop: null.
    """
    import impresario.loop as loop_mod
    from impresario.loop import resume_loop

    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"

    original = loop_mod._write_state
    calls = {"n": 0}

    def flaky(workspace, state, validator):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated crash before atomic replace")
        original(workspace, state, validator)

    monkeypatch.setattr(loop_mod, "_write_state", flaky)
    with pytest.raises(OSError):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=3,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"]["verdict"] == "needs_human"  # ожидание активно

    later = "2026-08-12T19:00:00Z"
    resume_loop(
        loop_ws,
        CONTRACTS_DIR,
        max_iterations=3,
        actor="andrei",
        reason="r",
        now_iso=later,
    )
    resumed = [e for e in _trace_events(loop_ws) if e["event"] == "resumed"]
    assert len(resumed) == 1
    assert resumed[0]["at"] == NOW  # at первой попытки сохранён
    assert resumed[0]["iteration"] == 1
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"] is None


def test_resume_refuses_non_needs_human(loop_ws: Path) -> None:
    from impresario.loop import LoopError, resume_loop

    _run(loop_ws, HAPPY_SCRIPT)  # terminal: ready_for_business
    with pytest.raises(LoopError, match="needs_human"):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=5,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )


def test_init_rejects_zero_iterations(tmp_path: Path) -> None:
    from impresario.loop import LoopError

    idea_file = tmp_path / "idea.yaml"
    idea_file.write_text(
        yaml.safe_dump(_idea(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(LoopError, match="max_iterations"):
        init_loop(
            tmp_path / "loop",
            idea_file,
            CONTRACTS_DIR,
            loop_id="LOOP-001",
            proposal_id="PP-001",
            exchange_log_id="XL-001",
            max_iterations=0,
            now_iso=NOW,
        )


def test_stop_record_is_contract_valid(loop_ws: Path) -> None:
    from impresario.schemas import load_validators

    _run(loop_ws, STUCK_SCRIPT)
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"]["iteration"] == 1
    assert state["stop"]["at"] == NOW
    validator = load_validators(CONTRACTS_DIR)["loop-state"]
    assert list(validator.iter_errors(state)) == []


def test_write_state_rejects_invalid_state(loop_ws: Path) -> None:
    import impresario.loop as loop_mod
    from impresario.schemas import load_validators

    validator = load_validators(CONTRACTS_DIR)["loop-state"]
    before = (loop_ws / "loop.state").read_text(encoding="utf-8")
    with pytest.raises(loop_mod.LoopError, match="invalid loop-state"):
        loop_mod._write_state(loop_ws, {"loop_id": "nope"}, validator)
    assert (loop_ws / "loop.state").read_text(encoding="utf-8") == before


def test_cli_bad_script_is_json_error(
    loop_ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from impresario.cli import main

    bad_script = tmp_path / "bad.script"
    bad_script.write_text("- just\n- a list\n", encoding="utf-8")
    code = main(
        [
            "forconcept",
            "run",
            str(loop_ws),
            "--script",
            str(bad_script),
            "--contracts",
            str(CONTRACTS_DIR),
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert out["ok"] is False
    assert "script" in out["error"]
