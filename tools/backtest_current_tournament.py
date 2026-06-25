from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.goal_models import poisson_negative_binomial_mixture_matrix
from pipeline.market_guard import apply_market_strength_calibration
from pipeline.model import outcome_probabilities, score_matrix, total_goals_probabilities
from pipeline.tournament_form import apply_tournament_form, load_first_round_profiles


BACKTEST_START_DATE = "2026-06-19"
OUT_ARTIFACT = ROOT / "artifacts" / "current-tournament-backtest.json"
OUT_PUBLIC = ROOT / "public" / "data" / "current-tournament-model-review.json"
OUTCOME_LABELS = {"胜": "home", "平": "draw", "负": "away"}
GOAL_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7+"]


def actual_outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def market_odds(match: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for quote in match.get("quotes", []):
        if quote.get("market") != "胜平负":
            continue
        selection = str(quote.get("selection"))
        if selection in OUTCOME_LABELS:
            result[selection] = quote.get("odds")
    return result


def settlement_key(match: dict[str, Any]) -> str:
    direct = str(match.get("id") or "")
    if direct.isdigit():
        return direct
    for quote in match.get("quotes", []):
        quote_match_id = str(quote.get("matchId") or "")
        if quote_match_id.isdigit():
            return quote_match_id
    return direct


def goal_bucket(home_goals: int, away_goals: int) -> str:
    total = home_goals + away_goals
    return "7+" if total >= 7 else str(total)


def total_goal_probabilities_from_quotes(match: dict[str, Any]) -> dict[str, float]:
    return {
        str(quote["selection"]): float(quote["modelProbability"])
        for quote in match.get("quotes", [])
        if quote.get("market") == "总进球数"
    }


def strongest_adjacent(probabilities: dict[str, float]) -> tuple[str, set[str]]:
    best_label = ""
    best_pair: set[str] = set()
    best_probability = -1.0
    for left, right in zip(GOAL_ORDER, GOAL_ORDER[1:]):
        probability = probabilities.get(left, 0.0) + probabilities.get(right, 0.0)
        if probability > best_probability:
            best_label = f"{left}-{right}"
            best_pair = {left, right}
            best_probability = probability
    return best_label, best_pair


def forecast_diagnostics(
    match: dict[str, Any],
    home_goals: int,
    away_goals: int,
) -> dict[str, Any]:
    actual_bucket = goal_bucket(home_goals, away_goals)
    probabilities = total_goal_probabilities_from_quotes(match)
    predicted_bucket = max(probabilities, key=probabilities.get) if probabilities else None
    core_label, core_pair = strongest_adjacent(probabilities)
    expected_total = sum(
        (7 if label == "7+" else int(label)) * probability
        for label, probability in probabilities.items()
    )
    return {
        "likelyScoreHit": match.get("likelyScore") == f"{home_goals}-{away_goals}",
        "actualTotalGoals": home_goals + away_goals,
        "expectedTotalGoals": round(expected_total, 4),
        "totalGoalsAbsoluteError": round(abs(expected_total - home_goals - away_goals), 4),
        "actualTotalBucket": actual_bucket,
        "predictedTotalBucket": predicted_bucket,
        "totalGoalsExactHit": predicted_bucket == actual_bucket,
        "totalGoalsCoreInterval": core_label,
        "totalGoalsCoreHit": actual_bucket in core_pair,
        "actualTotalProbability": round(probabilities.get(actual_bucket, 0.0), 6),
        "totalGoalsLogLoss": -math.log(max(1e-12, probabilities.get(actual_bucket, 0.0))),
    }


def summarize_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["forecastDiagnostics"] for row in rows]
    return {
        "matches": len(values),
        "likelyScoreHits": sum(value["likelyScoreHit"] for value in values),
        "totalGoalsExactHits": sum(value["totalGoalsExactHit"] for value in values),
        "totalGoalsCoreHits": sum(value["totalGoalsCoreHit"] for value in values),
        "averageTotalGoalsAbsoluteError": (
            sum(value["totalGoalsAbsoluteError"] for value in values) / len(values)
        ),
        "averageTotalGoalsLogLoss": (
            sum(value["totalGoalsLogLoss"] for value in values) / len(values)
        ),
    }


