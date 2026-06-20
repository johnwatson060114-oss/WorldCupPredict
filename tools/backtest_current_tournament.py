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

from pipeline.football_data import FootballDataClient, localized_team_name
from pipeline.market_guard import apply_market_strength_calibration
from pipeline.model import outcome_probabilities, score_matrix
from pipeline.tournament_form import apply_tournament_form, load_first_round_profiles


BACKTEST_DAYS = ("2026-06-19", "2026-06-20")
OUT_ARTIFACT = ROOT / "artifacts" / "current-tournament-backtest.json"
OUT_PUBLIC = ROOT / "public" / "data" / "current-tournament-model-review.json"
OUTCOME_LABELS = {"胜": "home", "平": "draw", "负": "away"}


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
    fixtures = FootballDataClient().world_cup_matches()
    finished = {
        (localized_team_name(item["homeTeam"]), localized_team_name(item["awayTeam"])): item
        for item in fixtures
        if item.get("status") == "FINISHED"
    }
    rows: list[dict[str, Any]] = []
    for target_date in BACKTEST_DAYS:
        archive = ROOT / "public" / "data" / "history" / f"{target_date}.json"
        payload = json.loads(archive.read_text(encoding="utf-8"))
        for match in payload.get("matches", []):
            fixture = finished.get((match["homeTeam"], match["awayTeam"]))
            if not fixture:
                continue
            home_goals = int(fixture["score"]["fullTime"]["home"])
            away_goals = int(fixture["score"]["fullTime"]["away"])
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
                "marketCalibration": calibration,
            })

    baseline_summary = summarize(rows, "baseline")
    optimized_summary = summarize(rows, "optimized")
    by_day = {}
    for target_date in BACKTEST_DAYS:
        day_rows = [row for row in rows if row["targetDate"] == target_date]
        by_day[target_date] = {
            "baseline": summarize(day_rows, "baseline"),
            "optimized": summarize(day_rows, "optimized"),
        }
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "scope": {
            "dates": list(BACKTEST_DAYS),
            "matches": len(rows),
            "description": "first completed second-round sample; chronological archived forecasts",
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
