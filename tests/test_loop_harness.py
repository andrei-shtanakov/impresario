"""Researcher/creator-харнесс цикла (spec 2026-08-16-loop-agent-harness)."""

from __future__ import annotations

import json

import pytest

from .conftest import CONTRACTS_DIR, REPO_ROOT

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
