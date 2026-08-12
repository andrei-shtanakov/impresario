"""Deterministic rank engine unit tests (P-07 and bucketing)."""

from __future__ import annotations

import random
from typing import Any

from impresario.engine import Policy, build_backlog, normalize_assessments

NOW = "2026-08-12T15:00:00Z"


def _idea(num: int, **overrides: Any) -> dict[str, Any]:
    idea = {
        "id": f"IDEA-{num:03d}",
        "title": f"Idea {num}",
        "date": "2026-08-12",
        "source": {"kind": "internal", "ref": "test"},
        "priority": "medium",
        "business_attractiveness": 3,
        "status": "new",
        "hypothesis": "h",
    }
    idea.update(overrides)
    return idea


def _assessment(num: int, s: Any, m: Any, st: Any, **overrides: Any) -> dict:
    assessment = {
        "assessment_id": f"ASMT-{num:03d}",
        "idea_ref": f"idea://IDEA-{num:03d}",
        "run_id": "RUN-001",
        "input_hash": "sha256:" + "a" * 64,
        "policy_version": "scoring/v1",
        "evidence_refs": [],
        "fit_strategy": s,
        "fit_market": m,
        "fit_standards": st,
        "strategy_blocker": False,
        "standards_blocker": False,
        "confidence": "medium",
        "evaluator": {"kind": "human", "id": "tester"},
        "evaluated_at": "2026-08-12T10:00:00Z",
    }
    assessment.update(overrides)
    return assessment


def _build(ideas: list[dict], assessments: list[dict]) -> dict[str, Any]:
    return build_backlog(
        backlog_id="BL-test",
        version=1,
        ideas=ideas,
        assessments_by_idea=normalize_assessments(assessments),
        policy=Policy(),
        run_id="RUN-002",
        now_iso=NOW,
    )


def test_deterministic_and_order_independent() -> None:
    ideas = [_idea(i) for i in range(1, 6)]
    assessments = [_assessment(i, 5 - i % 3, 3, 4) for i in range(1, 6)]
    first = _build(ideas, assessments)
    shuffled_ideas, shuffled_assessments = ideas[:], assessments[:]
    random.Random(7).shuffle(shuffled_ideas)
    random.Random(9).shuffle(shuffled_assessments)
    assert _build(shuffled_ideas, shuffled_assessments) == first


def test_score_is_weighted_average_rounded() -> None:
    backlog = _build([_idea(1)], [_assessment(1, 4, 4, 3)])
    assert backlog["items"][0]["score"] == 3.67


def test_tie_break_by_idea_id() -> None:
    backlog = _build(
        [_idea(2), _idea(1)],
        [_assessment(2, 3, 3, 3), _assessment(1, 3, 3, 3)],
    )
    assert [i["idea_ref"] for i in backlog["items"]] == [
        "idea://IDEA-001",
        "idea://IDEA-002",
    ]
    assert [i["rank"] for i in backlog["items"]] == [1, 2]


def test_unknown_axis_goes_to_pending() -> None:
    backlog = _build([_idea(1)], [_assessment(1, "unknown", 4, 4)])
    assert backlog["items"] == []
    entry = backlog["pending_unknown"][0]
    assert entry["missing_inputs"] == ["fit_strategy = unknown"]


def test_missing_assessment_goes_to_pending() -> None:
    backlog = _build([_idea(1)], [])
    entry = backlog["pending_unknown"][0]
    assert entry["missing_inputs"] == ["AxisAssessment отсутствует"]
    assert entry["fit_market"] == "unknown"


def test_proven_blocker_goes_to_excluded() -> None:
    blocked = _assessment(
        1,
        3,
        4,
        1,
        standards_blocker=True,
        standards_blocker_ref="standards://ecosystem/STD-6",
    )
    backlog = _build([_idea(1)], [blocked])
    assert backlog["items"] == []
    entry = backlog["excluded"][0]
    assert entry["reason_kind"] == "blocker"
    assert entry["standards_blocker_ref"] == "standards://ecosystem/STD-6"


def test_priority_thresholds() -> None:
    backlog = _build(
        [_idea(1), _idea(2), _idea(3)],
        [
            _assessment(1, 5, 4, 4),  # 4.33 -> high
            _assessment(2, 3, 3, 3),  # 3.0 -> medium
            _assessment(3, 2, 2, 2),  # 2.0 -> low
        ],
    )
    assert [i["priority"] for i in backlog["items"]] == [
        "high",
        "medium",
        "low",
    ]


def test_normalization_picks_latest_assessment() -> None:
    older = _assessment(1, 2, 2, 2)
    newer = _assessment(
        1,
        5,
        5,
        5,
        assessment_id="ASMT-900",
        evaluated_at="2026-08-12T12:00:00Z",
    )
    chosen = normalize_assessments([newer, older])
    assert chosen["idea://IDEA-001"]["assessment_id"] == "ASMT-900"
    assert normalize_assessments([older, newer]) == chosen
