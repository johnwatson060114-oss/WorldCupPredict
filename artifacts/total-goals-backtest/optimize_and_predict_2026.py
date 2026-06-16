from __future__ import annotations

import csv
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline.goal_models import ModelSpec, default_candidate_grid, fit_goal_model
from pipeline.model import total_goals_probabilities


DATA_PATH = ROOT / "artifacts" / "total-goals-backtest" / "international_results.csv"
MANUAL_2026_PATH = ROOT / "artifacts" / "total-goals-backtest" / "manual_2026_results.csv"
OUT_JSON = ROOT / "artifacts" / "total-goals-backtest" / "optimized_2026_summary.json"
OUT_CSV = ROOT / "artifacts" / "total-goals-backtest" / "optimized_2026_predictions.csv"
OUT_COMPARISON_CSV = ROOT / "artifacts" / "total-goals-backtest" / "model_comparison_2026.csv"
OUT_PUBLIC_REVIEW_JSON = ROOT / "public" / "data" / "total-goals-model-review.json"
RESULTS_CSV_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
GOAL_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7+"]
CURRENT_SPEC = ModelSpec("dixon_coles", {"half_life_days": 730.0, "rho": -0.08, "shrinkage": 6.0})
OPTIMIZED_SPEC = ModelSpec("hierarchical_poisson", {"rho": 0.0, "shrinkage": 16.0})
RUN_FULL_GRID = os.environ.get("TOTAL_GOALS_FULL_GRID") == "1"
SKIP_FETCH = os.environ.get("TOTAL_GOALS_SKIP_FETCH") == "1"
MIN_ADOPTION_MATCHES = 24
MIN_EXACT_ACCURACY_LIFT = 0.08
MIN_EXTRA_EXACT_HITS = 3
MIN_LOG_LOSS_IMPROVEMENT = 0.02
MAX_CORE_ACCURACY_DROP = 0.05


def beijing_now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def refresh_results_csv() -> dict[str, Any]:
    if SKIP_FETCH:
        return {
            "status": "skipped",
            "reason": "TOTAL_GOALS_SKIP_FETCH=1",
            "path": str(DATA_PATH.relative_to(ROOT)),
        }
    try:
        with urllib.request.urlopen(RESULTS_CSV_URL, timeout=20) as response:
            payload = response.read()
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_bytes(payload)
        return {
            "status": "ok",
            "url": RESULTS_CSV_URL,
            "bytes": len(payload),
            "path": str(DATA_PATH.relative_to(ROOT)),
            "refreshedAt": beijing_now(),
        }
    except (OSError, urllib.error.URLError) as exc:
        return {
            "status": "failed",
            "url": RESULTS_CSV_URL,
            "error": str(exc),
            "path": str(DATA_PATH.relative_to(ROOT)),
            "fallback": "kept existing local CSV",
            "refreshedAt": beijing_now(),
        }


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
                "source": "international_results",
            })
    seen = {(row["date"], row["home_team"], row["away_team"]) for row in rows}
    if MANUAL_2026_PATH.exists():
        with MANUAL_2026_PATH.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["date"], row["home_team"], row["away_team"])
                if key in seen:
                    continue
                rows.append({
                    "date": row["date"],
                    "home_team_id": row["home_team"],
                    "away_team_id": row["away_team"],
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "home_goals_90": int(float(row["home_score"])),
                    "away_goals_90": int(float(row["away_score"])),
                    "tournament": "FIFA World Cup",
                    "neutral": True,
                    "kickoff_utc": f"{row['date']}T12:00:00+00:00",
                    "source": row.get("source") or "manual",
                })
                seen.add(key)
    return sorted(rows, key=lambda item: item["date"])


def count_manual_results() -> int:
    if not MANUAL_2026_PATH.exists():
        return 0
    with MANUAL_2026_PATH.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def bucket(home: int, away: int) -> str:
    total = home + away
    return "7+" if total >= 7 else str(total)


def strongest_adjacent(probabilities: dict[str, float]) -> tuple[str, set[str], float]:
    best_label = ""
    best_set: set[str] = set()
    best_probability = -1.0
    for left, right in zip(GOAL_ORDER, GOAL_ORDER[1:]):
        probability = probabilities[left] + probabilities[right]
        if probability > best_probability:
            best_label = f"{left}-{right}"
            best_set = {left, right}
            best_probability = probability
    return best_label, best_set, best_probability


