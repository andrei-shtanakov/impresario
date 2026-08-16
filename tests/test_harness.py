"""Промпт-харнесс оценщика: identity, render, ingest (spec 2026-08-16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


def test_find_prompts_dir_walks_up() -> None:
    from impresario.harness import find_prompts_dir

    assert find_prompts_dir(REPO_ROOT / "pilot") == PROMPTS_DIR


def test_find_prompts_dir_missing_raises(tmp_path: Path) -> None:
    from impresario.harness import find_prompts_dir

    with pytest.raises(FileNotFoundError):
        find_prompts_dir(tmp_path)


def test_sha256_bytes_format() -> None:
    from impresario.harness import sha256_bytes

    digest = sha256_bytes(b"abc")
    assert digest == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_prompt_pack_exists_and_carries_placeholders() -> None:
    text = (PROMPTS_DIR / "prioritizer" / "v1" / "prompt.md").read_text(
        encoding="utf-8"
    )
    for token in ("{idea}", "{strategy}", "{standards}"):
        assert token in text
    assert "assessment-answer/v1" in text  # скелет ответа с дискриминатором
