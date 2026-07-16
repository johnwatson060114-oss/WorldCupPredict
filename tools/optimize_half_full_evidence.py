from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.current_tournament_evidence import EvidenceMatch, apply_current_tournament_evidence
from pipeline.half_full_specialist import apply_half_full_market_calibration
from pipeline.model import half_full_probabilities, half_full_probabilities_split
from tools.backtest_half_full import (
    SELECTIONS,
    actual_half_full,
    archived_forecasts,
    load_settlements,
    parse_datetime,
    settlement_key,
)

HISTORY = ROOT / "public" / "data" / "history"
SETTLEMENTS = ROOT / "public" / "data" / "settlements.json"
OUTPUT = ROOT / "artifacts" / "half-full-evidence-optimization-2026.json"
POLICY = ROOT / "pipeline" / "data" / "final-sprint-policy.json"


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"matches": 0}
    return {
        "matches": len(rows),
        "top1Hits": sum(row["top1"] for row in rows),
        "top3Hits": sum(row["top3"] for row in rows),
        "averageLogLoss": sum(row["logLoss"] for row in rows) / len(rows),
        "averageBrier": sum(row["brier"] for row in rows) / len(rows),
    }


def score(probabilities: dict[str, float], actual: str) -> dict[str, Any]:
    ranked = sorted(probabilities, key=probabilities.get, reverse=True)
    return {
        "top1": ranked[0] == actual,
        "top3": actual in ranked[:3],
        "logLoss": -math.log(max(probabilities.get(actual, 0.0), 1e-12)),
        "brier": sum((probabilities.get(key, 0.0) - (key == actual)) ** 2 for key in SELECTIONS),
        "predicted": ranked[0],
    }


def evaluate(
    half_life: float,
    shrinkage: float,
    cap: float,
    blend: float,
    half_score_scale: float,
    *,
    settlements: dict[str, dict[str, Any]] | None = None,
    ordered: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    settlements = settlements or load_settlements(SETTLEMENTS)
    if ordered is None:
        forecasts = archived_forecasts(HISTORY, settlements)
        ordered = sorted(forecasts.values(), key=lambda row: row["match"].get("kickoff") or "")
    evidence: list[EvidenceMatch] = []
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    for forecast in ordered:
        match = forecast["match"]
        match_id = settlement_key(match)
        settlement_match_id = str(forecast.get("settlementMatchId") or match_id)
        settlement = settlements[settlement_match_id]
        actual = actual_half_full(settlement)
        kickoff = parse_datetime(match.get("kickoff"))
        xg = match.get("expectedGoals") or {}
        if actual is None or kickoff is None or xg.get("home") is None or xg.get("away") is None:
            continue
        home_xg, away_xg = float(xg["home"]), float(xg["away"])
        baseline = apply_half_full_market_calibration(
            half_full_probabilities(home_xg, away_xg),
            {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}},
        ).probabilities
        seed = {
            "home_team": match.get("homeTeam"), "away_team": match.get("awayTeam"),
            "kickoff": kickoff.isoformat(), "base_xg": [home_xg, away_xg], "model_decomposition": {},
        }
        apply_current_tournament_evidence([seed], kickoff.date().isoformat(), evidence, settings={
            "halfLifeMatches": half_life, "shrinkage": shrinkage, "maxSideXgShift": 0.0,
            "halfFullEvidence": {
                "halfLifeMatches": half_life,
                "shrinkage": shrinkage,
                "maxFirstHalfXgShift": cap,
                "halfScoreResidualScale": half_score_scale,
            },
        })
        split = seed["tournament_evidence"]["halfFullEvidence"]
        first, second = split["firstHalfExpectedGoals"], split["secondHalfExpectedGoals"]
        split_candidate = apply_half_full_market_calibration(
            half_full_probabilities_split(first["home"], first["away"], second["home"], second["away"]),
            {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}},
        ).probabilities
        candidate = {key: (1.0 - blend) * baseline[key] + blend * split_candidate[key] for key in SELECTIONS}
        base_score, candidate_score = score(baseline, actual), score(candidate, actual)
        stage = "knockout" if kickoff.date().isoformat() >= "2026-06-28" else "group"
        baseline_rows.append({**base_score, "stage": stage})
        candidate_rows.append({**candidate_score, "stage": stage})
        match_rows.append({"matchId": match_id, "homeTeam": match.get("homeTeam"), "awayTeam": match.get("awayTeam"),
                           "kickoff": kickoff.isoformat(), "stage": stage, "actual": actual,
                           "baseline": base_score, "candidate": candidate_score, "halfFullEvidence": split})
        evidence.append(EvidenceMatch(
            match_id=match_id, kickoff=kickoff, home_team=str(match.get("homeTeam")), away_team=str(match.get("awayTeam")),
            home_xg=home_xg, away_xg=away_xg, home_goals=int(settlement["homeScore"]), away_goals=int(settlement["awayScore"]),
            extra_time_load=False, half_home_goals=int(settlement["halfTimeHomeScore"]), half_away_goals=int(settlement["halfTimeAwayScore"]),
        ))
    base_ko = [row for row in baseline_rows if row["stage"] == "knockout"]
    cand_ko = [row for row in candidate_rows if row["stage"] == "knockout"]
    late_start = (len(base_ko) + 1) // 2
    return {
        "settings": {
            "halfLifeMatches": half_life,
            "shrinkage": shrinkage,
            "maxFirstHalfXgShift": cap,
            "halfScoreResidualScale": half_score_scale,
            "blend": blend,
        },
        "baseline": {
            "all": metrics(baseline_rows),
            "knockout": metrics(base_ko),
            "lateKnockoutSegment": metrics(base_ko[late_start:]),
        },
        "candidate": {
            "all": metrics(candidate_rows),
            "knockout": metrics(cand_ko),
            "lateKnockoutSegment": metrics(cand_ko[late_start:]),
        },
        "matches": match_rows,
    }