def predict(rows: list[dict[str, Any]], targets: list[dict[str, Any]], spec: ModelSpec) -> list[dict[str, Any]]:
    predictions = []
    for match in targets:
        training = [row for row in rows if row["date"] < match["date"]]
        model = fit_goal_model(training, spec)
        matrix = model.matrix(match["home_team"], match["away_team"], match["neutral"])
        probabilities = total_goals_probabilities(matrix)
        predicted_bucket = max(GOAL_ORDER, key=lambda key: probabilities[key])
        core_label, core_set, core_probability = strongest_adjacent(probabilities)
        actual_bucket = bucket(match["home_goals_90"], match["away_goals_90"])
        predictions.append({
            "date": match["date"],
            "match": f"{match['home_team']} vs {match['away_team']}",
            "score": f"{match['home_goals_90']}-{match['away_goals_90']}",
            "actual_total_goals": match["home_goals_90"] + match["away_goals_90"],
            "actual_bucket": actual_bucket,
            "predicted_bucket": predicted_bucket,
            "predicted_probability": probabilities[predicted_bucket],
            "exact_hit": predicted_bucket == actual_bucket,
            "core_interval": core_label,
            "core_probability": core_probability,
            "core_hit": actual_bucket in core_set,
            "log_loss": -math.log(max(1e-12, probabilities[actual_bucket])),
            "bucketed_expected_total": sum((7 if key == "7+" else int(key)) * probabilities[key] for key in GOAL_ORDER),
            "probabilities": probabilities,
        })
    return predictions


