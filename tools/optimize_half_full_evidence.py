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


def evaluate(half_life: float, shrinkage: float, cap: float, blend: float) -> dict[str, Any]:
    settlements = load_settlements(SETTLEMENTS)
    forecasts = archived_forecasts(HISTORY, settlements)
    ordered = sorted(forecasts.values(), key=lambda row: row["match"].get("kickoff") or "")
    evidence: list[EvidenceMatch] = []
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    for forecast in ordered:
        match = forecast["match"]
        match_id = settlement_key(match)
        settlement = settlements[match_id]
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
            "halfFullEvidence": {"maxFirstHalfXgShift": cap},
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
    return {"settings": {"halfLifeMatches": half_life, "shrinkage": shrinkage, "maxFirstHalfXgShift": cap, "blend": blend},
            "baseline": {"all": metrics(baseline_rows), "knockout": metrics(base_ko)},
            "candidate": {"all": metrics(candidate_rows), "knockout": metrics(cand_ko)}, "matches": match_rows}


def main() -> None:
    candidates = [evaluate(half_life, shrinkage, cap, blend) for half_life in (1.5, 2.0, 3.0)
                  for shrinkage in (3.0, 5.0, 8.0) for cap in (0.05, 0.10, 0.15, 0.20)
                  for blend in (0.25, 0.50, 0.75, 1.0)]
    baseline = candidates[0]["baseline"]
    eligible = [row for row in candidates
                if row["candidate"]["knockout"]["top3Hits"] >= baseline["knockout"]["top3Hits"]
                and row["candidate"]["knockout"]["averageLogLoss"] < baseline["knockout"]["averageLogLoss"]
                and row["candidate"]["all"]["averageLogLoss"] <= baseline["all"]["averageLogLoss"] * 1.02]
    selected = min(eligible, key=lambda row: (row["candidate"]["knockout"]["averageLogLoss"],
                                               -row["candidate"]["knockout"]["top1Hits"])) if eligible else None
    payload = {"schemaVersion": 1, "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
               "objective": "opponent-adjusted first/second-half temporal residual model",
               "leakagePolicy": "only matches with kickoff strictly before target kickoff",
               "baseline": baseline, "selected": selected, "candidatesEvaluated": len(candidates)}
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": baseline, "selected": selected and {k: selected[k] for k in ("settings", "candidate")}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
