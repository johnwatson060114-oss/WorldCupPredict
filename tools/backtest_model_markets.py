from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.backtest_half_full import build_report as build_half_full_report
from tools.backtest_score_matrix import build_report as build_score_matrix_report


BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_HISTORY_DIR = ROOT / "public" / "data" / "history"
DEFAULT_SETTLEMENTS_PATH = ROOT / "public" / "data" / "settlements.json"
DEFAULT_SCORE_OUTPUT_PATH = ROOT / "artifacts" / "score-matrix-backtest-2026.json"
DEFAULT_HALF_FULL_OUTPUT_PATH = ROOT / "artifacts" / "half-full-backtest-2026.json"
DEFAULT_OUTPUT_PATH = ROOT / "artifacts" / "model-markets-backtest-2026.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest the specialist betting markets together: total goals, exact score, "
            "and half-time/full-time."
        )
    )
    parser.add_argument("--history-dir", type=Path, default=DEFAULT_HISTORY_DIR)
    parser.add_argument("--settlements", type=Path, default=DEFAULT_SETTLEMENTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--score-output", type=Path, default=DEFAULT_SCORE_OUTPUT_PATH)
    parser.add_argument("--half-full-output", type=Path, default=DEFAULT_HALF_FULL_OUTPUT_PATH)
    parser.add_argument(
        "--latest-match-id",
        action="append",
        default=None,
        help="Match id to include in the latestCompleted scope. May be repeated.",
    )
    return parser.parse_args()


def metric_subset(values: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: values[key] for key in keys if key in values}


def split_score_matrix_metrics(score_metrics: dict[str, Any]) -> dict[str, Any]:
    total_keys = (
        "matches",
        "totalExactHits",
        "totalExactAccuracy",
        "totalAdjacentCoreHits",
        "totalAdjacentCoreAccuracy",
        "averageTotalLogLoss",
        "averageTotalRps",
    )
    score_keys = (
        "matches",
        "scoreTop1Hits",
        "scoreTop1Accuracy",
        "scoreTop3Hits",
        "scoreTop3Accuracy",
        "scoreTop5Hits",
        "scoreTop5Accuracy",
        "averageScoreLogLoss",
    )
    return {
        "totalGoals": {
            scope: {
                model: metric_subset(values, total_keys)
                for model, values in scope_metrics.items()
            }
            for scope, scope_metrics in score_metrics.items()
        },
        "exactScore": {
            scope: {
                model: metric_subset(values, score_keys)
                for model, values in scope_metrics.items()
            }
            for scope, scope_metrics in score_metrics.items()
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_report(
    history_dir: Path = DEFAULT_HISTORY_DIR,
    settlements_path: Path = DEFAULT_SETTLEMENTS_PATH,
    score_output_path: Path = DEFAULT_SCORE_OUTPUT_PATH,
    half_full_output_path: Path = DEFAULT_HALF_FULL_OUTPUT_PATH,
    latest_match_ids: set[str] | None = None,
) -> dict[str, Any]:
    score_report = build_score_matrix_report(
        history_dir,
        settlements_path,
        latest_match_ids=latest_match_ids,
    )
    write_json(score_output_path, score_report)

    half_full_report = build_half_full_report(
        history_dir,
        settlements_path,
        score_matrix_backtest_path=score_output_path,
    )
    write_json(half_full_output_path, half_full_report)

    split_metrics = split_score_matrix_metrics(score_report["metrics"])
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "scope": {
            "tournament": "FIFA World Cup 2026",
            "predictionTarget": "90_minutes",
            "policy": (
                "full model-market backtest: total goals, exact score, and half-time/full-time "
                "are refreshed together from archived pre-kickoff forecasts and local settlements"
            ),
            "scoreMatrixReport": str(score_output_path.relative_to(ROOT)).replace("\\", "/"),
            "halfFullReport": str(half_full_output_path.relative_to(ROOT)).replace("\\", "/"),
        },
        "metricDefinitions": {
            "totalGoals": score_report["metricDefinitions"],
            "exactScore": score_report["metricDefinitions"],
            "halfFull": half_full_report["metricDefinitions"],
        },
        "metrics": {
            "totalGoals": split_metrics["totalGoals"],
            "exactScore": split_metrics["exactScore"],
            "halfFull": half_full_report["metrics"],
        },
        "modelDecision": {
            "primaryAdjustmentTargets": [
                "total_goals_bucket_distribution",
                "exact_score_matrix",
                "half_time_full_time_distribution",
            ],
            "wdlRole": "auxiliary outcome sanity check only",
            "productionScoreMatrix": "calibrated",
            "scoreCalibrationPolicy": "knockout_score_total_matrix_calibration_v2",
            "scoreCalibrationIntensity": 0.25,
            "halfFullCalibrationPolicy": "knockout_half_full_late_swing_v1",
            "diagnosticScoreMatrix": "base",
            "note": (
                "Future generic backtests should use this combined report so all three "
                "specialist markets move through the same evidence gate."
            ),
        },
    }


def main() -> None:
    args = parse_args()
    report = build_report(
        args.history_dir,
        args.settlements,
        score_output_path=args.score_output,
        half_full_output_path=args.half_full_output,
        latest_match_ids=set(args.latest_match_id or []) or None,
    )
    write_json(args.output, report)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
