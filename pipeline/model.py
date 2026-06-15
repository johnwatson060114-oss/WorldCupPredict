from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ModelEstimate:
    home_xg: float
    away_xg: float
    matrix: list[list[float]]


def poisson_probability(goals: int, expected: float) -> float:
    return math.exp(-expected) * expected**goals / math.factorial(goals)


def dixon_coles_tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def score_matrix(home_xg: float, away_xg: float, max_goals: int = 10, rho: float = -0.08) -> list[list[float]]:
    matrix = []
    for home_goals in range(max_goals + 1):
        row = []
        for away_goals in range(max_goals + 1):
            value = (
                poisson_probability(home_goals, home_xg)
                * poisson_probability(away_goals, away_xg)
                * dixon_coles_tau(home_goals, away_goals, home_xg, away_xg, rho)
            )
            row.append(max(0.0, value))
        matrix.append(row)
    total = sum(sum(row) for row in matrix)
    return [[value / total for value in row] for row in matrix]


def outcome_probabilities(matrix: list[list[float]], handicap: int = 0) -> dict[str, float]:
    result = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            adjusted_home = home_goals + handicap
            if adjusted_home > away_goals:
                result["home"] += probability
            elif adjusted_home == away_goals:
                result["draw"] += probability
            else:
                result["away"] += probability
    return result


def total_goals_probabilities(matrix: list[list[float]]) -> dict[str, float]:
    result = {str(goals): 0.0 for goals in range(7)} | {"7+": 0.0}
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            total = home_goals + away_goals
            result["7+" if total >= 7 else str(total)] += probability
    return result


def half_full_probabilities(home_xg: float, away_xg: float) -> dict[str, float]:
    first_half = score_matrix(home_xg * 0.45, away_xg * 0.45, max_goals=7, rho=-0.04)
    second_half = score_matrix(home_xg * 0.55, away_xg * 0.55, max_goals=8, rho=-0.04)
    labels = {"home": "胜", "draw": "平", "away": "负"}
    result = {f"{first}{full}": 0.0 for first in labels.values() for full in labels.values()}

    def outcome(home: int, away: int) -> str:
        return "home" if home > away else "draw" if home == away else "away"

    for first_home, row in enumerate(first_half):
        for first_away, first_probability in enumerate(row):
            first_label = labels[outcome(first_home, first_away)]
            for second_home, second_row in enumerate(second_half):
                for second_away, second_probability in enumerate(second_row):
                    full_label = labels[outcome(first_home + second_home, first_away + second_away)]
                    result[f"{first_label}{full_label}"] += first_probability * second_probability
    return result


def top_scores(matrix: list[list[float]], limit: int = 8) -> list[dict[str, float | str]]:
    values = [
        {"score": f"{home}:{away}", "probability": probability}
        for home, row in enumerate(matrix)
        for away, probability in enumerate(row)
    ]
    return sorted(values, key=lambda item: float(item["probability"]), reverse=True)[:limit]


def score_stars(top_probability: float, coverage: float, bootstrap_top_share: float = 0.8) -> int:
    if top_probability >= 0.18 and coverage >= 0.90 and bootstrap_top_share >= 0.8:
        return 3
    if top_probability >= 0.15 and coverage >= 0.85:
        return 2
    if top_probability >= 0.12:
        return 1
    return 0


def normalized_market_probabilities(odds: dict[str, float | None]) -> dict[str, float | None]:
    valid = {key: value for key, value in odds.items() if value and value > 1}
    if len(valid) != len(odds):
        return {key: None for key in odds}
    implied = {key: 1 / value for key, value in valid.items()}
    margin = sum(implied.values())
    return {key: value / margin for key, value in implied.items()}


def probability_lower_bound(probability: float, coverage: float, sample_scale: int = 250) -> float:
    effective_n = max(20, sample_scale * coverage)
    standard_error = math.sqrt(max(0.000001, probability * (1 - probability) / effective_n))
    data_penalty = (1 - coverage) * 0.08
    return max(0.0, probability - 1.28 * standard_error - data_penalty)


def expected_return(probability: float, odds: float) -> float:
    return probability * odds - 1


def adjust_xg(
    base_home: float,
    base_away: float,
    factors: Iterable[dict[str, float | str | bool]],
) -> tuple[float, float]:
    home, away = base_home, base_away
    for factor in factors:
        if not factor.get("active", False) or factor.get("admissionStatus") not in {"core", "enabled"}:
            continue
        value = float(factor.get("value", 0.0))
        direction = factor.get("direction")
        if direction == "home":
            home += abs(value)
            away -= abs(value) * 0.25
        elif direction == "away":
            away += abs(value)
            home -= abs(value) * 0.25
    return max(0.15, home), max(0.15, away)


def estimate_from_recent_results(
    home_results: list[dict],
    away_results: list[dict],
    home_team_id: int | None = None,
    away_team_id: int | None = None,
) -> tuple[float, float]:
    def weighted_rates(results: list[dict], team_id: int | None) -> tuple[float, float]:
        scored_total = conceded_total = weight_total = 0.0
        for index, fixture in enumerate(results[:20]):
            goals = fixture.get("goals", {})
            teams = fixture.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            if team_id is None:
                is_home_team = index % 2 == 0
            elif home.get("id") == team_id:
                is_home_team = True
            elif away.get("id") == team_id:
                is_home_team = False
            else:
                continue
            scored = goals.get("home") if is_home_team else goals.get("away")
            conceded = goals.get("away") if is_home_team else goals.get("home")
            if scored is None or conceded is None:
                continue
            weight = math.exp(-index / 8)
            scored_total += float(scored) * weight
            conceded_total += float(conceded) * weight
            weight_total += weight
        if not weight_total:
            return 1.25, 1.25
        return scored_total / weight_total, conceded_total / weight_total

    home_scored, home_conceded = weighted_rates(home_results, home_team_id)
    away_scored, away_conceded = weighted_rates(away_results, away_team_id)
    return (
        max(0.2, 0.55 * home_scored + 0.45 * away_conceded + 0.08),
        max(0.2, 0.55 * away_scored + 0.45 * home_conceded),
    )
