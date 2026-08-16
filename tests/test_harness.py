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


NOW = "2026-08-16T12:00:00Z"


def _good_answer() -> dict:
    return {
        "schema_version": "assessment-answer/v1",
        "fit_strategy": 5,
        "fit_market": "unknown",
        "fit_standards": 4,
        "strategy_blocker": False,
        "standards_blocker": False,
        "rationale": {
            "fit_strategy": "Прямое попадание в G-1.",
            "fit_market": "Замеров нет — честный unknown.",
            "fit_standards": "Соответствует STD-1.",
        },
        "evidence_refs": ["strategy://ecosystem/2026/G-1"],
        "confidence": "medium",
    }


def _ingest(ws_path: Path, pairs: list[tuple[Path, Path]], **kw):
    from impresario.harness import ingest_pairs

    defaults = dict(
        run_id="RUN-100", actor="claude", model="claude-fable-5", now_iso=NOW
    )
    defaults.update(kw)
    return ingest_pairs(ws_path, CONTRACTS_DIR, pairs=pairs, **defaults)


def test_ingest_happy_materializes_valid_assessment(
    assess_ws: Path, tmp_path: Path
) -> None:
    from impresario.cli import validate_paths
    from impresario.harness import render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    answer_path = tmp_path / "answer.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = _ingest(assess_ws, [(brief_path, answer_path)])
    assert result["ok"] and len(result["written"]) == 1

    asmt = load_doc(Path(result["written"][0]["path"]))
    assert asmt.kind == "axis-assessment"
    assert asmt.data["assessment_id"] == "ASMT-001"
    assert asmt.data["run_id"] == "RUN-100"
    assert asmt.data["input_hash"] == load_doc(brief_path).data["input_hash"]
    assert asmt.data["evaluator"] == {
        "kind": "agent",
        "id": "claude",
        "model": "claude-fable-5",
        "prompt_version": "prioritizer/v1",
    }
    assert asmt.data["provenance"]["brief_id"] == report["briefs"][0]["brief_id"]
    # собственный выход проходит контракты и бандл-чеки workspace
    bundle = validate_paths([assess_ws], CONTRACTS_DIR, bundle=True)
    assert bundle.ok, [f"{f.code}: {f.message}" for f in bundle.errors]


