from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .final_sprint_policy import load_final_sprint_policy
from .model import outcome_probabilities, total_goals_probabilities


GOAL_BUCKETS = ("0", "1", "2", "3", "4", "5", "6", "7+")


@dataclass(frozen=True)
class ScoreCalibrationResult:
    matrix: list[list[float]]
    metadata: dict[str, Any]


def _goal_bucket(home_goals: int, away_goals: int) -> str:
    total = home_goals + away_goals
    return "7+" if total >= 7 else str(total)


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def _normalize(matrix: list[list[float]]) -> list[list[float]]:
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return matrix
    return [[value / total for value in row] for row in matrix]


def _expected_total(totals: dict[str, float]) -> float:
    return sum((7 if label == "7+" else int(label)) * value for label, value in totals.items())


def _round_probabilities(values: dict[str, float]) -> dict[str, float]:
    return {key: round(float(values.get(key, 0.0)), 6) for key in values}


def _validation_summary(validation: Any, selected_intensity: float) -> dict[str, Any] | None:
    if not isinstance(validation, dict):
        return None
    candidates = validation.get("candidates") or {}
    baseline = candidates.get("0.00") or {}
    selected = candidates.get(f"{selected_intensity:.2f}") or {}
    return {
        "validationWeights": validation.get("validationWeights"),
        "selectedIntensity": selected_intensity,
        "selectionReason": validation.get("selectionReason"),
        "baselineWeightedLoss": baseline.get("weightedLoss"),
        "selectedWeightedLoss": selected.get("weightedLoss"),
        "current2026": selected.get("current2026"),
        "historical2018And2022": selected.get("historical2018And2022"),
    }


def _score_shape_weight(
    home_goals: int,
    away_goals: int,
    profile: str,
    favorite_side: str | None,
) -> float:
    total = home_goals + away_goals
    outcome = _outcome(home_goals, away_goals)

    if profile == "close_late_tail":
        if total == 0:
            return 1.10
        if home_goals == away_goals and total <= 2:
            return 1.01
        if abs(home_goals - away_goals) == 1 and total <= 3:
            return 0.98
        if total >= 5:
            return 1.04
        return 1.0

    if profile == "favorite_tail":
        if favorite_side and outcome == favorite_side:
            favorite_goals = home_goals if favorite_side == "home" else away_goals
            underdog_goals = away_goals if favorite_side == "home" else home_goals
            if favorite_goals - underdog_goals >= 2 and total >= 2:
                return 1.10
            if total >= 4:
                return 1.07
        if total >= 3 and home_goals > 0 and away_goals > 0:
            return 1.08
        if total == 0:
            return 0.88
        return 1.0

    if total >= 4:
        return 1.04
    if home_goals == away_goals and total <= 2:
        return 1.03
    return 1.0


def _profile_for_match(
    base_outcomes: dict[str, float],
    home_xg: float,
    away_xg: float,
    policy: str,
) -> tuple[str, str | None, dict[str, float]]:
    favorite_side = "home" if base_outcomes["home"] >= base_outcomes["away"] else "away"
    favorite_probability = max(base_outcomes["home"], base_outcomes["away"])
    xg_gap = abs(home_xg - away_xg)

    if "tension_close" in policy or favorite_probability < 0.53:
        return "close_late_tail", favorite_side, {
            "0": 1.035,
            "1": 0.975,
            "2": 0.955,
            "3": 1.000,
            "4": 1.045,
            "5": 1.070,
            "6": 1.095,
            "7+": 1.120,
        }

    if favorite_probability >= 0.60 or xg_gap >= 0.55:
        return "favorite_tail", favorite_side, {
            "0": 0.82,
            "1": 0.925,
            "2": 0.995,
            "3": 1.055,
            "4": 1.135,
            "5": 1.220,
            "6": 1.240,
            "7+": 1.220,
        }

    return "balanced_knockout", favorite_side, {
        "0": 0.94,
        "1": 1.00,
        "2": 1.03,
        "3": 1.04,
        "4": 1.04,
        "5": 1.03,
        "6": 1.02,
        "7+": 1.00,
    }


