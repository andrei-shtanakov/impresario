"""Deterministic rank engine (P-07): normalized assessments in, backlog out.

The LLM proposes assessments; this engine owns the rank. Same normalized
assessments + same policy + same idea set => the same RankedBacklog. A new
LLM call is a new evaluation run, never a silent re-rank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AXES = ("fit_strategy", "fit_market", "fit_standards")


@dataclass(frozen=True)
class Policy:
    """Scoring policy materialized into every backlog version."""

    policy_version: str = "scoring/v1"
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "fit_strategy": 0.3333,
            "fit_market": 0.3333,
            "fit_standards": 0.3334,
        }
    )
    priority_thresholds: dict[str, float] = field(
        default_factory=lambda: {"high": 4.0, "medium": 2.5}
    )
    strategy_ref: str = "strategy://ecosystem/2026"
    standards_ref: str = "standards://ecosystem"

    def as_dict(self) -> dict[str, Any]:
        """Policy block of the RankedBacklog document."""
        return {
            "policy_version": self.policy_version,
            "weights": dict(self.weights),
            "priority_thresholds": dict(self.priority_thresholds),
            "strategy_ref": self.strategy_ref,
            "standards_ref": self.standards_ref,
        }

    def propose_priority(self, score: float) -> str:
        """Default priority proposal by score thresholds."""
        if score >= self.priority_thresholds["high"]:
            return "high"
        if score >= self.priority_thresholds["medium"]:
            return "medium"
        return "low"


def policy_from_dict(data: dict[str, Any]) -> Policy:
    """Build a Policy from a partial mapping (unset fields keep defaults)."""
    base = Policy()
    return Policy(
        policy_version=data.get("policy_version", base.policy_version),
        weights=dict(data.get("weights", base.weights)),
        priority_thresholds=dict(
            data.get("priority_thresholds", base.priority_thresholds)
        ),
        strategy_ref=data.get("strategy_ref", base.strategy_ref),
        standards_ref=data.get("standards_ref", base.standards_ref),
    )


def normalize_assessments(
    assessments: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Pick exactly one assessment per idea: latest evaluated_at, then max id.

    Deterministic regardless of input order — part of the P-07 contract.
    """
    chosen: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        idea_ref = str(assessment.get("idea_ref"))
        current = chosen.get(idea_ref)
        if current is None or _assessment_key(assessment) > _assessment_key(current):
            chosen[idea_ref] = assessment
    return chosen


def _assessment_key(assessment: dict[str, Any]) -> tuple[str, str]:
    return (
        str(assessment.get("evaluated_at", "")),
        str(assessment.get("assessment_id", "")),
    )


def _score(assessment: dict[str, Any], policy: Policy) -> float:
    total_weight = sum(policy.weights[axis] for axis in AXES)
    weighted = sum(policy.weights[axis] * float(assessment[axis]) for axis in AXES)
    return round(weighted / total_weight, 2)


def _has_blocker(assessment: dict[str, Any]) -> bool:
    return bool(assessment.get("strategy_blocker")) or bool(
        assessment.get("standards_blocker")
    )


def _axis_snapshot(assessment: dict[str, Any] | None) -> dict[str, Any]:
    if assessment is None:
        return dict.fromkeys(AXES, "unknown")
    return {axis: assessment[axis] for axis in AXES}


def build_backlog(
    backlog_id: str,
    version: int,
    ideas: list[dict[str, Any]],
    assessments_by_idea: dict[str, dict[str, Any]],
    policy: Policy,
    run_id: str,
    now_iso: str,
) -> dict[str, Any]:
    """Materialize a RankedBacklog document from ideas and assessments.

    Buckets (each idea lands in exactly one):
    excluded[] (proven blocker) > pending_unknown[] (any unknown axis or no
    assessment) > items[] (fully scored, ranked by score desc, idea id asc).
    """
    scored: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for idea in sorted(ideas, key=lambda i: str(i.get("id"))):
        idea_ref = f"idea://{idea['id']}"
        assessment = assessments_by_idea.get(idea_ref)
        if assessment is not None and _has_blocker(assessment):
            excluded.append(_excluded_entry(idea, idea_ref, assessment))
        elif assessment is None or any(assessment[axis] == "unknown" for axis in AXES):
            pending.append(_pending_entry(idea, idea_ref, assessment))
        else:
            scored.append(_scored_candidate(idea, idea_ref, assessment, policy))

    scored.sort(key=lambda c: (-c["score"], c["idea_ref"]))
    for rank, candidate in enumerate(scored, start=1):
        candidate["rank"] = rank

    return {
        "id": backlog_id,
        "version": version,
        "updated_at": now_iso,
        "policy": policy.as_dict(),
        "items": [_finalize_item(c) for c in scored],
        "pending_unknown": pending,
        "excluded": excluded,
        "last_run_id": run_id,
    }


def _scored_candidate(
    idea: dict[str, Any],
    idea_ref: str,
    assessment: dict[str, Any],
    policy: Policy,
) -> dict[str, Any]:
    score = _score(assessment, policy)
    return {
        "idea_ref": idea_ref,
        "title": idea["title"],
        "source_kind": idea["source"]["kind"],
        "status": idea["status"],
        "priority": policy.propose_priority(score),
        "score": score,
        **_axis_snapshot(assessment),
        "strategy_blocker": False,
        "standards_blocker": False,
        "assessment_ref": f"assessment://{assessment['assessment_id']}",
    }


def _finalize_item(candidate: dict[str, Any]) -> dict[str, Any]:
    ordered = {"rank": candidate.pop("rank")}
    ordered.update(candidate)
    return ordered


def _pending_entry(
    idea: dict[str, Any], idea_ref: str, assessment: dict[str, Any] | None
) -> dict[str, Any]:
    if assessment is None:
        missing = ["AxisAssessment отсутствует"]
    else:
        missing = [
            f"{axis} = unknown" for axis in AXES if assessment[axis] == "unknown"
        ]
    entry: dict[str, Any] = {
        "idea_ref": idea_ref,
        "title": idea["title"],
        **_axis_snapshot(assessment),
        "missing_inputs": missing,
    }
    if assessment is not None:
        entry["assessment_ref"] = f"assessment://{assessment['assessment_id']}"
    return entry


def _excluded_entry(
    idea: dict[str, Any], idea_ref: str, assessment: dict[str, Any]
) -> dict[str, Any]:
    reasons = [
        f"{flag}: {assessment.get(flag + '_ref')}"
        for flag in ("strategy_blocker", "standards_blocker")
        if assessment.get(flag)
    ]
    entry: dict[str, Any] = {
        "idea_ref": idea_ref,
        "title": idea["title"],
        "reason_kind": "blocker",
        "reason": "формальный запрет — " + "; ".join(reasons),
        **_axis_snapshot(assessment),
        "assessment_ref": f"assessment://{assessment['assessment_id']}",
    }
    for flag in ("strategy_blocker", "standards_blocker"):
        if assessment.get(flag):
            entry[flag] = True
            entry[f"{flag}_ref"] = assessment[f"{flag}_ref"]
    return entry
