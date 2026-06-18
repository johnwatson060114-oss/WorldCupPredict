from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from .elo_ratings import allocate_total_goals_by_elo
from .goal_models import ModelSpec, default_candidate_grid, fit_goal_model
from .model import normalized_market_probabilities, outcome_probabilities
from .model import score_matrix


OUTCOMES = ("home", "draw", "away")


def observed_outcome(match: dict[str, Any]) -> str:
    home = int(match["home_goals_90"])
    away = int(match["away_goals_90"])
    return "home" if home > away else "draw" if home == away else "away"


def score_predictions(rows: Iterable[tuple[dict[str, float], str]]) -> dict[str, float]:
    samples = list(rows)
    if not samples:
        return {"log_loss": math.inf, "rps": math.inf, "brier": math.inf, "calibration_error": math.inf}
    log_loss = rps = brier = 0.0
    calibration: dict[tuple[str, int], list[float]] = defaultdict(list)
    for probabilities, actual in samples:
        log_loss -= math.log(max(1e-12, probabilities[actual]))
        actual_vector = [1.0 if outcome == actual else 0.0 for outcome in OUTCOMES]
        predicted_vector = [probabilities[outcome] for outcome in OUTCOMES]
        brier += sum((prediction - observation) ** 2 for prediction, observation in zip(predicted_vector, actual_vector))
        rps += sum(
            (sum(predicted_vector[:index]) - sum(actual_vector[:index])) ** 2
            for index in (1, 2)
        ) / 2
        for outcome in OUTCOMES:
            bucket = min(9, int(probabilities[outcome] * 10))
            calibration[(outcome, bucket)].append(1.0 if outcome == actual else 0.0)

    calibration_error = 0.0
    total_points = len(samples) * len(OUTCOMES)
    for (outcome, bucket), observations in calibration.items():
        predicted = (bucket + 0.5) / 10
        calibration_error += len(observations) / total_points * abs(sum(observations) / len(observations) - predicted)
    count = len(samples)
    return {
        "log_loss": log_loss / count,
        "rps": rps / count,
        "brier": brier / count,
        "calibration_error": calibration_error,
    }


def predict_rows(model: Any, matches: Iterable[dict[str, Any]]) -> list[tuple[dict[str, float], str]]:
    rows = []
    for match in matches:
        matrix = model.matrix(
            str(match["home_team_id"]),
            str(match["away_team_id"]),
            bool(match.get("neutral", True)),
        )
        rows.append((outcome_probabilities(matrix), observed_outcome(match)))
    return rows


def blend_probabilities(statistical: dict[str, float], market: dict[str, float], alpha: float) -> dict[str, float]:
    return {outcome: alpha * statistical[outcome] + (1 - alpha) * market[outcome] for outcome in OUTCOMES}


def learn_blend_alpha(records: Iterable[dict[str, Any]]) -> float:
    samples = list(records)
    if not samples:
        return 1.0
    candidates = [index / 20 for index in range(21)]
    return min(
        candidates,
        key=lambda alpha: score_predictions(
            (blend_probabilities(item["statistical"], item["market"], alpha), item["actual"])
            for item in samples
        )["log_loss"],
    )


def market_probabilities(match: dict[str, Any]) -> dict[str, float] | None:
    odds = match.get("odds") or {}
    normalized = normalized_market_probabilities({outcome: odds.get(outcome) for outcome in OUTCOMES})
    if any(normalized[outcome] is None for outcome in OUTCOMES):
        return None
    return {outcome: float(normalized[outcome]) for outcome in OUTCOMES}


