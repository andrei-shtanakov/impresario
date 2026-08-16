"""Промпт-харнесс оценщика: identity, render, ingest (spec 2026-08-16)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from impresario.loader import load_doc
from impresario.schemas import load_validators

from .conftest import CONTRACTS_DIR, REPO_ROOT

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


IDEA_DOC = {
    "id": "IDEA-001",
    "title": "Test idea",
    "date": "2026-08-16",
    "source": {"kind": "internal", "ref": "test"},
    "priority": "high",
    "business_attractiveness": 3,
    "status": "new",
    "hypothesis": "h",
}


@pytest.fixture()
def assess_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "ideas").mkdir(parents=True)
    (ws / "ideas" / "idea-001.yaml").write_text(
        yaml.safe_dump(IDEA_DOC, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (ws / "strategy.md").write_text("# Стратегия\nG-1: цель.\n", encoding="utf-8")
    (ws / "standards.md").write_text("# Стандарты\nSTD-1: правило.\n", encoding="utf-8")
    return ws


def test_brief_identity_depends_on_prompt_hash() -> None:
    from impresario.harness import brief_identity

    fields = {
        "idea_ref": "idea://IDEA-001",
        "input_hash": "sha256:" + "a" * 64,
        "prompt_version": "prioritizer/v1",
        "prompt_pack_hash": "sha256:" + "b" * 64,
        "policy_version": "scoring/v1",
        "strategy_hash": "sha256:" + "c" * 64,
        "standards_hash": "sha256:" + "d" * 64,
        "prompt_hash": "sha256:" + "e" * 64,
    }
    base = brief_identity(fields)
    assert base.startswith("BRF-") and len(base) == 16
    changed = brief_identity({**fields, "prompt_hash": "sha256:" + "f" * 64})
    assert changed != base  # подмена промпта меняет identity


def test_render_is_deterministic_and_valid(assess_ws: Path) -> None:
    from impresario.harness import render_briefs

    report1 = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report1["ok"] and len(report1["briefs"]) == 1
    path = Path(report1["briefs"][0]["path"])
    bytes1 = path.read_bytes()

    report2 = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report2["briefs"] == report1["briefs"]
    assert path.read_bytes() == bytes1  # байтовый no-op

    doc = load_doc(path)
    assert doc.kind == "evaluation-brief"
    validators = load_validators(CONTRACTS_DIR)
    from impresario.schemas import check_schema

    assert check_schema(doc, validators) == []


def test_render_new_id_on_idea_change_keeps_old_brief(assess_ws: Path) -> None:
    from impresario.harness import render_briefs

    first = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    old_id = first["briefs"][0]["brief_id"]

    idea_path = assess_ws / "ideas" / "idea-001.yaml"
    changed = dict(IDEA_DOC, hypothesis="h2")
    idea_path.write_text(
        yaml.safe_dump(changed, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    second = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    new_id = second["briefs"][0]["brief_id"]
    assert new_id != old_id
    assert (assess_ws / "briefs" / f"{old_id.lower()}.yaml").exists()


def test_render_comment_only_edit_is_noop(assess_ws: Path) -> None:
    from impresario.harness import render_briefs

    first = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    idea_path = assess_ws / "ideas" / "idea-001.yaml"
    idea_path.write_text(
        "# комментарий\n" + idea_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    second = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert second["briefs"] == first["briefs"]


def test_render_refuses_divergent_bytes_under_same_id(assess_ws: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    path = Path(report["briefs"][0]["path"])
    tampered = path.read_text(encoding="utf-8").replace(
        "prioritizer/v1", "prioritizer/v1 "
    )
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(HarnessError, match="diverg"):
        render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