def test_ingest_stale_input(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    idea_path = assess_ws / "ideas" / "idea-001.yaml"
    idea_path.write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, hypothesis="changed"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(HarnessError, match="STALE_INPUT"):
        _ingest(assess_ws, [(brief_path, answer_path)])
    assert not list((assess_ws / "assessments").glob("*.yaml"))


def test_ingest_tampered_brief(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    doc = yaml.safe_load(brief_path.read_text(encoding="utf-8"))
    doc["prompt"] += "инъекция\n"
    tampered = tmp_path / "brief.yaml"
    tampered.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(HarnessError, match="BRIEF_IDENTITY"):
        _ingest(assess_ws, [(tampered, answer_path)])


def test_ingest_invalid_answer_writes_nothing(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    bad = dict(_good_answer(), input_hash="sha256:" + "a" * 64)  # bookkeeping
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(HarnessError):
        _ingest(assess_ws, [(brief_path, answer_path)])
    assert not list((assess_ws / "assessments").glob("*.yaml"))


def test_ingest_idempotent_retry_and_conflict(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    first = _ingest(assess_ws, [(brief_path, answer_path)])
    written_path = Path(first["written"][0]["path"])
    bytes_before = written_path.read_bytes()

    retry = _ingest(
        assess_ws, [(brief_path, answer_path)], now_iso="2026-08-16T13:00:00Z"
    )
    assert retry["written"] == [] and len(retry["noop"]) == 1
    assert written_path.read_bytes() == bytes_before  # первый evaluated_at жив

    divergent = dict(_good_answer(), confidence="low")
    answer2 = tmp_path / "b.yaml"
    answer2.write_text(yaml.safe_dump(divergent, allow_unicode=True), encoding="utf-8")
    with pytest.raises(HarnessError, match="ASSESS_CONFLICT"):
        _ingest(assess_ws, [(brief_path, answer2)])
    with pytest.raises(HarnessError, match="ASSESS_CONFLICT"):
        _ingest(assess_ws, [(brief_path, answer_path)], actor="другой")


def test_ingest_phase1_error_writes_nothing_for_any_pair(
    assess_ws: Path, tmp_path: Path
) -> None:
    """Вторая пара бита → не записана и первая (двухфазность)."""
    from impresario.harness import HarnessError, render_briefs

    (assess_ws / "ideas" / "idea-002.yaml").write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, id="IDEA-002", title="Second"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert len(report["briefs"]) == 2
    good_answer = tmp_path / "good.yaml"
    good_answer.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    bad_answer = tmp_path / "bad.yaml"
    bad_answer.write_text("schema_version: assessment-answer/v1\n", encoding="utf-8")
    pairs = [
        (Path(report["briefs"][0]["path"]), good_answer),
        (Path(report["briefs"][1]["path"]), bad_answer),
    ]
    with pytest.raises(HarnessError):
        _ingest(assess_ws, pairs)
    assert not list((assess_ws / "assessments").glob("*.yaml"))


def test_ingest_recovery_after_partial_write(
    assess_ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой между записями пар: повтор дозаписывает без дублей."""
    import impresario.harness as harness_mod
    from impresario.harness import render_briefs

    (assess_ws / "ideas" / "idea-002.yaml").write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, id="IDEA-002", title="Second"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    answers = []
    for i in (0, 1):
        p = tmp_path / f"a{i}.yaml"
        p.write_text(
            yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
        )
        answers.append(p)
    pairs = [
        (Path(report["briefs"][0]["path"]), answers[0]),
        (Path(report["briefs"][1]["path"]), answers[1]),
    ]

    original = harness_mod._write_assessment
    calls = {"n": 0}

    def flaky(path, content):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated crash mid commit phase")
        original(path, content)

    monkeypatch.setattr(harness_mod, "_write_assessment", flaky)
    with pytest.raises(OSError):
        _ingest(assess_ws, pairs)
    assert len(list((assess_ws / "assessments").glob("*.yaml"))) == 1

    monkeypatch.setattr(harness_mod, "_write_assessment", original)
    result = _ingest(assess_ws, pairs)
    assert len(result["noop"]) == 1 and len(result["written"]) == 1
    assert len(list((assess_ws / "assessments").glob("*.yaml"))) == 2


def test_cli_assess_render_and_ingest(assess_ws: Path, tmp_path: Path, capsys) -> None:
    import json as jsonlib

    from impresario.cli import main

    code = main(["assess", "render", str(assess_ws)])
    out = jsonlib.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] and len(out["briefs"]) == 1

    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    code = main(
        [
            "assess",
            "ingest",
            str(assess_ws),
            "--run-id",
            "RUN-100",
            "--actor",
            "claude",
            "--model",
            "claude-fable-5",
            "--brief",
            out["briefs"][0]["path"],
            "--answer",
            str(answer_path),
        ]
    )
    out2 = jsonlib.loads(capsys.readouterr().out)
    assert code == 0 and out2["ok"] and len(out2["written"]) == 1


def test_cli_assess_ingest_error_is_exit_2(
    assess_ws: Path, tmp_path: Path, capsys
) -> None:
    from impresario.cli import main

    code = main(
        [
            "assess",
            "ingest",
            str(assess_ws),
            "--run-id",
            "RUN-100",
            "--actor",
            "a",
            "--model",
            "m",
            "--brief",
            str(tmp_path / "нет.yaml"),
            "--answer",
            str(tmp_path / "нет2.yaml"),
        ]
    )
    assert code == 2


def test_cli_assess_render_idea_filter(assess_ws: Path, capsys) -> None:
    """Carried-over review item: --idea filtering had zero CLI coverage."""
    import json as jsonlib

    from impresario.cli import main

    (assess_ws / "ideas" / "idea-002.yaml").write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, id="IDEA-002", title="Second"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    code = main(["assess", "render", str(assess_ws), "--idea", "IDEA-001"])
    out = jsonlib.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"]
    assert len(out["briefs"]) == 1
    assert out["briefs"][0]["idea_ref"] == "idea://IDEA-001"
