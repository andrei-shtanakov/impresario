"""Stage 4 command tests: rank CAS semantics and typed QG-4 select."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from impresario.commands import cmd_rank, cmd_select
from impresario.hashing import canonical_doc_hash
from impresario.loader import load_doc
from impresario.schemas import check_schema, load_validators

from .conftest import CONTRACTS_DIR

NOW = "2026-08-12T15:00:00Z"


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _idea(num: int) -> dict[str, Any]:
    return {
        "id": f"IDEA-{num:03d}",
        "title": f"Idea {num}",
        "date": "2026-08-12",
        "source": {"kind": "internal", "ref": "test"},
        "priority": "medium",
        "business_attractiveness": 3,
        "status": "new",
        "hypothesis": "h",
    }


def _assessment(num: int, input_hash: str, score: int = 4) -> dict[str, Any]:
    return {
        "assessment_id": f"ASMT-{num:03d}",
        "idea_ref": f"idea://IDEA-{num:03d}",
        "run_id": "RUN-001",
        "input_hash": input_hash,
        "policy_version": "scoring/v1",
        "evidence_refs": ["test://evidence"],
        "fit_strategy": score,
        "fit_market": score,
        "fit_standards": score,
        "strategy_blocker": False,
        "standards_blocker": False,
        "confidence": "medium",
        "evaluator": {"kind": "human", "id": "tester"},
        "evaluated_at": "2026-08-12T10:00:00Z",
    }


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    for num, score in ((1, 5), (2, 3)):
        idea = _idea(num)
        _write(tmp_path / "ideas" / f"idea-{num:03d}.yaml", idea)
        _write(
            tmp_path / "assessments" / f"asmt-{num:03d}.yaml",
            _assessment(num, canonical_doc_hash(idea), score),
        )
    return tmp_path


def _rank(workspace: Path, **kwargs: Any):
    defaults: dict[str, Any] = {
        "apply": False,
        "expected_version": None,
        "backlog_id": "BL-test",
        "policy_file": None,
        "actor": "tester",
        "now_iso": NOW,
    }
    defaults.update(kwargs)
    return cmd_rank(workspace, CONTRACTS_DIR, **defaults)


def test_dry_run_proposes_and_writes_nothing(workspace: Path) -> None:
    report, proposed = _rank(workspace)
    assert report.ok, [f.message for f in report.errors]
    assert proposed is not None and proposed["version"] == 1
    assert [i["idea_ref"] for i in proposed["items"]] == [
        "idea://IDEA-001",
        "idea://IDEA-002",
    ]
    assert not (workspace / "backlog.yaml").exists()
    assert (
        not list((workspace / "runs").glob("*"))
        if (workspace / "runs").exists()
        else True
    )


def test_apply_writes_valid_backlog_and_run_record(workspace: Path) -> None:
    report, proposed = _rank(workspace, apply=True)
    assert report.ok, [f.message for f in report.errors]
    validators = load_validators(CONTRACTS_DIR)
    backlog = load_doc(workspace / "backlog.yaml")
    assert backlog.data == proposed
    assert check_schema(backlog, validators) == []
    runs = sorted((workspace / "runs").glob("*.yaml"))
    assert len(runs) == 1
    run = load_doc(runs[0])
    assert check_schema(run, validators) == []
    # RUN-001 belongs to the evaluation run referenced by assessments.
    assert run.data["run_id"] == "RUN-002"
    assert run.data["backlog_version_after"] == 1


def test_p07_reapply_is_reproducible(workspace: Path) -> None:
    _, first = _rank(workspace, apply=True)
    report, second = _rank(workspace, apply=True, expected_version=1)
    assert report.ok
    assert first is not None and second is not None
    assert second["version"] == 2
    assert second["items"] == first["items"]
    assert second["last_run_id"] == "RUN-003"


def test_stale_input_hash_blocks_apply(workspace: Path) -> None:
    idea_path = workspace / "ideas" / "idea-001.yaml"
    data = yaml.safe_load(idea_path.read_text(encoding="utf-8"))
    data["title"] = "Changed after evaluation"
    _write(idea_path, data)
    report, _ = _rank(workspace, apply=True)
    assert not report.ok
    assert {f.code for f in report.errors} == {"STALE_INPUT"}
    assert not (workspace / "backlog.yaml").exists()


def test_version_conflict_blocks_apply(workspace: Path) -> None:
    _rank(workspace, apply=True)
    report, _ = _rank(workspace, apply=True, expected_version=7)
    assert {f.code for f in report.errors} == {"VERSION_CONFLICT"}


def test_first_apply_requires_backlog_id(workspace: Path) -> None:
    report, _ = _rank(workspace, backlog_id=None)
    assert {f.code for f in report.errors} == {"USAGE"}


def _select(workspace: Path, idea_id: str, **kwargs: Any):
    defaults: dict[str, Any] = {
        "expected_version": 1,
        "actor": "andrei",
        "reason": "top-ranked, evidence reviewed",
        "role": "qg4_selector",
        "now_iso": NOW,
    }
    defaults.update(kwargs)
    return cmd_select(workspace, CONTRACTS_DIR, idea_id=idea_id, **defaults)


def test_select_happy_path(workspace: Path) -> None:
    _rank(workspace, apply=True)
    report, decision = _select(workspace, "IDEA-001")
    assert report.ok, [f.message for f in report.errors]
    validators = load_validators(CONTRACTS_DIR)

    decisions = sorted((workspace / "decisions").glob("*.yaml"))
    assert len(decisions) == 1
    decision_doc = load_doc(decisions[0])
    assert check_schema(decision_doc, validators) == []
    assert decision_doc.data == decision
    assert decision_doc.data["decided_by"]["kind"] == "human"

    backlog = load_doc(workspace / "backlog.yaml")
    assert backlog.data["version"] == 2
    selected = [i for i in backlog.data["items"] if i["status"] == "selected"]
    assert [i["idea_ref"] for i in selected] == ["idea://IDEA-001"]

    idea = load_doc(workspace / "ideas" / "idea-001.yaml")
    assert idea.data["status"] == "selected"


def test_select_preserves_idea_file_bytes_except_status(workspace: Path) -> None:
    idea_path = workspace / "ideas" / "idea-001.yaml"
    original = idea_path.read_text(encoding="utf-8")
    idea_path.write_text("# authored comment\n" + original, encoding="utf-8")
    # re-evaluate after the edit so input hashes match
    idea = yaml.safe_load(idea_path.read_text(encoding="utf-8"))
    _write(
        workspace / "assessments" / "asmt-001.yaml",
        _assessment(1, canonical_doc_hash(idea), 5),
    )
    _rank(workspace, apply=True)
    _select(workspace, "IDEA-001")
    updated = idea_path.read_text(encoding="utf-8")
    assert updated.startswith("# authored comment\n")
    assert "status: selected" in updated


def test_select_stale_version_writes_nothing(workspace: Path) -> None:
    _rank(workspace, apply=True)
    report, _ = _select(workspace, "IDEA-001", expected_version=9)
    assert {f.code for f in report.errors} == {"VERSION_CONFLICT"}
    assert not (workspace / "decisions").exists() or not list(
        (workspace / "decisions").glob("*.yaml")
    )
    assert load_doc(workspace / "backlog.yaml").data["version"] == 1


def test_select_rejects_card_changed_after_ranking(workspace: Path) -> None:
    _rank(workspace, apply=True)
    idea_path = workspace / "ideas" / "idea-001.yaml"
    data = yaml.safe_load(idea_path.read_text(encoding="utf-8"))
    data["title"] = "Edited after ranking"
    _write(idea_path, data)
    report, _ = _select(workspace, "IDEA-001")
    assert {f.code for f in report.errors} == {"STALE_INPUT"}
    assert not (workspace / "decisions").exists() or not list(
        (workspace / "decisions").glob("*.yaml")
    )
    assert load_doc(workspace / "backlog.yaml").data["version"] == 1


def test_select_requires_run_record(workspace: Path) -> None:
    _rank(workspace, apply=True)
    for run in (workspace / "runs").glob("*.yaml"):
        run.unlink()
    report, _ = _select(workspace, "IDEA-001")
    assert {f.code for f in report.errors} == {"RUN_RECORD_MISSING"}


def test_select_keeps_inline_status_comment(workspace: Path) -> None:
    idea_path = workspace / "ideas" / "idea-001.yaml"
    text = idea_path.read_text(encoding="utf-8")
    idea_path.write_text(
        text.replace("status: new", "status: new  # funnel stage"),
        encoding="utf-8",
    )
    _rank(workspace, apply=True)  # comment does not change the canonical hash
    report, _ = _select(workspace, "IDEA-001")
    assert report.ok, [f.message for f in report.errors]
    updated = idea_path.read_text(encoding="utf-8")
    assert "status: selected  # funnel stage" in updated


def test_prepare_idea_status_requires_status_line(tmp_path: Path) -> None:
    from impresario.workspace import WorkspaceError, prepare_idea_status

    card = tmp_path / "idea.yaml"
    card.write_text("id: IDEA-001\ntitle: no status here\n", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        prepare_idea_status(card, "selected")


def test_select_rejects_non_ranked_idea(workspace: Path) -> None:
    idea = _idea(3)
    _write(workspace / "ideas" / "idea-003.yaml", idea)
    # no assessment -> IDEA-003 lands in pending_unknown
    _rank(workspace, apply=True)
    report, _ = _select(workspace, "IDEA-003")
    assert {f.code for f in report.errors} == {"NOT_SELECTABLE"}
    assert "pending_unknown" in report.errors[0].message
