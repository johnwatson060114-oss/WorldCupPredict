from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.model import score_matrix, top_scores, total_goals_probabilities
from pipeline.score_calibration import apply_score_matrix_calibration


BEIJING = ZoneInfo("Asia/Shanghai")
GOAL_BUCKETS = ["0", "1", "2", "3", "4", "5", "6", "7+"]
DEFAULT_HISTORY_DIR = ROOT / "public" / "data" / "history"
DEFAULT_SETTLEMENTS_PATH = ROOT / "public" / "data" / "settlements.json"
DEFAULT_OUTPUT_PATH = ROOT / "artifacts" / "score-matrix-backtest-2026.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest total-goals and exact-score matrix predictions from archived "
            "forecast files joined to local settlements."
        )
    )
    parser.add_argument("--history-dir", type=Path, default=DEFAULT_HISTORY_DIR)
    parser.add_argument("--settlements", type=Path, default=DEFAULT_SETTLEMENTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--latest-match-id",
        action="append",
        default=None,
        help="Match id to include in the latestCompleted scope. May be repeated.",
    )
    return parser.parse_args()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def actual_bucket(total_goals: int) -> str:
    return "7+" if total_goals >= 7 else str(total_goals)


def bucket_index(label: str) -> int:
    return 7 if label == "7+" else int(label)


def ranked_probability_score(probabilities: dict[str, float], actual: str) -> float:
    cumulative = 0.0
    total = 0.0
    actual_index = bucket_index(actual)
    for index, bucket in enumerate(GOAL_BUCKETS[:-1]):
        cumulative += probabilities.get(bucket, 0.0)
        target = 1.0 if index >= actual_index else 0.0
        total += (cumulative - target) ** 2
    return total / (len(GOAL_BUCKETS) - 1)


def probability_at_score(matrix: list[list[float]], home_goals: int, away_goals: int) -> float:
    if home_goals < len(matrix) and away_goals < len(matrix[home_goals]):
        return matrix[home_goals][away_goals]
    return 1e-12


def top_total_bucket(probabilities: dict[str, float]) -> str:
    return max(GOAL_BUCKETS, key=lambda bucket: probabilities.get(bucket, 0.0))


def score_xg(match: dict[str, Any]) -> tuple[float, float] | None:
    decomposition = match.get("modelDecomposition") or {}
    adjusted = decomposition.get("adjustedExpectedGoals") or {}
    if adjusted.get("home") is not None and adjusted.get("away") is not None:
        return float(adjusted["home"]), float(adjusted["away"])

    expected = match.get("expectedGoals") or {}
    if expected.get("home") is not None and expected.get("away") is not None:
        return float(expected["home"]), float(expected["away"])

    return None


def evaluate_matrix(matrix: list[list[float]], home_score: int, away_score: int) -> dict[str, Any]:
    total_probabilities = total_goals_probabilities(matrix)
    actual_total_bucket = actual_bucket(home_score + away_score)
    predicted_total_bucket = top_total_bucket(total_probabilities)
    top_score_rows = top_scores(matrix, limit=8)
    actual_score = f"{home_score}:{away_score}"
    actual_score_probability = max(probability_at_score(matrix, home_score, away_score), 1e-12)

    return {
        "predictedTotalBucket": predicted_total_bucket,
        "actualTotalBucket": actual_total_bucket,
        "totalExactHit": predicted_total_bucket == actual_total_bucket,
        "totalAdjacentCoreHit": abs(
            bucket_index(predicted_total_bucket) - bucket_index(actual_total_bucket)
        )
        <= 1,
        "totalLogLoss": -math.log(max(total_probabilities.get(actual_total_bucket, 0.0), 1e-12)),
        "totalRps": ranked_probability_score(total_probabilities, actual_total_bucket),
        "topScore": top_score_rows[0]["score"] if top_score_rows else None,
        "actualScore": actual_score,
        "scoreTop1Hit": bool(top_score_rows and top_score_rows[0]["score"] == actual_score),
        "scoreTop3Hit": any(item["score"] == actual_score for item in top_score_rows[:3]),
        "scoreTop5Hit": any(item["score"] == actual_score for item in top_score_rows[:5]),
        "scoreLogLoss": -math.log(actual_score_probability),
        "actualScoreProbability": actual_score_probability,
        "topScores": top_score_rows[:5],
        "totalProbabilities": {bucket: total_probabilities.get(bucket, 0.0) for bucket in GOAL_BUCKETS},
    }


def summarize(rows: list[dict[str, Any]], model_key: str) -> dict[str, Any]:
    if not rows:
        return {"matches": 0}

    metrics = [row[model_key] for row in rows]
    total_exact_hits = sum(1 for metric in metrics if metric["totalExactHit"])
    total_adjacent_hits = sum(1 for metric in metrics if metric["totalAdjacentCoreHit"])
    score_top1_hits = sum(1 for metric in metrics if metric["scoreTop1Hit"])
    score_top3_hits = sum(1 for metric in metrics if metric["scoreTop3Hit"])
    score_top5_hits = sum(1 for metric in metrics if metric["scoreTop5Hit"])
    match_count = len(metrics)

    return {
        "matches": match_count,
        "totalExactHits": total_exact_hits,
        "totalExactAccuracy": total_exact_hits / match_count,
        "totalAdjacentCoreHits": total_adjacent_hits,
        "totalAdjacentCoreAccuracy": total_adjacent_hits / match_count,
        "averageTotalLogLoss": sum(metric["totalLogLoss"] for metric in metrics) / match_count,
        "averageTotalRps": sum(metric["totalRps"] for metric in metrics) / match_count,
        "scoreTop1Hits": score_top1_hits,
        "scoreTop1Accuracy": score_top1_hits / match_count,
        "scoreTop3Hits": score_top3_hits,
        "scoreTop3Accuracy": score_top3_hits / match_count,
        "scoreTop5Hits": score_top5_hits,
        "scoreTop5Accuracy": score_top5_hits / match_count,
        "averageScoreLogLoss": sum(metric["scoreLogLoss"] for metric in metrics) / match_count,
    }