def summarize(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(predictions)
    exact_hits = sum(item["exact_hit"] for item in predictions)
    core_hits = sum(item["core_hit"] for item in predictions)
    return {
        "matches": total,
        "exact_hits": exact_hits,
        "exact_accuracy": exact_hits / total if total else 0,
        "core_hits": core_hits,
        "core_accuracy": core_hits / total if total else 0,
        "average_log_loss": sum(item["log_loss"] for item in predictions) / total if total else math.inf,
        "predicted_bucket_counts": {bucket: sum(item["predicted_bucket"] == bucket for item in predictions) for bucket in GOAL_ORDER},
        "average_bucketed_expected_total": sum(item["bucketed_expected_total"] for item in predictions) / total if total else 0,
    }


def adoption_decision(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    matches = min(current["matches"], candidate["matches"])
    exact_lift = candidate["exact_accuracy"] - current["exact_accuracy"]
    extra_hits = candidate["exact_hits"] - current["exact_hits"]
    log_loss_improvement = current["average_log_loss"] - candidate["average_log_loss"]
    core_delta = candidate["core_accuracy"] - current["core_accuracy"]
    gates = {
        "sample_size": matches >= MIN_ADOPTION_MATCHES,
        "exact_accuracy_lift": exact_lift >= MIN_EXACT_ACCURACY_LIFT,
        "extra_exact_hits": extra_hits >= MIN_EXTRA_EXACT_HITS,
        "log_loss_improvement": log_loss_improvement >= MIN_LOG_LOSS_IMPROVEMENT,
        "core_accuracy_not_materially_worse": core_delta >= -MAX_CORE_ACCURACY_DROP,
    }
    if all(gates.values()):
        status = "switch"
        reason = "candidate model clears every adoption gate"
        recommendation_zh = "新模型已经显著优于旧模型，可以切换为主用模型。"
    elif not gates["sample_size"]:
        status = "observe"
        reason = f"need at least {MIN_ADOPTION_MATCHES} settled 2026 matches before switching"
        recommendation_zh = "样本还不够，旧模型继续主用，新模型继续影子观察。"
    else:
        status = "keep"
        reason = "candidate has not shown a significant, stable advantage over the current model"
        recommendation_zh = "新模型优势不显著，继续使用旧模型。"
    return {
        "status": status,
        "should_switch_model": status == "switch",
        "reason": reason,
        "recommendation_zh": recommendation_zh,
        "gates": gates,
        "deltas": {
            "exact_accuracy_lift": exact_lift,
            "extra_exact_hits": extra_hits,
            "log_loss_improvement": log_loss_improvement,
            "core_accuracy_delta": core_delta,
        },
        "thresholds": {
            "min_matches": MIN_ADOPTION_MATCHES,
            "min_exact_accuracy_lift": MIN_EXACT_ACCURACY_LIFT,
            "min_extra_exact_hits": MIN_EXTRA_EXACT_HITS,
            "min_log_loss_improvement": MIN_LOG_LOSS_IMPROVEMENT,
            "max_core_accuracy_drop": MAX_CORE_ACCURACY_DROP,
        },
    }


def public_prediction(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: item[key] for key in [
            "date", "match", "score", "actual_total_goals", "actual_bucket",
            "predicted_bucket", "predicted_probability", "exact_hit",
            "core_interval", "core_probability", "core_hit", "bucketed_expected_total",
        ]},
        "probabilities": json.dumps({key: round(value, 6) for key, value in item["probabilities"].items()}, ensure_ascii=False),
    }


def compare_predictions(current: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for old, new in zip(current, candidate):
        rows.append({
            "date": old["date"],
            "match": old["match"],
            "score": old["score"],
            "actual_total_goals": old["actual_total_goals"],
            "actual_bucket": old["actual_bucket"],
            "current_predicted_bucket": old["predicted_bucket"],
            "current_exact_hit": old["exact_hit"],
            "current_core_interval": old["core_interval"],
            "current_core_hit": old["core_hit"],
            "current_log_loss": old["log_loss"],
            "candidate_predicted_bucket": new["predicted_bucket"],
            "candidate_exact_hit": new["exact_hit"],
            "candidate_core_interval": new["core_interval"],
            "candidate_core_hit": new["core_hit"],
            "candidate_log_loss": new["log_loss"],
        })
    return rows


def main() -> None:
    data_refresh = refresh_results_csv()
    rows = read_rows()
    validation = [
        row for row in rows
        if row["tournament"] == "FIFA World Cup" and row["date"][:4] in {"2018", "2022"}
    ]
    world_cup_2026 = [
        row for row in rows
        if row["tournament"] == "FIFA World Cup" and row["date"].startswith("2026")
    ]

    if RUN_FULL_GRID:
        candidates = [ModelSpec("legacy", {}), *default_candidate_grid()]
        ranking = []
        for spec in candidates:
            predictions = predict(rows, validation, spec)
            summary = summarize(predictions)
            ranking.append({"model_spec": spec.key, **summary})
        ranking.sort(key=lambda item: (-item["exact_accuracy"], item["average_log_loss"], -item["core_accuracy"]))
        best_key = ranking[0]["model_spec"]
        candidate_spec = next(spec for spec in candidates if spec.key == best_key)
        optimized_spec_source = "selected by full 2018+2022 grid search in this run"
    else:
        ranking = []
        candidate_spec = OPTIMIZED_SPEC
        optimized_spec_source = "locked from the 2018+2022 grid search; set TOTAL_GOALS_FULL_GRID=1 to reselect"

    current_2026 = predict(rows, world_cup_2026, CURRENT_SPEC)
    optimized_2026 = predict(rows, world_cup_2026, candidate_spec)
    current_summary = summarize(current_2026)
    optimized_summary = summarize(optimized_2026)
    current_rows = [public_prediction(item) for item in current_2026]
    optimized_rows = [public_prediction(item) for item in optimized_2026]
    comparison_rows = compare_predictions(current_2026, optimized_2026)

    summary = {
        "generatedAt": beijing_now(),
        "timezone": "Asia/Shanghai",
        "data_refresh": data_refresh,
        "optimization": {
            "validation_set": "FIFA World Cup 2018 and 2022",
            "selection_rule": "highest exact total-goals bucket accuracy; tie-break by total-goals log loss then core interval accuracy",
            "production_policy": "current model remains primary; optimized model runs as shadow until adoption gates pass",
            "current_model_spec": CURRENT_SPEC.key,
            "optimized_model_spec": candidate_spec.key,
            "optimized_model_spec_source": optimized_spec_source,
            "full_grid_was_run": RUN_FULL_GRID,
            "top_candidates": ranking[:8],
        },
        "current_model_2026": current_summary,
        "optimized_model_2026": optimized_summary,
        "adoption_decision": adoption_decision(current_summary, optimized_summary),
        "current_predictions_2026": current_rows,
        "optimized_predictions_2026": optimized_rows,
        "comparison_2026": comparison_rows,
    }

    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    public_review = {
        "schemaVersion": 1,
        "generatedAt": summary["generatedAt"],
        "timezone": summary["timezone"],
        "scheduledReviewStartDate": "2026-06-17",
        "productionPolicy": summary["optimization"]["production_policy"],
        "currentModel": {
            "role": "production",
            "spec": summary["optimization"]["current_model_spec"],
            **current_summary,
        },
        "shadowModel": {
            "role": "shadow",
            "spec": summary["optimization"]["optimized_model_spec"],
            **optimized_summary,
        },
        "adoptionDecision": summary["adoption_decision"],
        "dataRefresh": data_refresh,
        "manualResultRows": count_manual_results(),
        "comparisonPath": str(OUT_COMPARISON_CSV.relative_to(ROOT)),
    }
    OUT_PUBLIC_REVIEW_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_PUBLIC_REVIEW_JSON.write_text(json.dumps(public_review, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(optimized_rows[0]))
        writer.writeheader()
        writer.writerows(optimized_rows)
    with OUT_COMPARISON_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison_rows[0]))
        writer.writeheader()
        writer.writerows(comparison_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
