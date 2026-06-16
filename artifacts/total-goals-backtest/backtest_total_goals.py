from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline.goal_models import ModelSpec, fit_goal_model
from pipeline.model import total_goals_probabilities

DATA_PATH = ROOT / "artifacts" / "total-goals-backtest" / "international_results.csv"
OUT_CSV = ROOT / "artifacts" / "total-goals-backtest" / "total_goals_predictions.csv"
OUT_JSON = ROOT / "artifacts" / "total-goals-backtest" / "summary.json"

SPEC = ModelSpec("dixon_coles", {"half_life_days": 730.0, "rho": -0.08, "shrinkage": 6.0})
GOAL_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7+"]


def read_rows() -> list[dict[str, Any]]:
    rows = []
    with DATA_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row["home_score"] or not row["away_score"] or row["home_score"] == "NA" or row["away_score"] == "NA":
                continue
            rows.append({
                "date": row["date"],
                "home_team_id": row["home_team"],
                "away_team_id": row["away_team"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home_goals_90": int(float(row["home_score"])),
                "away_goals_90": int(float(row["away_score"])),
                "tournament": row["tournament"],
                "neutral": row["neutral"].upper() == "TRUE",
                "kickoff_utc": f"{row['date']}T12:00:00+00:00",
            })
    return sorted(rows, key=lambda item: item["date"])


def bucket(home: int, away: int) -> str:
    total = home + away
    return "7+" if total >= 7 else str(total)


def top_adjacent(probabilities: dict[str, float]) -> tuple[str, set[str], float]:
    best_label = "0-1"
    best_set = {"0", "1"}
    best_probability = probabilities["0"] + probabilities["1"]
    for left, right in zip(GOAL_ORDER, GOAL_ORDER[1:]):
        probability = probabilities[left] + probabilities[right]
        if probability > best_probability:
            best_label = f"{left}-{right}"
            best_set = {left, right}
            best_probability = probability
    return best_label, best_set, best_probability


def evaluate() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_rows()
    targets = [
        row for row in rows
        if row["tournament"] == "FIFA World Cup" and row["date"][:4] in {"2018", "2022"}
    ]
    predictions = []
    for match in targets:
        training = [row for row in rows if row["date"] < match["date"]]
        model = fit_goal_model(training, SPEC)
        matrix = model.matrix(match["home_team"], match["away_team"], match["neutral"])
        probabilities = total_goals_probabilities(matrix)
        predicted_bucket = max(GOAL_ORDER, key=lambda key: probabilities[key])
        core_label, core_set, core_probability = top_adjacent(probabilities)
        actual_bucket = bucket(match["home_goals_90"], match["away_goals_90"])
        predictions.append({
            "year": match["date"][:4],
            "date": match["date"],
            "match": f"{match['home_team']} vs {match['away_team']}",
            "score": f"{match['home_goals_90']}-{match['away_goals_90']}",
            "actual_total_goals": match["home_goals_90"] + match["away_goals_90"],
            "actual_bucket": actual_bucket,
            "predicted_bucket": predicted_bucket,
            "predicted_probability": round(probabilities[predicted_bucket], 6),
            "exact_hit": predicted_bucket == actual_bucket,
            "core_interval": core_label,
            "core_probability": round(core_probability, 6),
            "core_hit": actual_bucket in core_set,
            "probabilities": {key: round(probabilities[key], 6) for key in GOAL_ORDER},
        })

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        exact_hits = sum(item["exact_hit"] for item in items)
        core_hits = sum(item["core_hit"] for item in items)
        return {
            "matches": total,
            "exact_hits": exact_hits,
            "exact_accuracy": exact_hits / total if total else 0,
            "core_hits": core_hits,
            "core_accuracy": core_hits / total if total else 0,
        }

    summary = {
        "model_spec": SPEC.key,
        "target": "FIFA World Cup 2018 and 2022",
        "definition": {
            "exact_hit": "argmax probability over Sporttery total-goals buckets 0,1,2,3,4,5,6,7+",
            "core_hit": "actual bucket falls inside the strongest adjacent two-bucket interval",
            "score_source_note": "CSV full score excludes penalty shoot-outs; knockout scores can include extra time when recorded.",
        },
        "overall": summarize(predictions),
        "by_year": {
            year: summarize([item for item in predictions if item["year"] == year])
            for year in ("2018", "2022")
        },
    }
    return predictions, summary


def main() -> None:
    predictions, summary = evaluate()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "year", "date", "match", "score", "actual_total_goals", "actual_bucket",
            "predicted_bucket", "predicted_probability", "exact_hit",
            "core_interval", "core_probability", "core_hit", "probabilities",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(predictions)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