def scope_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "base": summarize(rows, "base"),
        "calibrated": summarize(rows, "calibrated"),
    }


def load_settlements(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["matchId"]): row for row in payload["matches"]}


def latest_history_match_ids(history_dir: Path, settlements: dict[str, dict[str, Any]]) -> set[str]:
    history_paths = sorted(history_dir.glob("*.json"))
    if not history_paths:
        return set()

    latest_path = max(
        history_paths,
        key=lambda path: (
            json.loads(path.read_text(encoding="utf-8")).get("targetDate") or "",
            path.name,
        ),
    )
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    return {
        str(match.get("id"))
        for match in payload.get("matches", [])
        if str(match.get("id")) in settlements
    }


def archived_forecasts(
    history_dir: Path,
    settlements: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    forecasts: dict[str, dict[str, Any]] = {}

    for path in sorted(history_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = parse_datetime(payload.get("generatedAt"))
        for match in payload.get("matches", []):
            match_id = str(match.get("id") or "")
            if match_id not in settlements:
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


def build_rows(
    forecasts: dict[str, dict[str, Any]],
    settlements: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for match_id, forecast in sorted(
        forecasts.items(),
        key=lambda item: item[1]["match"].get("kickoff") or "",
    ):
        match = forecast["match"]
        xg = score_xg(match)
        if xg is None:
            continue

        home_xg, away_xg = xg
        settlement = settlements[match_id]
        home_score = int(settlement["homeScore"])
        away_score = int(settlement["awayScore"])
        base_matrix = score_matrix(home_xg, away_xg)
        calibration = apply_score_matrix_calibration(
            base_matrix,
            {"knockout_context": match.get("knockoutContext")},
            home_xg,
            away_xg,
        )

        rows.append(
            {
                "matchId": match_id,
                "homeTeam": match.get("homeTeam"),
                "awayTeam": match.get("awayTeam"),
                "kickoff": match.get("kickoff"),
                "stage": "knockout" if match.get("knockoutContext") else "group",
                "historyPath": forecast["historyPath"],
                "historyGeneratedAt": forecast["historyGeneratedAt"],
                "settlementScoreBasis": settlement.get("settlementScoreBasis", "fulltime"),
                "actualScore": f"{home_score}:{away_score}",
                "xg": {"home": home_xg, "away": away_xg},
                "base": evaluate_matrix(base_matrix, home_score, away_score),
                "calibrated": evaluate_matrix(calibration.matrix, home_score, away_score),
                "scoreCalibration": calibration.metadata,
            }
        )

    return rows


def main() -> None:
    args = parse_args()
    settlements = load_settlements(args.settlements)
    forecasts = archived_forecasts(args.history_dir, settlements)
    rows = build_rows(forecasts, settlements)

    latest_match_ids = set(args.latest_match_id or []) or latest_history_match_ids(
        args.history_dir,
        settlements,
    )
    latest_rows = [row for row in rows if row["matchId"] in latest_match_ids]
    knockout_rows = [row for row in rows if row["stage"] == "knockout"]

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "scope": {
            "tournament": "FIFA World Cup 2026",
            "predictionTarget": "90_minutes",
            "policy": (
                "archived forecasts joined to local settlements by match id; full score matrix "
                "reconstructed from archived adjustedExpectedGoals; knockout score calibration "
                "applied from archived knockoutContext"
            ),
            "matchedSettledMatches": len(rows),
            "settlementCount": len(settlements),
        },
        "metricDefinitions": {
            "totalExactAccuracy": (
                "predicted total-goals bucket with highest probability equals actual "
                "total-goals bucket"
            ),
            "totalAdjacentCoreAccuracy": (
                "predicted total-goals bucket is within one bucket of the actual bucket"
            ),
            "scoreTopKAccuracy": (
                "actual exact score appears in the top K score probabilities from the "
                "reconstructed full matrix"
            ),
            "logLoss": "negative log probability assigned to the realized bucket or exact score",
            "rps": "ranked probability score over ordered total-goals buckets 0,1,2,3,4,5,6,7+",
        },
        "metrics": {
            "allMatchedSettled": scope_summary(rows),
            "knockout": scope_summary(knockout_rows),
            "latestCompleted": scope_summary(latest_rows),
        },
        "modelDecision": {
            "primaryAdjustmentTarget": "total_goals_and_exact_score_matrix",
            "wdlRole": "auxiliary outcome sanity check only",
            "currentDecision": (
                "keep current production total-goals model; keep optimized total-goals model "
                "as shadow; keep knockout score calibration enabled but do not widen it from "
                "this small knockout sample"
            ),
            "reason": (
                "latest completed matches slightly help calibrated total-goals log loss/RPS, "
                "but the settled knockout sample still favors the base matrix on exact-score "
                "top1 and log loss; optimized total-goals shadow has not cleared stable-window "
                "adoption gates"
            ),
        },
        "latestCompletedMatchIds": sorted(latest_match_ids),
        "latestMatches": latest_rows,
        "knockoutMatches": knockout_rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
