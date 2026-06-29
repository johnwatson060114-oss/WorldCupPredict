from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.backtest import observed_outcome, score_predictions
from pipeline.elo_ratings import allocate_total_goals_by_elo
from pipeline.goal_models import PRODUCTION_GOAL_SPEC, _read_historical_matches, fit_goal_model
from pipeline.group_stage_form import apply_group_stage_form, load_group_stage_profiles
from pipeline.knockout_context import knockout_adjust_xg
from pipeline.market_guard import apply_market_strength_calibration
from pipeline.model import outcome_probabilities, score_matrix, total_goals_probabilities


BEIJING = ZoneInfo("Asia/Shanghai")
OUT_HISTORICAL = ROOT / "artifacts" / "model-comparison-2018-2022.json"
OUT_2026 = ROOT / "artifacts" / "model-comparison-2026-group-stage.json"
OUTCOME_LABELS = {"鑳?": "home", "骞?": "draw", "璐?": "away"}
OUTCOME_LABELS = {"\u80dc": "home", "\u5e73": "draw", "\u8d1f": "away"}
HISTORICAL_GROUP_PROFILE_PATH = ROOT / "pipeline" / "data" / "historical-group-stage-performance-statsbomb.json"
GOAL_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7+"]
MODELS = ("current_production", "candidate_knockout_ready", "no_tournament_form")


def actual_outcome_from_goals(home: int, away: int) -> str:
    return "home" if home > away else "away" if away > home else "draw"


def goal_bucket(home_goals: int, away_goals: int) -> str:
    total = home_goals + away_goals
    return "7+" if total >= 7 else str(total)


def strongest_adjacent(probabilities: dict[str, float]) -> tuple[str, set[str]]:
    best_label = ""
    best_pair: set[str] = set()
    best_probability = -1.0
    for left, right in zip(GOAL_ORDER, GOAL_ORDER[1:], strict=False):
        probability = probabilities.get(left, 0.0) + probabilities.get(right, 0.0)
        if probability > best_probability:
            best_probability = probability
            best_label = f"{left}-{right}"
            best_pair = {left, right}
    return best_label, best_pair


def metric_row(probabilities: dict[str, float], actual: str, xg: tuple[float, float], score: tuple[int, int]) -> dict[str, Any]:
    total_probabilities = total_goals_probabilities(score_matrix(xg[0], xg[1]))
    actual_bucket = goal_bucket(score[0], score[1])
    predicted_bucket = max(total_probabilities, key=total_probabilities.get)
    core_label, core_pair = strongest_adjacent(total_probabilities)
    prediction = max(probabilities, key=probabilities.get)
    return {
        "prediction": prediction,
        "hit": prediction == actual,
        "probabilities": {key: round(float(value), 8) for key, value in probabilities.items()},
        "xg": {"home": round(float(xg[0]), 4), "away": round(float(xg[1]), 4)},
        "totalGoals": {
            "actualBucket": actual_bucket,
            "predictedBucket": predicted_bucket,
            "exactHit": predicted_bucket == actual_bucket,
            "adjacentCore": core_label,
            "adjacentCoreHit": actual_bucket in core_pair,
        },
    }