def metric_row(probabilities: dict[str, float], actual: str) -> dict[str, Any]:
    prediction = max(probabilities, key=probabilities.get)
    return {
        "prediction": prediction,
        "hit": prediction == actual,
        "logLoss": -math.log(max(1e-12, probabilities[actual])),
        "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
    }


def summarize(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row[key] for row in rows]
    return {
        "matches": len(values),
        "hits": sum(value["hit"] for value in values),
        "accuracy": sum(value["hit"] for value in values) / len(values),
        "averageLogLoss": sum(value["logLoss"] for value in values) / len(values),
    }


def main() -> None:
    profiles = load_first_round_profiles()
    settlement_payload = json.loads(
        (ROOT / "public" / "data" / "settlements.json").read_text(encoding="utf-8")
    )
    settlements = {
        str(item["matchId"]): item
        for item in settlement_payload.get("matches", [])
    }
    archives = sorted((ROOT / "public" / "data" / "history").glob("2026-*.json"))
    backtest_days = tuple(
        path.stem
        for path in archives
        if BACKTEST_START_DATE <= path.stem <= datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    )
    rows: list[dict[str, Any]] = []
    scheduled_by_day: dict[str, int] = {}
    for target_date in backtest_days:
        archive = ROOT / "public" / "data" / "history" / f"{target_date}.json"
        payload = json.loads(archive.read_text(encoding="utf-8"))
        forecast_matches = payload.get("matches", [])
        scheduled_by_day[target_date] = len(forecast_matches)
        day_settlements = sorted(
            (
                item for item in settlements.values()
                if datetime.fromisoformat(str(item["settledAt"]).replace("Z", "+00:00"))
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .date()
                .isoformat() == target_date
            ),
            key=lambda item: str(item["settledAt"]),
        )
        for match_index, match in enumerate(forecast_matches):
            settlement = settlements.get(settlement_key(match))
            if settlement is None and len(day_settlements) == len(forecast_matches):
                settlement = day_settlements[match_index]
            if not settlement:
                continue
            home_goals = int(settlement["homeScore"])
            away_goals = int(settlement["awayScore"])
            actual = actual_outcome(home_goals, away_goals)
            baseline = metric_row(
                {key: float(value) for key, value in match["outcomeProbabilities"].items()},
                actual,
            )

            decomposition = match.get("modelDecomposition", {})
            long_term = decomposition.get("longTermExpectedGoals") or match["expectedGoals"]
            seed = {
                "home_team": match["homeTeam"],
                "away_team": match["awayTeam"],
                "base_xg": [float(long_term["home"]), float(long_term["away"])],
                "model_decomposition": {},
            }
            apply_tournament_form([seed], target_date, profiles)
            calibration = apply_market_strength_calibration(seed, market_odds(match))
            home_xg, away_xg = map(float, seed["base_xg"])
            optimized_probabilities = outcome_probabilities(score_matrix(home_xg, away_xg))
            optimized = metric_row(optimized_probabilities, actual)
            rows.append({
                "targetDate": target_date,
                "match": f"{match['homeTeam']} vs {match['awayTeam']}",
                "score": f"{home_goals}-{away_goals}",
                "actualOutcome": actual,
                "baseline": baseline,
                "optimized": optimized,
                "optimizedExpectedGoals": {
                    "home": round(home_xg, 4),
                    "away": round(away_xg, 4),
                },
                "forecastExpectedGoals": {
                    "home": float(match["expectedGoals"]["home"]),
                    "away": float(match["expectedGoals"]["away"]),
                },
                "forecastDiagnostics": forecast_diagnostics(match, home_goals, away_goals),
                "marketCalibration": calibration,
            })

    baseline_summary = summarize(rows, "baseline")
    optimized_summary = summarize(rows, "optimized")
    by_day = {}
    for target_date in backtest_days:
        day_rows = [row for row in rows if row["targetDate"] == target_date]
        if not day_rows:
            continue
        by_day[target_date] = {
            "scheduledMatches": scheduled_by_day[target_date],
            "settledMatches": len(day_rows),
            "complete": len(day_rows) == scheduled_by_day[target_date],
            "baseline": summarize(day_rows, "baseline"),
            "optimized": summarize(day_rows, "optimized"),
            "forecastDiagnostics": summarize_diagnostics(day_rows),
        }
    poisson_total_loss = 0.0
    tail_total_loss = 0.0
    poisson_outcome_loss = 0.0
    tail_outcome_loss = 0.0
    for row in rows:
        home_xg = float(row["forecastExpectedGoals"]["home"])
        away_xg = float(row["forecastExpectedGoals"]["away"])
        home_goals, away_goals = (int(value) for value in row["score"].split("-"))
        actual = row["actualOutcome"]
        actual_bucket = goal_bucket(home_goals, away_goals)
        poisson_matrix = score_matrix(home_xg, away_xg, rho=0.0)
        tail_matrix = poisson_negative_binomial_mixture_matrix(
            home_xg,
            away_xg,
            dispersion=2.0,
            tail_weight=0.20,
            rho=0.0,
        )
        poisson_outcome = outcome_probabilities(poisson_matrix)
        tail_outcome = outcome_probabilities(tail_matrix)
        poisson_totals = total_goals_probabilities(poisson_matrix)
        tail_totals = total_goals_probabilities(tail_matrix)
        poisson_outcome_loss -= math.log(max(1e-12, poisson_outcome[actual]))
        tail_outcome_loss -= math.log(max(1e-12, tail_outcome[actual]))
        poisson_total_loss -= math.log(max(1e-12, poisson_totals[actual_bucket]))
        tail_total_loss -= math.log(max(1e-12, tail_totals[actual_bucket]))
    total_goals_log_loss_reduction = (poisson_total_loss - tail_total_loss) / len(rows)
    distribution_reason = (
        "loss improvement is small and the settled sample remains below 24 matches"
        if len(rows) < 24
        else "loss improvement is small; keep the heavier-tail distribution in shadow until the gain is material"
    )
    distribution_review = {
        "sampleMatches": len(rows),
        "productionFamily": "poisson",
        "shadowFamily": "poisson_negative_binomial_mixture",
        "shadowParameters": {"dispersion": 2.0, "tailWeight": 0.20},
        "productionAverageOutcomeLogLoss": poisson_outcome_loss / len(rows),
        "shadowAverageOutcomeLogLoss": tail_outcome_loss / len(rows),
        "productionAverageTotalGoalsLogLoss": poisson_total_loss / len(rows),
        "shadowAverageTotalGoalsLogLoss": tail_total_loss / len(rows),
        "totalGoalsLogLossReduction": total_goals_log_loss_reduction,
        "decision": "keep_shadow",
        "reason": distribution_reason,
    }
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "scope": {
            "dates": list(by_day),
            "matches": len(rows),
            "description": "chronological archived forecasts with all currently settled matches",
            "completeDates": [
                target_date for target_date, item in by_day.items() if item["complete"]
            ],
            "partialDates": [
                target_date for target_date, item in by_day.items() if not item["complete"]
            ],
            "motivationLayerEvaluation": "not active before group matchday three",
        },
        "changes": {
            "currentTournamentFormMultiplier": 1.5,
            "agePolicy": "no standalone age penalty; current-tournament results absorb decline without double counting",
            "marketStrengthBlend": 0.35,
            "marketStrengthMaxXgShift": 0.20,
            "marketConflictThreshold": 0.15,
            "motivationPolicy": "matchday_three_bounded_v1",
        },
        "baseline": baseline_summary,
        "optimized": optimized_summary,
        "improvement": {
            "additionalHits": optimized_summary["hits"] - baseline_summary["hits"],
            "accuracyDelta": optimized_summary["accuracy"] - baseline_summary["accuracy"],
            "averageLogLossReduction": (
                baseline_summary["averageLogLoss"] - optimized_summary["averageLogLoss"]
            ),
        },
        "forecastDiagnostics": summarize_diagnostics(rows),
        "distributionReview": distribution_review,
        "byDay": by_day,
        "matches": rows,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    OUT_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    OUT_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    OUT_ARTIFACT.write_text(text, encoding="utf-8")
    OUT_PUBLIC.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
