from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "data" / "final-four-policy.json"

STAGE_ALIASES = {
    "SEMI_FINAL": "SEMI_FINAL",
    "SEMI_FINALS": "SEMI_FINAL",
    "SEMIFINAL": "SEMI_FINAL",
    "SEMIFINALS": "SEMI_FINAL",
    "FINAL": "FINAL",
    "THIRD_PLACE": "THIRD_PLACE",
    "THIRD_PLACE_PLAY_OFF": "THIRD_PLACE",
    "THIRD_PLACE_PLAYOFF": "THIRD_PLACE",
    "BRONZE_FINAL": "THIRD_PLACE",
    "BRONZE_MATCH": "THIRD_PLACE",
}

# FIFA lists host-local dates. The production forecast contract uses Beijing
# calendar dates, so the late North American kickoffs roll into the next day.
BEIJING_STAGE_DATES_2026 = {
    "2026-07-15": "SEMI_FINAL",
    "2026-07-16": "SEMI_FINAL",
    "2026-07-19": "THIRD_PLACE",
    "2026-07-20": "FINAL",
}

OUTCOMES = ("home", "draw", "away")


def load_final_four_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_stage(value: str | None) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def infer_final_four_stage(
    stage: str | None,
    kickoff: str | None = None,
    target_date: str | None = None,
) -> tuple[str | None, str | None]:
    explicit = STAGE_ALIASES.get(_normalized_stage(stage))
    if explicit:
        return explicit, "fixture_stage"

    kickoff_date = None
    if kickoff:
        try:
            kickoff_date = datetime.fromisoformat(kickoff).date().isoformat()
        except ValueError:
            kickoff_date = None
    inferred = BEIJING_STAGE_DATES_2026.get(kickoff_date or str(target_date or ""))
    if inferred:
        return inferred, "official_2026_beijing_schedule"
    return None, None


def _scaled_expected_goals(home: float, away: float, multiplier: float) -> tuple[float, float]:
    total = home + away
    if total <= 0:
        return home, away
    target_total = total * multiplier
    return target_total * home / total, target_total * away / total


def apply_final_four_policy(
    seeds: list[dict[str, Any]],
    target_date: str,
    policy: Mapping[str, Any] | None = None,
) -> None:
    settings = dict(policy or load_final_four_policy())
    profiles = settings["stageProfiles"]
    validation = settings.get("validation", {})

    for seed in seeds:
        stage, source = infer_final_four_stage(seed.get("stage"), seed.get("kickoff"), target_date)
        if stage is None:
            continue

        profile = dict(profiles[stage])
        base_home, base_away = map(float, seed["base_xg"])
        candidate_home, candidate_away = _scaled_expected_goals(
            base_home,
            base_away,
            float(profile["candidateTotalXgMultiplier"]),
        )
        blend = min(1.0, max(0.0, float(profile.get("activeMatrixBlend", 0.0))))
        adjusted_home = (1.0 - blend) * base_home + blend * candidate_home
        adjusted_away = (1.0 - blend) * base_away + blend * candidate_away
        coverage_before = float(seed.get("coverage", 0.70))
        coverage_after = max(0.0, coverage_before - float(profile["coveragePenalty"]))

        seed["stage"] = stage
        seed["base_xg"] = [adjusted_home, adjusted_away]
        seed["coverage"] = coverage_after
        seed["final_four_context"] = {
            "policy": settings["policy"],
            "predictionTarget": settings["predictionTarget"],
            "stage": stage,
            "stageSource": source,
            "applied": True,
            "matrixAdjustmentApplied": blend > 0,
            "diagnosticOnly": blend <= 0,
            "validationStatus": validation.get("status", "diagnostic_only"),
            "validationReason": validation.get("reason"),
            "stageParameters": profile,
            "preStageExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "candidateExpectedGoals": {
                "home": round(candidate_home, 4),
                "away": round(candidate_away, 4),
            },
            "adjustedExpectedGoals": {
                "home": round(adjusted_home, 4),
                "away": round(adjusted_away, 4),
            },
            "coverageBefore": round(coverage_before, 4),
            "coverageAfter": round(coverage_after, 4),
        }
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "preFinalFourExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "finalFourLayer": settings["policy"],
            "finalFourStage": stage,
            "finalFourMatrixBlend": blend,
            "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
        }


def outcome_confidence_intervals(
    probabilities: Mapping[str, float],
    coverage: float,
    uncertainty_multiplier: float,
) -> dict[str, list[float]]:
    effective_n = max(20.0, 250.0 * max(0.0, min(1.0, coverage)))
    effective_n /= max(1.0, float(uncertainty_multiplier)) ** 2
    data_penalty = (1.0 - max(0.0, min(1.0, coverage))) * 0.08
    intervals: dict[str, list[float]] = {}
    for outcome in OUTCOMES:
        probability = max(0.0, min(1.0, float(probabilities[outcome])))
        error = 1.96 * math.sqrt(max(1e-9, probability * (1.0 - probability) / effective_n))
        intervals[outcome] = [
            round(max(0.0, probability - error - data_penalty), 5),
            round(min(1.0, probability + error + data_penalty), 5),
        ]
    return intervals


def build_final_four_market_assessment(
    context: Mapping[str, Any] | None,
    model_probabilities: Mapping[str, float],
    market_probabilities: Mapping[str, float | None] | None,
    coverage: float,
) -> dict[str, Any] | None:
    if not context:
        return None
    profile = context["stageParameters"]
    threshold = float(profile["valueProbabilityGap"])
    intervals = outcome_confidence_intervals(
        model_probabilities,
        coverage,
        float(profile["uncertaintyMultiplier"]),
    )
    complete_market = bool(market_probabilities) and all(
        market_probabilities.get(outcome) is not None for outcome in OUTCOMES
    )
    if not complete_market:
        return {
            "policy": "final_four_value_assessment_v1",
            "predictionTarget": "90_minutes",
            "stage": context["stage"],
            "confidence95": intervals,
            "noVigMarketProbabilities": None,
            "probabilityGaps": None,
            "valueProbabilityGap": threshold,
            "valueSelections": [],
            "status": "market_unavailable",
            "conclusion": "市场概率不完整，不能判断统计价值",
        }

    market = {outcome: float(market_probabilities[outcome]) for outcome in OUTCOMES}
    gaps = {
        outcome: round(float(model_probabilities[outcome]) - market[outcome], 5)
        for outcome in OUTCOMES
    }
    value_selections = [
        outcome
        for outcome in OUTCOMES
        if gaps[outcome] >= threshold and intervals[outcome][0] > market[outcome]
    ]
    return {
        "policy": "final_four_value_assessment_v1",
        "predictionTarget": "90_minutes",
        "stage": context["stage"],
        "confidence95": intervals,
        "noVigMarketProbabilities": {key: round(value, 5) for key, value in market.items()},
        "probabilityGaps": gaps,
        "valueProbabilityGap": threshold,
        "valueSelections": value_selections,
        "status": "value_identified" if value_selections else "no_clear_value",
        "conclusion": "存在通过安全边际的统计价值" if value_selections else "无明显价值玩法或不确定性最高",
    }