def _preserve_outcomes(
    matrix: list[list[float]],
    target_outcomes: dict[str, float],
) -> list[list[float]]:
    grouped = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for home_goals, row in enumerate(matrix):
        for away_goals, value in enumerate(row):
            grouped[_outcome(home_goals, away_goals)] += value

    scales = {
        outcome: (target_outcomes[outcome] / grouped[outcome] if grouped[outcome] > 0 else 1.0)
        for outcome in grouped
    }
    preserved = [
        [
            value * scales[_outcome(home_goals, away_goals)]
            for away_goals, value in enumerate(row)
        ]
        for home_goals, row in enumerate(matrix)
    ]
    return _normalize(preserved)


def _blend_matrices(
    base: list[list[float]],
    calibrated: list[list[float]],
    intensity: float,
) -> list[list[float]]:
    bounded = min(1.0, max(0.0, intensity))
    blended = [
        [
            (1 - bounded) * base_value + bounded * calibrated[home_goals][away_goals]
            for away_goals, base_value in enumerate(row)
        ]
        for home_goals, row in enumerate(base)
    ]
    return _normalize(blended)


def apply_score_matrix_calibration(
    matrix: list[list[float]],
    seed: dict[str, Any],
    home_xg: float,
    away_xg: float,
    intensity: float | None = None,
) -> ScoreCalibrationResult:
    knockout_context = seed.get("knockout_context") or {}
    tournament_evidence = seed.get("tournament_evidence") or seed.get("tournamentEvidence") or {}
    if not knockout_context and not tournament_evidence:
        return ScoreCalibrationResult(matrix=matrix, metadata={"applied": False, "reason": "no_current_tournament_evidence"})

    sprint_policy = load_final_sprint_policy()["scoreCalibration"]
    selected_intensity = float(sprint_policy["selectedIntensity"] if intensity is None else intensity)
    policy = str(knockout_context.get("policy") or tournament_evidence.get("policy") or "")
    base_outcomes = outcome_probabilities(matrix)
    base_totals = total_goals_probabilities(matrix)
    profile, favorite_side, total_weights = _profile_for_match(base_outcomes, home_xg, away_xg, policy)

    weighted = [
        [
            value
            * total_weights[_goal_bucket(home_goals, away_goals)]
            * _score_shape_weight(home_goals, away_goals, profile, favorite_side)
            for away_goals, value in enumerate(row)
        ]
        for home_goals, row in enumerate(matrix)
    ]
    full_calibrated = _preserve_outcomes(_normalize(weighted), base_outcomes)
    calibrated = matrix if selected_intensity <= 0 else _blend_matrices(matrix, full_calibrated, selected_intensity)
    calibrated_totals = total_goals_probabilities(calibrated)
    full_calibrated_totals = total_goals_probabilities(full_calibrated)
    calibrated_outcomes = outcome_probabilities(calibrated)
    max_cell_delta = max(
        abs(calibrated[home][away] - matrix[home][away])
        for home, row in enumerate(matrix)
        for away, _value in enumerate(row)
    )

    return ScoreCalibrationResult(
        matrix=calibrated,
        metadata={
            "applied": selected_intensity > 0,
            "reason": None if selected_intensity > 0 else str(sprint_policy.get("selectionReason") or "validation_gate_fallback"),
            "policy": "adaptive_score_total_matrix_calibration_v4",
            "profile": profile,
            "candidateProfile": profile,
            "intensity": selected_intensity,
            "candidateIntensities": sprint_policy.get("candidateIntensities", [0.0, 0.1, 0.15, 0.2, 0.25]),
            "validation": _validation_summary(sprint_policy.get("validation"), selected_intensity),
            "sourceKnockoutPolicy": policy,
            "favoriteSide": favorite_side,
            "totalGoalWeights": {key: round(value, 4) for key, value in total_weights.items()},
            "expectedTotalGoalsBefore": round(_expected_total(base_totals), 4),
            "expectedTotalGoalsAfter": round(_expected_total(calibrated_totals), 4),
            "fullIntensityExpectedTotalGoalsAfter": round(_expected_total(full_calibrated_totals), 4),
            "outcomePreserved": _round_probabilities(base_outcomes) == _round_probabilities(calibrated_outcomes),
            "maxCellDelta": round(max_cell_delta, 6),
        },
    )