def main() -> None:
    settlements = load_settlements(SETTLEMENTS)
    forecasts = archived_forecasts(HISTORY, settlements)
    ordered = sorted(forecasts.values(), key=lambda row: row["match"].get("kickoff") or "")
    candidates = [
        evaluate(
            half_life,
            shrinkage,
            cap,
            blend,
            half_score_scale,
            settlements=settlements,
            ordered=ordered,
        )
        for half_life in (1.5, 2.0, 3.0)
        for shrinkage in (3.0, 5.0, 8.0)
        for cap in (0.03, 0.05, 0.08)
        for half_score_scale in (0.15, 0.30, 0.45)
        for blend in (0.25, 0.50, 0.75, 1.0)
    ]
    baseline = candidates[0]["baseline"]
    for row in candidates:
        knockout = row["candidate"]["knockout"]
        row["properScoreIndexVsBaseline"] = 0.5 * (
            knockout["averageLogLoss"] / baseline["knockout"]["averageLogLoss"]
        ) + 0.5 * (
            knockout["averageBrier"] / baseline["knockout"]["averageBrier"]
        )
    eligible = [
        row for row in candidates
        if row["candidate"]["knockout"]["top1Hits"] >= baseline["knockout"]["top1Hits"]
        and row["candidate"]["knockout"]["top3Hits"] >= baseline["knockout"]["top3Hits"]
        and row["candidate"]["knockout"]["averageLogLoss"] < baseline["knockout"]["averageLogLoss"] - 1e-6
        and row["candidate"]["knockout"]["averageBrier"] < baseline["knockout"]["averageBrier"] - 1e-6
        and row["candidate"]["lateKnockoutSegment"]["top1Hits"] >= baseline["lateKnockoutSegment"]["top1Hits"]
        and row["candidate"]["lateKnockoutSegment"]["top3Hits"] >= baseline["lateKnockoutSegment"]["top3Hits"]
        and row["candidate"]["lateKnockoutSegment"]["averageLogLoss"] < baseline["lateKnockoutSegment"]["averageLogLoss"] - 1e-6
        and row["candidate"]["lateKnockoutSegment"]["averageBrier"] < baseline["lateKnockoutSegment"]["averageBrier"] - 1e-6
        and row["candidate"]["all"]["averageLogLoss"] <= baseline["all"]["averageLogLoss"] * 1.02
    ]
    selected = min(
        eligible,
        key=lambda row: (row["properScoreIndexVsBaseline"], -row["candidate"]["knockout"]["top1Hits"]),
    ) if eligible else None
    selection_reason = (
        "proper_scores_improved_and_late_segment_hit_gates_passed"
        if selected else "validation_gate_fallback_to_baseline_half_full"
    )
    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "objective": "opponent-strength-adjusted halftime-score temporal residual model",
        "leakagePolicy": "only matches with kickoff strictly before target kickoff",
        "grid": {
            "halfLifeMatches": [1.5, 2.0, 3.0],
            "shrinkage": [3.0, 5.0, 8.0],
            "maxFirstHalfXgShift": [0.03, 0.05, 0.08],
            "halfScoreResidualScale": [0.15, 0.30, 0.45],
            "blend": [0.25, 0.50, 0.75, 1.0],
        },
        "baseline": baseline,
        "selected": selected,
        "selectionReason": selection_reason,
        "candidatesEvaluated": len(candidates),
        "historicalSafetyGate": "not_available_for_half_time_scores",
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    selected_settings = selected["settings"] if selected else {
        "halfLifeMatches": 1.5,
        "shrinkage": 5.0,
        "maxFirstHalfXgShift": 0.0,
        "halfScoreResidualScale": 0.0,
        "blend": 0.0,
    }
    policy["halfFullEvidence"] = {
        "policy": "opponent_adjusted_half_split_v2",
        **selected_settings,
        "selectionReason": selection_reason,
        "validation": {
            "objective": payload["objective"],
            "leakagePolicy": payload["leakagePolicy"],
            "baseline": baseline,
            "selected": ({
                "settings": selected["settings"],
                "candidate": selected["candidate"],
                "properScoreIndexVsBaseline": selected["properScoreIndexVsBaseline"],
            } if selected else None),
            "candidatesEvaluated": len(candidates),
        },
    }
    POLICY.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "baseline": baseline,
        "selected": selected and {key: selected[key] for key in ("settings", "candidate", "properScoreIndexVsBaseline")},
        "selectionReason": selection_reason,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