def learn_elo_allocation_weight(
    matches: Iterable[dict[str, Any]],
    validation_years: set[str] | None = None,
    validation_tournament: str = "FIFA World Cup",
    candidates: Iterable[float] | None = None,
    min_history: int = 100,
) -> dict[str, Any]:
    """Learn the Elo share of strength allocation without future leakage."""

    years = validation_years or {"2018", "2022"}
    weights = list(candidates or (0.0, 0.25, 0.50, 0.75, 1.0))
    ordered = sorted(matches, key=lambda item: item["kickoff_utc"])
    ratings: dict[str, float] = {}
    rows_by_weight: dict[float, list[tuple[dict[str, float], str]]] = {weight: [] for weight in weights}
    validation_matches = 0
    spec = ModelSpec("hierarchical_poisson", {"half_life_days": 730.0, "shrinkage": 16.0, "rho": 0.0})

    for index, match in enumerate(ordered):
        home = str(match["home_team_id"])
        away = str(match["away_team_id"])
        home_rating = ratings.get(home, 1500.0)
        away_rating = ratings.get(away, 1500.0)
        year = str(match["kickoff_utc"])[:4]
        is_validation_match = (
            year in years
            and str(match.get("tournament", "")) == validation_tournament
        )
        if index >= min_history and is_validation_match:
            model = fit_goal_model(ordered[:index], spec)
            stat_home, stat_away = model.expected_goals(home, away, bool(match.get("neutral", True)))
            total = stat_home + stat_away
            elo_home, elo_away = allocate_total_goals_by_elo(total, round(home_rating), round(away_rating))
            actual = observed_outcome(match)
            for weight in weights:
                blended_home = (1 - weight) * stat_home + weight * elo_home
                blended_away = (1 - weight) * stat_away + weight * elo_away
                probabilities = outcome_probabilities(score_matrix(blended_home, blended_away))
                rows_by_weight[weight].append((probabilities, actual))
            validation_matches += 1

        expected = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
        home_goals = int(match["home_goals_90"])
        away_goals = int(match["away_goals_90"])
        actual_points = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        change = 20.0 * (actual_points - expected)
        ratings[home] = home_rating + change
        ratings[away] = away_rating - change

    metrics = {str(weight): score_predictions(rows) for weight, rows in rows_by_weight.items()}
    selected = min(
        weights,
        key=lambda weight: (metrics[str(weight)]["log_loss"], metrics[str(weight)]["rps"]),
    ) if validation_matches else 1.0
    return {
        "eloAllocationWeight": selected,
        "validationYears": sorted(years),
        "validationTournament": validation_tournament,
        "validationMatches": validation_matches,
        "candidates": metrics,
        "selectionRule": "lowest chronological validation log loss; tie-break by RPS",
        "excludedYears": ["2026"],
    }


def rolling_backtest(
    matches: Iterable[dict[str, Any]],
    candidates: Iterable[ModelSpec] | None = None,
    min_train: int = 24,
    validation_size: int = 8,
    test_size: int = 8,
) -> dict[str, Any]:
    ordered = sorted(matches, key=lambda item: item["kickoff_utc"])
    candidate_grid = list(candidates or default_candidate_grid())
    by_family: dict[str, list[ModelSpec]] = defaultdict(list)
    for spec in candidate_grid:
        by_family[spec.family].append(spec)
    baseline_spec = ModelSpec("legacy", {})
    baseline_rows: list[tuple[dict[str, float], str]] = []
    candidate_rows: dict[str, list[tuple[dict[str, float], str]]] = defaultdict(list)
    chosen_specs: dict[str, list[str]] = defaultdict(list)
    folds = []

    test_start = min_train + validation_size
    while test_start + test_size <= len(ordered):
        inner_train = ordered[:test_start - validation_size]
        validation = ordered[test_start - validation_size:test_start]
        final_train = ordered[:test_start]
        test = ordered[test_start:test_start + test_size]
        baseline = fit_goal_model(final_train, baseline_spec)
        baseline_rows.extend(predict_rows(baseline, test))

        for family, specs in by_family.items():
            selected = min(
                specs,
                key=lambda spec: (
                    score_predictions(predict_rows(fit_goal_model(inner_train, spec), validation))["log_loss"],
                    score_predictions(predict_rows(fit_goal_model(inner_train, spec), validation))["rps"],
                ),
            )
            chosen_specs[family].append(selected.key)
            candidate_rows[family].extend(predict_rows(fit_goal_model(final_train, selected), test))

        folds.append({
            "train_end": inner_train[-1]["kickoff_utc"],
            "validation_end": validation[-1]["kickoff_utc"],
            "test_end": test[-1]["kickoff_utc"],
            "test_matches": len(test),
        })
        test_start += test_size

    if not folds:
        raise ValueError("not enough chronological matches for nested rolling backtest")

    baseline_metrics = score_predictions(baseline_rows)
    results = {
        family: {**score_predictions(rows), "chosen_specs": chosen_specs[family]}
        for family, rows in candidate_rows.items()
    }
    best_family = min(results, key=lambda family: (results[family]["log_loss"], results[family]["rps"]))
    best = results[best_family]
    promote = best["log_loss"] < baseline_metrics["log_loss"] and best["rps"] <= baseline_metrics["rps"]
    return {
        "baseline": {"family": baseline_spec.family, **baseline_metrics},
        "candidates": results,
        "selected_model": best_family if promote else baseline_spec.family,
        "promote": promote,
        "folds": folds,
        "test_matches": len(baseline_rows),
    }