def summarize_rows(rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    if not rows:
        return {
            "matches": 0,
            "hits": 0,
            "accuracy": 0.0,
            "logLoss": math.inf,
            "rps": math.inf,
            "brier": math.inf,
            "calibrationError": math.inf,
            "totalGoalsExactBucketAccuracy": 0.0,
            "totalGoalsAdjacentCoreAccuracy": 0.0,
        }
    samples = [(row["models"][model]["probabilities"], row["actual"]) for row in rows]
    scored = score_predictions(samples)
    hits = sum(row["models"][model]["hit"] for row in rows)
    total_exact = sum(row["models"][model]["totalGoals"]["exactHit"] for row in rows)
    total_core = sum(row["models"][model]["totalGoals"]["adjacentCoreHit"] for row in rows)
    count = len(rows)
    return {
        "matches": count,
        "hits": hits,
        "accuracy": hits / count,
        "logLoss": scored["log_loss"],
        "rps": scored["rps"],
        "brier": scored["brier"],
        "calibrationError": scored["calibration_error"],
        "totalGoalsExactBucketAccuracy": total_exact / count,
        "totalGoalsAdjacentCoreAccuracy": total_core / count,
    }


def summarize_grouped(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return {
        group: {model: summarize_rows(group_rows, model) for model in MODELS}
        for group, group_rows in sorted(grouped.items())
    }


def summary_table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": {model: summarize_rows(rows, model) for model in MODELS},
        "byYear": summarize_grouped(rows, "year"),
        "byStage": summarize_grouped(rows, "stage"),
        "byStrengthTier": summarize_grouped(rows, "strengthTier"),
    }


def load_historical_group_stage_profiles(
    path: Path = HISTORICAL_GROUP_PROFILE_PATH,
) -> dict[str, dict[str, dict[str, Any]]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_year: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for profile in payload.get("teams", []):
        year = str(profile.get("year") or profile.get("sourceYear") or "")
        team = str(profile.get("team") or "").strip()
        if year and team:
            by_year[year][team] = profile
    return dict(by_year)


def chronological_elo_backtest_rows(matches: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(matches, key=lambda item: item["kickoff_utc"])
    historical_group_profiles = load_historical_group_stage_profiles()
    world_cup_by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in ordered:
        year = str(match["date"])[:4]
        if match.get("tournament") == "FIFA World Cup" and year in {"2018", "2022"}:
            world_cup_by_year[year].append(match)
    stage_by_identity: dict[tuple[str, str, str, str], str] = {}
    for year, year_matches in world_cup_by_year.items():
        for index, match in enumerate(sorted(year_matches, key=lambda item: item["kickoff_utc"])):
            key = (year, str(match["date"]), str(match["home_team"]), str(match["away_team"]))
            stage_by_identity[key] = "group" if index < 48 else "knockout"

    ratings: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(ordered):
        home = str(match["home_team_id"])
        away = str(match["away_team_id"])
        home_rating = ratings.get(home, 1500.0)
        away_rating = ratings.get(away, 1500.0)
        year = str(match["date"])[:4]
        is_validation = match.get("tournament") == "FIFA World Cup" and year in {"2018", "2022"}
        if is_validation:
            stage = stage_by_identity[(year, str(match["date"]), str(match["home_team"]), str(match["away_team"]))]
            prior = [
                row for row in ordered[:index]
                if int(str(row["date"])[:4]) >= 2000
            ]
            model = fit_goal_model(prior, PRODUCTION_GOAL_SPEC)
            base_home, base_away = model.expected_goals(home, away, bool(match.get("neutral", True)))
            total = base_home + base_away
            elo_home, elo_away = allocate_total_goals_by_elo(total, round(home_rating), round(away_rating))
            current_xg = (elo_home, elo_away)
            candidate_xg = current_xg
            year_profiles = historical_group_profiles.get(year, {})
            if year_profiles:
                seed = {
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "base_xg": [candidate_xg[0], candidate_xg[1]],
                    "model_decomposition": {},
                    "coverage": 0.95,
                    "stage": "GROUP_STAGE" if stage == "group" else "KNOCKOUT",
                    "group": "HISTORICAL_GROUP_STAGE_ARCHIVE",
                }
                apply_group_stage_form([seed], str(match["date"]), year_profiles)
                candidate_xg = (float(seed["base_xg"][0]), float(seed["base_xg"][1]))
            if stage == "knockout":
                adjusted = knockout_adjust_xg(*candidate_xg)
                candidate_xg = (adjusted.home_xg, adjusted.away_xg)
            no_form_xg = (base_home, base_away)
            actual = observed_outcome(match)
            score = (int(match["home_goals_90"]), int(match["away_goals_90"]))
            current_prob = outcome_probabilities(score_matrix(*current_xg, rho=0.0))
            candidate_prob = outcome_probabilities(score_matrix(*candidate_xg, rho=0.0))
            no_form_prob = outcome_probabilities(score_matrix(*no_form_xg, rho=0.0))
            strength_probability = max(current_prob["home"], current_prob["away"])
            strength_tier = (
                "strong_favorite"
                if strength_probability >= 0.60 or abs(current_xg[0] - current_xg[1]) >= 0.55
                else "balanced_or_close"
            )
            rows.append({
                "date": match["date"],
                "year": year,
                "stage": stage,
                "strengthTier": strength_tier,
                "match": f"{match['home_team']} vs {match['away_team']}",
                "score": f"{score[0]}-{score[1]}",
                "actual": actual,
                "models": {
                    "current_production": metric_row(current_prob, actual, current_xg, score),
                    "candidate_knockout_ready": metric_row(candidate_prob, actual, candidate_xg, score),
                    "no_tournament_form": metric_row(no_form_prob, actual, no_form_xg, score),
                },
            })

        expected = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
        home_goals = int(match["home_goals_90"])
        away_goals = int(match["away_goals_90"])
        actual_points = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        change = 20.0 * (actual_points - expected)
        ratings[home] = home_rating + change
        ratings[away] = away_rating - change
    return rows


def market_odds(match: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for quote in match.get("quotes", []):
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


def load_settlements() -> dict[str, dict[str, Any]]:
    payload = json.loads((ROOT / "public" / "data" / "settlements.json").read_text(encoding="utf-8"))
    return {str(item["matchId"]): item for item in payload.get("matches", [])}


def settled_rows_2026() -> list[dict[str, Any]]:
    profiles = load_group_stage_profiles()
    settlements = load_settlements()
    rows: list[dict[str, Any]] = []
    archives = sorted((ROOT / "public" / "data" / "history").glob("2026-*.json"))
    for archive in archives:
        payload = json.loads(archive.read_text(encoding="utf-8"))
        target_date = str(payload.get("targetDate") or archive.stem)
        day_settlements = sorted(
            (
                item for item in settlements.values()
                if datetime.fromisoformat(str(item["settledAt"]).replace("Z", "+00:00"))
                .astimezone(BEIJING).date().isoformat() == target_date
            ),
            key=lambda item: str(item["settledAt"]),
        )
        forecast_matches = payload.get("matches", [])
        for match_index, match in enumerate(forecast_matches):
            settlement = settlements.get(settlement_key(match))
            if settlement is None and len(day_settlements) == len(forecast_matches):
                settlement = day_settlements[match_index]
            if not settlement:
                continue
            home_goals = int(settlement["homeScore"])
            away_goals = int(settlement["awayScore"])
            actual = actual_outcome_from_goals(home_goals, away_goals)
            score = (home_goals, away_goals)
            current_prob = {key: float(value) for key, value in match["outcomeProbabilities"].items()}
            current_xg = (
                float(match["expectedGoals"]["home"]),
                float(match["expectedGoals"]["away"]),
            )

            decomposition = match.get("modelDecomposition", {})
            long_term = decomposition.get("longTermExpectedGoals") or match["expectedGoals"]
            no_form_xg = (float(long_term["home"]), float(long_term["away"]))
            no_form_prob = outcome_probabilities(score_matrix(*no_form_xg))

            is_group_stage_sample = bool(settlement.get("group")) or target_date <= "2026-06-28"
            seed = {
                "home_team": match["homeTeam"],
                "away_team": match["awayTeam"],
                "base_xg": [no_form_xg[0], no_form_xg[1]],
                "model_decomposition": {},
                "coverage": float(match.get("coverage", 0.70)),
                "stage": None if is_group_stage_sample else "ROUND_OF_32",
                "group": settlement.get("group") or ("GROUP_STAGE_ARCHIVE" if is_group_stage_sample else None),
            }
            if profiles:
                apply_group_stage_form([seed], target_date, profiles)
            apply_market_strength_calibration(seed, market_odds(match))
            if not is_group_stage_sample:
                adjusted = knockout_adjust_xg(float(seed["base_xg"][0]), float(seed["base_xg"][1]))
                seed["base_xg"] = [adjusted.home_xg, adjusted.away_xg]
            candidate_xg = (float(seed["base_xg"][0]), float(seed["base_xg"][1]))
            candidate_prob = outcome_probabilities(score_matrix(*candidate_xg))
            strength_probability = max(current_prob["home"], current_prob["away"])
            strength_tier = (
                "strong_favorite"
                if strength_probability >= 0.60 or abs(current_xg[0] - current_xg[1]) >= 0.55
                else "balanced_or_close"
            )
            rows.append({
                "date": target_date,
                "year": "2026",
                "stage": "group" if is_group_stage_sample else "knockout",
                "strengthTier": strength_tier,
                "match": f"{match['homeTeam']} vs {match['awayTeam']}",
                "score": f"{home_goals}-{away_goals}",
                "actual": actual,
                "models": {
                    "current_production": metric_row(current_prob, actual, current_xg, score),
                    "candidate_knockout_ready": metric_row(candidate_prob, actual, candidate_xg, score),
                    "no_tournament_form": metric_row(no_form_prob, actual, no_form_xg, score),
                },
            })
    return rows


def adoption_decision(historical_summary: dict[str, Any]) -> dict[str, Any]:
    current = historical_summary["overall"]["current_production"]
    candidate = historical_summary["overall"]["candidate_knockout_ready"]
    accuracy_gate = candidate["accuracy"] >= current["accuracy"] - 1e-12
    log_loss_improves = candidate["logLoss"] < current["logLoss"] - 1e-9
    rps_improves = candidate["rps"] < current["rps"] - 1e-9
    log_loss_not_worse = candidate["logLoss"] <= current["logLoss"] + 0.010
    rps_not_worse = candidate["rps"] <= current["rps"] + 0.010
    adopt = accuracy_gate and ((log_loss_improves and rps_not_worse) or (rps_improves and log_loss_not_worse))
    return {
        "selectedModel": "candidate_knockout_ready" if adopt else "current_production",
        "adoptCandidate": adopt,
        "gates": {
            "accuracyNotLowerOn2018And2022": accuracy_gate,
            "logLossImproves": log_loss_improves,
            "rpsImproves": rps_improves,
            "logLossNotClearlyWorse": log_loss_not_worse,
            "rpsNotClearlyWorse": rps_not_worse,
        },
        "rule": (
            "Candidate must not lower 2018+2022 WDL accuracy; either log loss or RPS must improve, "
            "and the other metric cannot worsen by more than 0.010."
        ),
        "note": (
            "2018/2022 replay a reproducible StatsBomb Open Data event-xG group-stage layer; "
            "only matches before the forecast date are visible, and penalties, red cards and own goals reduce credibility."
        ),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact_print(label: str, summary: dict[str, Any]) -> None:
    print(label)
    print("model,matches,accuracy,logLoss,rps,brier,calibrationError,totalExact,totalAdjacent")
    for model in MODELS:
        item = summary["overall"][model]
        print(
            f"{model},{item['matches']},{item['accuracy']:.4f},{item['logLoss']:.4f},"
            f"{item['rps']:.4f},{item['brier']:.4f},{item['calibrationError']:.4f},"
            f"{item['totalGoalsExactBucketAccuracy']:.4f},{item['totalGoalsAdjacentCoreAccuracy']:.4f}"
        )


def main() -> None:
    generated_at = datetime.now(BEIJING).isoformat(timespec="seconds")
    historical_rows = chronological_elo_backtest_rows(_read_historical_matches())
    historical_summary = summary_table(historical_rows)
    decision = adoption_decision(historical_summary)
    historical_report = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {
            "tournament": "FIFA World Cup",
            "years": [2018, 2022],
            "matches": len(historical_rows),
            "predictionTarget": "90_minutes",
            "chronologicalPolicy": "fit and update only with matches before the target row",
        },
        "models": {
            "current_production": "hierarchical_poisson + chronological Elo allocation; market calibration unavailable historically",
            "candidate_knockout_ready": "current_production + StatsBomb event-gated group-stage state when available + conservative knockout 90-minute context",
            "no_tournament_form": "hierarchical_poisson long-term goal model without tournament-state or Elo allocation",
        },
        "metrics": historical_summary,
        "adoptionDecision": decision,
        "matches": historical_rows,
    }
    write_json(OUT_HISTORICAL, historical_report)

    current_rows = settled_rows_2026()
    current_summary = summary_table(current_rows)
    current_report = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {
            "tournament": "FIFA World Cup 2026",
            "matches": len(current_rows),
            "predictionTarget": "90_minutes",
            "policy": "rolling archived forecasts joined to settled local results",
            "historicalAdoptionDecision": decision["selectedModel"],
        },
        "models": {
            "current_production": "archived public/data/history outcomeProbabilities",
            "candidate_knockout_ready": "long-term xG replayed through group-stage commentary gate, market strength calibration, and knockout context when applicable",
            "no_tournament_form": "archived longTermExpectedGoals without tournament-state replay",
        },
        "metrics": current_summary,
        "matches": current_rows,
    }
    write_json(OUT_2026, current_report)
    compact_print("2018+2022", historical_summary)
    compact_print("2026 settled sample", current_summary)
    print(f"adoption={decision['selectedModel']}")


if __name__ == "__main__":
    main()
