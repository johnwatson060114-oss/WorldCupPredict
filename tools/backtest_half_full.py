from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.model import (  # noqa: E402
    half_full_probabilities as structural_half_full_probabilities,
    outcome_probabilities,
    score_matrix,
)
from pipeline.half_full_specialist import apply_half_full_market_calibration  # noqa: E402


BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_HISTORY_DIR = ROOT / "public" / "data" / "history"
DEFAULT_SETTLEMENTS_PATH = ROOT / "public" / "data" / "settlements.json"
DEFAULT_OUTPUT_PATH = ROOT / "artifacts" / "half-full-backtest-2026.json"
DEFAULT_SCORE_MATRIX_BACKTEST_PATH = ROOT / "artifacts" / "score-matrix-backtest-2026.json"
HALF_FULL_MARKET = "\u534a\u5168\u573a"
FORECAST_SECTIONS = ("matches", "parlayMatches", "parlayCandidateMatches")
OUTCOME_LABELS = {"home": "\u80dc", "draw": "\u5e73", "away": "\u8d1f"}
SELECTIONS = [
    "\u80dc\u80dc",
    "\u80dc\u5e73",
    "\u80dc\u8d1f",
    "\u5e73\u80dc",
    "\u5e73\u5e73",
    "\u5e73\u8d1f",
    "\u8d1f\u80dc",
    "\u8d1f\u5e73",
    "\u8d1f\u8d1f",
]
OUTCOME_KEYS = ("home", "draw", "away")
GROUP_OUTCOME_ASSIST_WEIGHT = 0.20
KNOCKOUT_OUTCOME_ASSIST_WEIGHT = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest half-time/full-time predictions from archived forecasts."
    )
    parser.add_argument("--history-dir", type=Path, default=DEFAULT_HISTORY_DIR)
    parser.add_argument("--settlements", type=Path, default=DEFAULT_SETTLEMENTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def outcome_label(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return OUTCOME_LABELS["home"]
    if home_goals < away_goals:
        return OUTCOME_LABELS["away"]
    return OUTCOME_LABELS["draw"]


def actual_half_full(settlement: dict[str, Any]) -> str | None:
    half_home = settlement.get("halfTimeHomeScore")
    half_away = settlement.get("halfTimeAwayScore")
    if half_home is None or half_away is None:
        return None
    return (
        outcome_label(int(half_home), int(half_away))
        + outcome_label(int(settlement["homeScore"]), int(settlement["awayScore"]))
    )


def settlement_key(match: dict[str, Any]) -> str:
    direct = str(match.get("id") or "")
    if direct.isdigit():
        return direct
    for quote in match.get("quotes", []):
        quote_match_id = str(quote.get("matchId") or "")
        if quote_match_id.isdigit():
            return quote_match_id
    return direct


def half_full_probabilities(match: dict[str, Any]) -> dict[str, float]:
    probabilities: dict[str, float] = {}
    for quote in match.get("quotes", []):
        if quote.get("market") != HALF_FULL_MARKET:
            continue
        selection = str(quote.get("selection") or "")
        if selection not in SELECTIONS:
            continue
        probability = quote.get("modelProbability")
        if probability is None:
            continue
        probabilities[selection] = float(probability)

    total = sum(probabilities.values())
    if total <= 0:
        return {}
    return {selection: probabilities.get(selection, 0.0) / total for selection in SELECTIONS}


def load_settlements(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["matchId"]): item for item in payload.get("matches", [])}


def _settlement_priority(match_id: str, settlement: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(str(settlement.get("settlementScoreBasis") or "").lower() == "90_minutes"),
        int(settlement.get("halfTimeHomeScore") is not None and settlement.get("halfTimeAwayScore") is not None),
        int(bool(settlement.get("settlementSourceUrl") or settlement.get("settlementSource"))),
        int(match_id.isdigit()),
    )


def archived_forecasts(
    history_dir: Path,
    settlements: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    forecasts_by_fixture: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in sorted(history_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = parse_datetime(payload.get("generatedAt"))
        for section in FORECAST_SECTIONS:
            for match in payload.get(section, []):
                match_id = settlement_key(match)
                if match_id not in settlements:
                    continue
                if not half_full_probabilities(match):
                    continue

                kickoff = parse_datetime(match.get("kickoff") or match.get("kickoffBeijing"))
                if generated_at is None or kickoff is None or generated_at >= kickoff:
                    continue

                home_team = " ".join(str(match.get("homeTeam") or "").casefold().split())
                away_team = " ".join(str(match.get("awayTeam") or "").casefold().split())
                fixture_key = (
                    kickoff.astimezone(timezone.utc).isoformat(),
                    home_team,
                    away_team,
                )
                previous = forecasts_by_fixture.get(fixture_key)
                previous_generated = parse_datetime(previous["historyGeneratedAt"]) if previous else None
                candidate_ids = set(previous.get("settlementCandidateIds", [])) if previous else set()
                candidate_ids.add(match_id)
                if previous is None or (
                    generated_at and previous_generated and generated_at > previous_generated
                ):
                    forecasts_by_fixture[fixture_key] = {
                        "matchId": match_id,
                        "historyPath": display_path(path),
                        "historySection": section,
                        "historyGeneratedAt": payload.get("generatedAt"),
                        "match": match,
                        "settlementCandidateIds": sorted(candidate_ids),
                    }
                else:
                    previous["settlementCandidateIds"] = sorted(candidate_ids)

    for forecast in forecasts_by_fixture.values():
        candidate_ids = forecast.pop("settlementCandidateIds", [forecast["matchId"]])
        forecast["settlementMatchId"] = max(
            candidate_ids,
            key=lambda candidate_id: _settlement_priority(candidate_id, settlements[candidate_id]),
        )
    return {
        str(forecast["matchId"]): {
            key: value for key, value in forecast.items() if key != "matchId"
        }
        for forecast in forecasts_by_fixture.values()
    }


def supplemental_score_matrix_forecasts(
    path: Path,
    settlements: dict[str, dict[str, Any]],
    existing_forecasts: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    supplemental: dict[str, dict[str, Any]] = {}
    try:
        artifact_path = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        artifact_path = str(path)
    for section in ("latestMatches", "knockoutMatches", "matches"):
        for row in payload.get(section, []):
            match_id = str(row.get("matchId") or "")
            if not match_id or match_id in existing_forecasts or match_id in supplemental:
                continue
            if match_id not in settlements or actual_half_full(settlements[match_id]) is None:
                continue

            xg = row.get("xg") or {}
            if xg.get("home") is None or xg.get("away") is None:
                continue
            home_xg = float(xg["home"])
            away_xg = float(xg["away"])
            half_full = structural_half_full_probabilities(home_xg, away_xg)
            outcomes = outcome_probabilities(score_matrix(home_xg, away_xg))
            quotes = [
                {
                    "market": HALF_FULL_MARKET,
                    "selection": selection,
                    "modelProbability": probability,
                    "matchId": match_id,
                }
                for selection, probability in half_full.items()
            ]

            supplemental[match_id] = {
                "historyPath": row.get("historyPath") or artifact_path,
                "historyGeneratedAt": row.get("historyGeneratedAt"),
                "match": {
                    "id": match_id,
                    "homeTeam": row.get("homeTeam"),
                    "awayTeam": row.get("awayTeam"),
                    "kickoff": row.get("kickoff"),
                    "knockoutContext": {"reconstructed": True} if row.get("stage") == "knockout" else None,
                    "outcomeProbabilities": outcomes,
                    "quotes": quotes,
                    "halfFullSource": "reconstructed_from_archived_xg",
                },
            }
    return supplemental


def multiclass_brier(probabilities: dict[str, float], actual: str) -> float:
    return sum((probabilities.get(selection, 0.0) - (1.0 if selection == actual else 0.0)) ** 2 for selection in SELECTIONS)


def actual_outcome(settlement: dict[str, Any]) -> str:
    home_score = int(settlement["homeScore"])
    away_score = int(settlement["awayScore"])
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def half_full_to_outcomes(probabilities: dict[str, float]) -> dict[str, float]:
    outcomes = {key: 0.0 for key in OUTCOME_KEYS}
    for selection, probability in probabilities.items():
        full_label = selection[1]
        outcomes[{"\u80dc": "home", "\u5e73": "draw", "\u8d1f": "away"}[full_label]] += probability
    return outcomes


def blend_outcomes(
    base: dict[str, float],
    auxiliary: dict[str, float],
    weight: float,
) -> dict[str, float]:
    return {
        key: (1 - weight) * base[key] + weight * auxiliary[key]
        for key in OUTCOME_KEYS
    }


def assist_weight_for_stage(stage: str) -> float:
    return KNOCKOUT_OUTCOME_ASSIST_WEIGHT if stage == "knockout" else GROUP_OUTCOME_ASSIST_WEIGHT


def outcome_metric(probabilities: dict[str, float], actual: str) -> dict[str, Any]:
    predicted = max(OUTCOME_KEYS, key=lambda key: probabilities.get(key, 0.0))
    actual_probability = max(probabilities.get(actual, 0.0), 1e-12)
    return {
        "predicted": predicted,
        "hit": predicted == actual,
        "actualProbability": actual_probability,
        "logLoss": -math.log(actual_probability),
        "probabilities": {key: round(probabilities.get(key, 0.0), 6) for key in OUTCOME_KEYS},
    }


def evaluate_row(
    match_id: str,
    forecast: dict[str, Any],
    settlement: dict[str, Any],
) -> dict[str, Any] | None:
    actual = actual_half_full(settlement)
    if actual is None:
        return None

    match = forecast["match"]
    probabilities = half_full_probabilities(match)
    if not probabilities:
        return None
    if match.get("halfFullSource") == "reconstructed_from_archived_xg":
        calibration = apply_half_full_market_calibration(
            probabilities,
            (
                {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}}
                if match.get("knockoutContext") or str(match.get("kickoff") or "")[:10] >= "2026-06-28"
                else {}
            ),
        )
        probabilities = calibration.probabilities
        calibration_metadata = calibration.metadata
    else:
        calibration_metadata = match.get("halfFullCalibration") or {
            "applied": False,
            "reason": "archived_quotes_are_final_probabilities",
        }

    ranked = sorted(
        (
            {"selection": selection, "probability": probabilities.get(selection, 0.0)}
            for selection in SELECTIONS
        ),
        key=lambda item: item["probability"],
        reverse=True,
    )
    predicted = str(ranked[0]["selection"])
    actual_probability = max(probabilities.get(actual, 0.0), 1e-12)
    base_outcomes = {
        key: float(forecast["match"]["outcomeProbabilities"][key])
        for key in OUTCOME_KEYS
    }
    half_full_outcomes = half_full_to_outcomes(probabilities)
    stage = (
        "knockout"
        if match.get("knockoutContext") or str(match.get("kickoff") or "")[:10] >= "2026-06-28"
        else "group"
    )
    assist_weight = assist_weight_for_stage(stage)
    assisted_outcomes = blend_outcomes(base_outcomes, half_full_outcomes, assist_weight)
    actual_wdl = actual_outcome(settlement)
    return {
        "matchId": match_id,
        "forecastMatchId": match_id,
        "settlementMatchId": forecast.get("settlementMatchId", match_id),
        "homeTeam": match.get("homeTeam"),
        "awayTeam": match.get("awayTeam"),
        "kickoff": match.get("kickoff"),
        "stage": stage,
        "historyPath": forecast["historyPath"],
        "historySection": forecast.get("historySection"),
        "historyGeneratedAt": forecast["historyGeneratedAt"],
        "halfFullCalibration": calibration_metadata,
        "actual": actual,
        "predicted": predicted,
        "hit": predicted == actual,
        "top3Hit": any(item["selection"] == actual for item in ranked[:3]),
        "actualProbability": actual_probability,
        "logLoss": -math.log(actual_probability),
        "brier": multiclass_brier(probabilities, actual),
        "topSelections": ranked[:5],
        "probabilities": {selection: round(probabilities.get(selection, 0.0), 6) for selection in SELECTIONS},
        "outcomeAssistance": {
            "actual": actual_wdl,
            "base": outcome_metric(base_outcomes, actual_wdl),
            "halfFullSignal": outcome_metric(half_full_outcomes, actual_wdl),
            "assisted": outcome_metric(assisted_outcomes, actual_wdl),
            "assistWeight": assist_weight,
        },
        "score": {
            "halftime": f"{settlement['halfTimeHomeScore']}:{settlement['halfTimeAwayScore']}",
            "fulltime": f"{settlement['homeScore']}:{settlement['awayScore']}",
        },
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"matches": 0}

    actual_counts = Counter(str(row["actual"]) for row in rows)
    prediction_counts = Counter(str(row["predicted"]) for row in rows)
    match_count = len(rows)
    hits = sum(1 for row in rows if row["hit"])
    top3_hits = sum(1 for row in rows if row["top3Hit"])
    most_common_actual, most_common_actual_count = actual_counts.most_common(1)[0]
    return {
        "matches": match_count,
        "hits": hits,
        "accuracy": hits / match_count,
        "top3Hits": top3_hits,
        "top3Accuracy": top3_hits / match_count,
        "averageLogLoss": sum(float(row["logLoss"]) for row in rows) / match_count,
        "averageBrier": sum(float(row["brier"]) for row in rows) / match_count,
        "averageActualProbability": sum(float(row["actualProbability"]) for row in rows) / match_count,
        "inSampleMostCommonActual": most_common_actual,
        "inSampleMostCommonAccuracy": most_common_actual_count / match_count,
        "uniformNineWayLogLoss": math.log(len(SELECTIONS)),
        "actualDistribution": dict(sorted(actual_counts.items())),
        "predictionDistribution": dict(sorted(prediction_counts.items())),
    }


def summarize_by_stage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stage"])].append(row)
    return {stage: summarize(stage_rows) for stage, stage_rows in sorted(grouped.items())}


def latest_matched_kickoff_date_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated_rows = [
        (parse_datetime(row.get("kickoff")), row)
        for row in rows
        if row.get("kickoff")
    ]
    if not dated_rows:
        return []
    latest_date = max(kickoff.astimezone(BEIJING).date() for kickoff, _row in dated_rows if kickoff)
    return [
        row
        for kickoff, row in dated_rows
        if kickoff and kickoff.astimezone(BEIJING).date() == latest_date
    ]


def summarize_outcomes(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {"matches": 0}

    values = [row["outcomeAssistance"][key] for row in rows]
    hits = sum(1 for value in values if value["hit"])
    return {
        "matches": len(values),
        "hits": hits,
        "accuracy": hits / len(values),
        "averageLogLoss": sum(float(value["logLoss"]) for value in values) / len(values),
        "averageActualProbability": (
            sum(float(value["actualProbability"]) for value in values) / len(values)
        ),
    }


def outcome_assistance_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "assistPolicy": {
            "groupWeight": GROUP_OUTCOME_ASSIST_WEIGHT,
            "knockoutWeight": KNOCKOUT_OUTCOME_ASSIST_WEIGHT,
        },
        "base": summarize_outcomes(rows, "base"),
        "halfFullSignal": summarize_outcomes(rows, "halfFullSignal"),
        "assisted": summarize_outcomes(rows, "assisted"),
    }


def outcome_assistance_by_stage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stage"])].append(row)
    return {stage: outcome_assistance_summary(stage_rows) for stage, stage_rows in sorted(grouped.items())}


def build_report(
    history_dir: Path = DEFAULT_HISTORY_DIR,
    settlements_path: Path = DEFAULT_SETTLEMENTS_PATH,
    score_matrix_backtest_path: Path = DEFAULT_SCORE_MATRIX_BACKTEST_PATH,
) -> dict[str, Any]:
    settlements = load_settlements(settlements_path)
    forecasts = archived_forecasts(history_dir, settlements)
    supplemental = supplemental_score_matrix_forecasts(
        score_matrix_backtest_path,
        settlements,
        forecasts,
    )
    forecasts.update(supplemental)
    rows = []
    missing_halftime = 0
    for match_id, forecast in sorted(
        forecasts.items(),
        key=lambda item: item[1]["match"].get("kickoff") or "",
    ):
        settlement_match_id = str(forecast.get("settlementMatchId") or match_id)
        row = evaluate_row(match_id, forecast, settlements[settlement_match_id])
        if row is None:
            if actual_half_full(settlements[settlement_match_id]) is None:
                missing_halftime += 1
            continue
        rows.append(row)
    latest_rows = latest_matched_kickoff_date_rows(rows)

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "scope": {
            "tournament": "FIFA World Cup 2026",
            "market": HALF_FULL_MARKET,
            "policy": (
                "latest archived pre-kickoff forecast with half-time/full-time quotes, "
                "joined to local settlements by match id; settlements missing halftime "
                "scores are excluded"
            ),
            "settlementCount": len(settlements),
            "forecastsWithHalfFullMarket": len(forecasts),
            "supplementalReconstructedForecasts": len(supplemental),
            "excludedMissingHalftime": missing_halftime,
            "evaluatedMatches": len(rows),
        },
        "metricDefinitions": {
            "accuracy": "top probability half-time/full-time selection equals the realized selection",
            "top3Accuracy": "realized selection appears in the three highest model probabilities",
            "averageLogLoss": "negative log probability assigned to the realized selection",
            "averageBrier": "sum of squared probability errors across the nine selections",
            "inSampleMostCommonAccuracy": "accuracy from always picking the most frequent realized class in this same sample",
            "outcomeAssistance": "W/D/L metrics before and after adding the half-full specialist signal",
        },
        "metrics": {
            "allMatchedSettled": summarize(rows),
            "latestCompleted": summarize(latest_rows),
            "byStage": summarize_by_stage(rows),
            "outcomeAssistance": {
                "allMatchedSettled": outcome_assistance_summary(rows),
                "latestCompleted": outcome_assistance_summary(latest_rows),
                "byStage": outcome_assistance_by_stage(rows),
            },
        },
        "latestCompletedMatchIds": [str(row["matchId"]) for row in latest_rows],
        "matches": rows,
    }
    return report


def main() -> None:
    args = parse_args()
    report = build_report(args.history_dir, args.settlements)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
