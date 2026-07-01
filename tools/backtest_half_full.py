from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_HISTORY_DIR = ROOT / "public" / "data" / "history"
DEFAULT_SETTLEMENTS_PATH = ROOT / "public" / "data" / "settlements.json"
DEFAULT_OUTPUT_PATH = ROOT / "artifacts" / "half-full-backtest-2026.json"
HALF_FULL_MARKET = "\u534a\u5168\u573a"
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


def archived_forecasts(
    history_dir: Path,
    settlements: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    forecasts: dict[str, dict[str, Any]] = {}
    for path in sorted(history_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = parse_datetime(payload.get("generatedAt"))
        for match in payload.get("matches", []):
            match_id = settlement_key(match)
            if match_id not in settlements:
                continue
            if not half_full_probabilities(match):
                continue

            kickoff = parse_datetime(match.get("kickoff"))
            if generated_at and kickoff and generated_at > kickoff:
                continue

            previous = forecasts.get(match_id)
            previous_generated = parse_datetime(previous["historyGeneratedAt"]) if previous else None
            if previous is None or (
                generated_at and previous_generated and generated_at > previous_generated
            ):
                forecasts[match_id] = {
                    "historyPath": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "historyGeneratedAt": payload.get("generatedAt"),
                    "match": match,
                }
    return forecasts


def multiclass_brier(probabilities: dict[str, float], actual: str) -> float:
    return sum((probabilities.get(selection, 0.0) - (1.0 if selection == actual else 0.0)) ** 2 for selection in SELECTIONS)


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
    return {
        "matchId": match_id,
        "homeTeam": match.get("homeTeam"),
        "awayTeam": match.get("awayTeam"),
        "kickoff": match.get("kickoff"),
        "stage": "knockout" if match.get("knockoutContext") else "group",
        "historyPath": forecast["historyPath"],
        "historyGeneratedAt": forecast["historyGeneratedAt"],
        "actual": actual,
        "predicted": predicted,
        "hit": predicted == actual,
        "top3Hit": any(item["selection"] == actual for item in ranked[:3]),
        "actualProbability": actual_probability,
        "logLoss": -math.log(actual_probability),
        "brier": multiclass_brier(probabilities, actual),
        "topSelections": ranked[:5],
        "probabilities": {selection: round(probabilities.get(selection, 0.0), 6) for selection in SELECTIONS},
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


def build_report(
    history_dir: Path = DEFAULT_HISTORY_DIR,
    settlements_path: Path = DEFAULT_SETTLEMENTS_PATH,
) -> dict[str, Any]:
    settlements = load_settlements(settlements_path)
    forecasts = archived_forecasts(history_dir, settlements)
    rows = []
    missing_halftime = 0
    for match_id, forecast in sorted(
        forecasts.items(),
        key=lambda item: item[1]["match"].get("kickoff") or "",
    ):
        row = evaluate_row(match_id, forecast, settlements[match_id])
        if row is None:
            if actual_half_full(settlements[match_id]) is None:
                missing_halftime += 1
            continue
        rows.append(row)

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
            "excludedMissingHalftime": missing_halftime,
            "evaluatedMatches": len(rows),
        },
        "metricDefinitions": {
            "accuracy": "top probability half-time/full-time selection equals the realized selection",
            "top3Accuracy": "realized selection appears in the three highest model probabilities",
            "averageLogLoss": "negative log probability assigned to the realized selection",
            "averageBrier": "sum of squared probability errors across the nine selections",
            "inSampleMostCommonAccuracy": "accuracy from always picking the most frequent realized class in this same sample",
        },
        "metrics": {
            "allMatchedSettled": summarize(rows),
            "byStage": summarize_by_stage(rows),
        },
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
