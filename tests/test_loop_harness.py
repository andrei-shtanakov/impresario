"""Researcher/creator-харнесс цикла (spec 2026-08-16-loop-agent-harness)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import CONTRACTS_DIR, REPO_ROOT
from .test_loop import (
    HAPPY_SCRIPT,
    NOW,
    STUCK_SCRIPT,
    loop_ws,  # noqa: F401 - fixture reuse
)
from .test_loop import _run as run_scripted

PROMPTS_DIR = REPO_ROOT / "prompts"


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
