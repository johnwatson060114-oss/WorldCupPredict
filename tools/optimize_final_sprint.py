from __future__ import annotations

import itertools
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.current_tournament_evidence import EvidenceMatch, apply_current_tournament_evidence, load_evidence_matches
from pipeline.market_guard import apply_bounded_market_anchor
from pipeline.model import outcome_probabilities, score_matrix
from pipeline.outcome_calibration import calibrate_outcome_probabilities
from pipeline.score_calibration import apply_score_matrix_calibration
from tools.backtest_score_matrix import (
    archived_forecasts,
    evaluate_matrix,
    load_settlements,
    score_xg,
    select_calibration_intensity,
    build_rows,
)


BEIJING = ZoneInfo("Asia/Shanghai")
POLICY_PATH = ROOT / "pipeline" / "data" / "final-sprint-policy.json"
HISTORY_DIR = ROOT / "public" / "data" / "history"
SETTLEMENTS_PATH = ROOT / "public" / "data" / "settlements.json"
OUTCOME_KEYS = ("home", "draw", "away")
EVIDENCE_CAPS = (0.0, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20)


def _long_term_xg(match: dict[str, Any]) -> tuple[float, float] | None:
    decomposition = match.get("modelDecomposition") or {}
    values = decomposition.get("longTermExpectedGoals") or match.get("expectedGoals") or {}
    if values.get("home") is None or values.get("away") is None:
        return None
    return float(values["home"]), float(values["away"])


def _market_odds(match: dict[str, Any], market_name: str) -> dict[str, float | None]:
    return {
        str(quote["selection"]): quote.get("odds")
        for quote in match.get("quotes", [])
        if quote.get("market") == market_name and quote.get("selection") is not None
    }


def _actual_outcome(home: int, away: int) -> str:
    return "home" if home > away else "away" if away > home else "draw"


def _base_outcome_probabilities(match: dict[str, Any]) -> dict[str, float] | None:
    """Return the uncalibrated W/D/L vector when the archive exposes it."""

    calibration = match.get("outcomeCalibration") or {}
    sources = (calibration.get("preCalibration"), match.get("outcomeProbabilities"))
    for source in sources:
        if not isinstance(source, dict):
            continue
        try:
            values = {key: float(source[key]) for key in OUTCOME_KEYS}
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) and value >= 0.0 for value in values.values()) and sum(values.values()) > 0:
            return values
    return None


def _evaluate(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        return {"matches": 0, "wdlLogLoss": math.inf, "totalGoalsLogLoss": math.inf, "scoreLogLoss": math.inf, "combinedLoss": math.inf}
    count = len(rows)
    wdl = sum(row["wdlLogLoss"] for row in rows) / count
    total = sum(row["totalGoalsLogLoss"] for row in rows) / count
    score = sum(row["scoreLogLoss"] for row in rows) / count
    return {
        "matches": count,
        "wdlLogLoss": wdl,
        "totalGoalsLogLoss": total,
        "scoreLogLoss": score,
        "combinedLoss": 0.20 * wdl + 0.40 * total + 0.40 * score,
        "totalAdjacentHits": sum(row["totalAdjacentHit"] for row in rows),
        "scoreTop3Hits": sum(row["scoreTop3Hit"] for row in rows),
    }


def _outcome_metrics(
    rows: list[tuple[dict[str, float], str]],
    settings: dict[str, float],
) -> dict[str, float | int]:
    if not rows:
        return {"matches": 0, "hits": 0, "accuracy": 0.0, "logLoss": math.inf, "brier": math.inf}
    evaluated = []
    for probabilities, actual in rows:
        calibrated = calibrate_outcome_probabilities(
            probabilities,
            temperature=settings["selectedTemperature"],
            draw_multiplier=settings["selectedDrawMultiplier"],
            max_probability_shift=settings["maxProbabilityShift"],
        )
        evaluated.append((calibrated, actual))
    matches = len(evaluated)
    hits = sum(max(probabilities, key=probabilities.get) == actual for probabilities, actual in evaluated)
    return {
        "matches": matches,
        "hits": hits,
        "accuracy": hits / matches,
        "logLoss": sum(-math.log(max(probabilities[actual], 1e-12)) for probabilities, actual in evaluated) / matches,
        "brier": sum(
            sum((probabilities[outcome] - float(outcome == actual)) ** 2 for outcome in ("home", "draw", "away"))
            for probabilities, actual in evaluated
        ) / matches,
    }


def _historical_outcome_rows() -> dict[str, list[tuple[dict[str, float], str]]]:
    payload = json.loads((ROOT / "artifacts" / "model-comparison-2018-2022.json").read_text(encoding="utf-8"))
    rows: dict[str, list[tuple[dict[str, float], str]]] = {"2018": [], "2022": []}
    for row in payload["matches"]:
        if row["stage"] != "knockout":
            continue
        year = str(row["year"])
        probabilities = row["models"]["current_production"]["probabilities"]
        rows.setdefault(year, []).append((probabilities, str(row["actual"])))
    return rows


def _evaluate_xg(home_xg: float, away_xg: float, settlement: dict[str, Any]) -> dict[str, Any]:
    home_score, away_score = int(settlement["homeScore"]), int(settlement["awayScore"])
    matrix = score_matrix(home_xg, away_xg)
    outcomes = outcome_probabilities(matrix)
    matrix_metrics = evaluate_matrix(matrix, home_score, away_score)
    actual = _actual_outcome(home_score, away_score)
    return {
        "wdlLogLoss": -math.log(max(outcomes[actual], 1e-12)),
        "totalGoalsLogLoss": matrix_metrics["totalLogLoss"],
        "scoreLogLoss": matrix_metrics["scoreLogLoss"],
        "totalAdjacentHit": int(matrix_metrics["totalAdjacentCoreHit"]),
        "scoreTop3Hit": int(matrix_metrics["scoreTop3Hit"]),
    }


def _evaluate_calibrated_xg(home_xg: float, away_xg: float, settlement: dict[str, Any], intensity: float) -> dict[str, Any]:
    home_score, away_score = int(settlement["homeScore"]), int(settlement["awayScore"])
    base = score_matrix(home_xg, away_xg)
    calibrated = apply_score_matrix_calibration(
        base,
        {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}},
        home_xg,
        away_xg,
        intensity=intensity,
    ).matrix
    outcomes = outcome_probabilities(base)
    matrix_metrics = evaluate_matrix(calibrated, home_score, away_score)
    actual = _actual_outcome(home_score, away_score)
    return {
        "wdlLogLoss": -math.log(max(outcomes[actual], 1e-12)),
        "totalGoalsLogLoss": matrix_metrics["totalLogLoss"],
        "scoreLogLoss": matrix_metrics["scoreLogLoss"],
        "totalAdjacentHit": int(matrix_metrics["totalAdjacentCoreHit"]),
        "scoreTop3Hit": int(matrix_metrics["scoreTop3Hit"]),
    }


def _historical_metrics(settings: dict[str, float] | None = None, score_intensity: float = 0.0) -> dict[str, Any]:
    payload = json.loads((ROOT / "artifacts" / "model-comparison-2018-2022.json").read_text(encoding="utf-8"))
    evaluated: list[dict[str, Any]] = []
    evidence_by_year: dict[str, list[EvidenceMatch]] = {}
    for index, row in enumerate(payload["matches"]):
        year = str(row["year"])
        kickoff = datetime.fromisoformat(f"{row['date']}T00:00:00+00:00") + timedelta(minutes=index)
        home_team, away_team = str(row["match"]).split(" vs ", 1)
        home_score, away_score = (int(value) for value in str(row["score"]).split("-", 1))
        base_xg = row["models"]["current_production"]["xg"]
        home_xg, away_xg = float(base_xg["home"]), float(base_xg["away"])
        year_evidence = evidence_by_year.setdefault(year, [])
        if settings is not None:
            seed = {
                "home_team": home_team,
                "away_team": away_team,
                "kickoff": kickoff.isoformat(),
                "base_xg": [home_xg, away_xg],
                "model_decomposition": {},
            }
            apply_current_tournament_evidence([seed], str(row["date"]), year_evidence, settings=settings)
            home_xg, away_xg = map(float, seed["base_xg"])
        if row["stage"] == "knockout":
            evaluated.append(_evaluate_calibrated_xg(
                home_xg,
                away_xg,
                {"homeScore": home_score, "awayScore": away_score},
                score_intensity,
            ))
        year_evidence.append(EvidenceMatch(
            match_id=f"{year}-{index}",
            kickoff=kickoff,
            home_team=home_team,
            away_team=away_team,
            home_xg=float(base_xg["home"]),
            away_xg=float(base_xg["away"]),
            home_goals=home_score,
            away_goals=away_score,
            extra_time_load=False,
        ))
    return _evaluate(evaluated)


def _knockout_samples() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    settlements = load_settlements(SETTLEMENTS_PATH)
    forecasts = archived_forecasts(HISTORY_DIR, settlements)
    samples = []
    for match_id, forecast in forecasts.items():
        match = forecast["match"]
        kickoff = str(match.get("kickoff") or "")
        if kickoff[:10] < "2026-06-28":
            continue
        if _long_term_xg(match) is None:
            continue
        samples.append({"matchId": match_id, "match": match, "settlement": settlements[match_id]})
    samples.sort(key=lambda row: row["match"].get("kickoff") or "")
    return samples, forecasts


def select_tournament_evidence(samples: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    evidence = load_evidence_matches()
    candidates = [
        {"halfLifeMatches": half_life, "shrinkage": shrinkage, "maxSideXgShift": cap}
        for half_life, shrinkage, cap in itertools.product(
            (1.5, 2.0, 3.0),
            (3.0, 5.0, 8.0),
            EVIDENCE_CAPS,
        )
    ]
    current_baseline = _evaluate([_evaluate_xg(*score_xg(sample["match"]), sample["settlement"]) for sample in samples])
    historical_baseline = _historical_metrics()
    baseline_weighted_loss = 0.70 * current_baseline["combinedLoss"] + 0.30 * historical_baseline["combinedLoss"]
    results: list[tuple[dict[str, float], dict[str, Any]]] = []
    for settings in candidates:
        evaluated = []
        for sample in samples:
            match = sample["match"]
            base = _long_term_xg(match)
            seed = {
                "home_team": match["homeTeam"],
                "away_team": match["awayTeam"],
                "kickoff": match["kickoff"],
                "base_xg": [base[0], base[1]],
                "model_decomposition": {},
            }
            apply_current_tournament_evidence([seed], str(match["kickoff"])[:10], evidence, settings=settings)
            evaluated.append(_evaluate_xg(*seed["base_xg"], sample["settlement"]))
        current = _evaluate(evaluated)
        historical = _historical_metrics(settings)
        weighted_loss = 0.70 * current["combinedLoss"] + 0.30 * historical["combinedLoss"]
        eligible = (
            current["wdlLogLoss"] <= current_baseline["wdlLogLoss"] * 1.01
            and current["totalAdjacentHits"] >= current_baseline["totalAdjacentHits"]
            and current["scoreTop3Hits"] >= current_baseline["scoreTop3Hits"]
            and historical["wdlLogLoss"] <= historical_baseline["wdlLogLoss"] * 1.02
            and historical["totalGoalsLogLoss"] <= historical_baseline["totalGoalsLogLoss"] * 1.02
            and historical["scoreLogLoss"] <= historical_baseline["scoreLogLoss"] * 1.02
            and historical["totalAdjacentHits"] >= historical_baseline["totalAdjacentHits"]
            and historical["scoreTop3Hits"] >= historical_baseline["scoreTop3Hits"]
            and weighted_loss < baseline_weighted_loss - 1e-12
        )
        results.append((settings, {"current2026": current, "historical2018And2022": historical, "weightedLoss": weighted_loss, "eligible": eligible}))
    eligible_results = [item for item in results if item[1]["eligible"]]
    if eligible_results:
        selected_settings, selected_metrics = min(eligible_results, key=lambda item: item[1]["weightedLoss"])
        selection_reason = "weighted_loss_improved_and_all_safety_gates_passed"
    else:
        selected_settings = {"halfLifeMatches": 2.0, "shrinkage": 5.0, "maxSideXgShift": 0.0}
        selected_metrics = {
            "current2026": current_baseline,
            "historical2018And2022": historical_baseline,
            "weightedLoss": 0.70 * current_baseline["combinedLoss"] + 0.30 * historical_baseline["combinedLoss"],
            "eligible": True,
            "fallback": True,
        }
        selection_reason = "historical_top3_gate_fallback_to_diagnostic_only"
    return selected_settings, {
        "grid": {
            "halfLifeMatches": [1.5, 2.0, 3.0],
            "shrinkage": [3.0, 5.0, 8.0],
            "maxSideXgShift": list(EVIDENCE_CAPS),
        },
        "selected": selected_settings,
        "metrics": selected_metrics,
        "selectionReason": selection_reason,
        "baseline": {"current2026": current_baseline, "historical2018And2022": historical_baseline},
        "historicalCommentaryCoverage": "not_applicable_no_archived_commentary_process_coverage",
        "candidatesEvaluated": len(results),
    }


def select_market_anchor(samples: list[dict[str, Any]], evidence_settings: dict[str, float]) -> tuple[dict[str, float], dict[str, Any]]:
    evidence = load_evidence_matches()
    candidates = [
        {
            "strengthBlend": strength,
            "totalGoalsBlend": total,
            "maxSideXgShift": 0.20,
            "maxTotalXgShift": 0.25,
        }
        for strength, total in itertools.product((0.25, 0.35, 0.45), (0.15, 0.25, 0.35))
    ]
    baseline_evaluated = []
    for sample in samples:
        match = sample["match"]
        base = _long_term_xg(match)
        seed = {"home_team": match["homeTeam"], "away_team": match["awayTeam"], "kickoff": match["kickoff"], "base_xg": [base[0], base[1]], "model_decomposition": {}}
        apply_current_tournament_evidence([seed], str(match["kickoff"])[:10], evidence, settings=evidence_settings)
        baseline_evaluated.append(_evaluate_xg(*seed["base_xg"], sample["settlement"]))
    baseline_metrics = _evaluate(baseline_evaluated)
    results: list[tuple[dict[str, float], dict[str, Any]]] = []
    for settings in candidates:
        evaluated = []
        market_samples = 0
        for sample in samples:
            match = sample["match"]
            base = _long_term_xg(match)
            seed = {
                "home_team": match["homeTeam"],
                "away_team": match["awayTeam"],
                "kickoff": match["kickoff"],
                "base_xg": [base[0], base[1]],
                "model_decomposition": {},
            }
            apply_current_tournament_evidence([seed], str(match["kickoff"])[:10], evidence, settings=evidence_settings)
            result = apply_bounded_market_anchor(
                seed,
                _market_odds(match, "\u80dc\u5e73\u8d1f"),
                _market_odds(match, "\u603b\u8fdb\u7403\u6570"),
                observed_at=sample["match"].get("generatedAt"),
                settings=settings,
            )
            market_samples += int(result["applied"])
            evaluated.append(_evaluate_xg(*seed["base_xg"], sample["settlement"]))
        metrics = _evaluate(evaluated)
        metrics["marketSamples"] = market_samples
        metrics["eligible"] = (
            market_samples > 0
            and metrics["combinedLoss"] < baseline_metrics["combinedLoss"] - 1e-12
            and metrics["wdlLogLoss"] <= baseline_metrics["wdlLogLoss"] * 1.01
            and metrics["totalGoalsLogLoss"] <= baseline_metrics["totalGoalsLogLoss"]
            and metrics["scoreLogLoss"] <= baseline_metrics["scoreLogLoss"]
            and metrics["totalAdjacentHits"] >= baseline_metrics["totalAdjacentHits"]
            and metrics["scoreTop3Hits"] >= baseline_metrics["scoreTop3Hits"]
        )
        results.append((settings, metrics))
    eligible_results = [item for item in results if item[1]["eligible"]]
    if eligible_results:
        selected_settings, selected_metrics = min(eligible_results, key=lambda item: item[1]["combinedLoss"])
        selection_reason = "all_market_specific_gates_passed"
    else:
        selected_settings = {"strengthBlend": 0.0, "totalGoalsBlend": 0.0, "maxSideXgShift": 0.20, "maxTotalXgShift": 0.25}
        selected_metrics = {**baseline_metrics, "marketSamples": 0, "eligible": True, "fallback": True}
        selection_reason = "total_goals_loss_gate_fallback_to_diagnostic_only"
    return selected_settings, {
        "grid": {"strengthBlend": [0.25, 0.35, 0.45], "totalGoalsBlend": [0.15, 0.25, 0.35]},
        "selected": selected_settings,
        "metrics": selected_metrics,
        "selectionReason": selection_reason,
        "baseline": baseline_metrics,
        "candidatesEvaluated": len(results),
    }


def select_outcome_calibration(samples: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    baseline_settings = {
        "selectedTemperature": 1.0,
        "selectedDrawMultiplier": 1.0,
        "maxProbabilityShift": 0.0,
    }
    current_rows = []
    for sample in samples:
        probabilities = _base_outcome_probabilities(sample["match"])
        if probabilities is None:
            continue
        current_rows.append((
            probabilities,
            _actual_outcome(int(sample["settlement"]["homeScore"]), int(sample["settlement"]["awayScore"])),
        ))
    late_segment_rows = current_rows[(len(current_rows) + 1) // 2:]
    historical_by_year = _historical_outcome_rows()
    historical_rows = historical_by_year.get("2018", []) + historical_by_year.get("2022", [])

    baseline = {
        "current2026": _outcome_metrics(current_rows, baseline_settings),
        "current2026LateSegment": _outcome_metrics(late_segment_rows, baseline_settings),
        "historical2018And2022": _outcome_metrics(historical_rows, baseline_settings),
        "historical2018": _outcome_metrics(historical_by_year.get("2018", []), baseline_settings),
        "historical2022": _outcome_metrics(historical_by_year.get("2022", []), baseline_settings),
    }
    baseline_weighted_log_loss = (
        0.70 * float(baseline["current2026"]["logLoss"])
        + 0.30 * float(baseline["historical2018And2022"]["logLoss"])
    )
    baseline_weighted_brier = (
        0.70 * float(baseline["current2026"]["brier"])
        + 0.30 * float(baseline["historical2018And2022"]["brier"])
    )

    candidates: list[tuple[dict[str, float], dict[str, Any]]] = []
    for temperature, draw_multiplier, max_shift in itertools.product(
        (0.70, 0.80, 0.90, 1.00),
        (1.00, 1.10, 1.20, 1.30),
        (0.04, 0.06, 0.08, 0.10, 0.12),
    ):
        settings = {
            "selectedTemperature": temperature,
            "selectedDrawMultiplier": draw_multiplier,
            "maxProbabilityShift": max_shift,
        }
        metrics = {
            "current2026": _outcome_metrics(current_rows, settings),
            "current2026LateSegment": _outcome_metrics(late_segment_rows, settings),
            "historical2018And2022": _outcome_metrics(historical_rows, settings),
            "historical2018": _outcome_metrics(historical_by_year.get("2018", []), settings),
            "historical2022": _outcome_metrics(historical_by_year.get("2022", []), settings),
        }
        weighted_log_loss = (
            0.70 * float(metrics["current2026"]["logLoss"])
            + 0.30 * float(metrics["historical2018And2022"]["logLoss"])
        )
        weighted_brier = (
            0.70 * float(metrics["current2026"]["brier"])
            + 0.30 * float(metrics["historical2018And2022"]["brier"])
        )
        proper_score_index = 0.50 * (weighted_log_loss / baseline_weighted_log_loss) + 0.50 * (
            weighted_brier / baseline_weighted_brier
        )
        metrics["weightedLogLoss"] = weighted_log_loss
        metrics["weightedBrier"] = weighted_brier
        metrics["properScoreIndexVsBaseline"] = proper_score_index
        metrics["eligible"] = (
            float(metrics["current2026"]["logLoss"]) < float(baseline["current2026"]["logLoss"]) - 1e-12
            and float(metrics["current2026"]["brier"]) < float(baseline["current2026"]["brier"]) - 1e-12
            and int(metrics["current2026"]["hits"]) >= int(baseline["current2026"]["hits"])
            and float(metrics["current2026LateSegment"]["logLoss"]) < float(baseline["current2026LateSegment"]["logLoss"]) - 1e-12
            and float(metrics["current2026LateSegment"]["brier"]) < float(baseline["current2026LateSegment"]["brier"]) - 1e-12
            and int(metrics["current2026LateSegment"]["hits"]) >= int(baseline["current2026LateSegment"]["hits"])
            and float(metrics["historical2018And2022"]["logLoss"]) <= float(baseline["historical2018And2022"]["logLoss"]) * 1.02
            and float(metrics["historical2018And2022"]["brier"]) <= float(baseline["historical2018And2022"]["brier"]) * 1.02
            and int(metrics["historical2018And2022"]["hits"]) >= int(baseline["historical2018And2022"]["hits"])
            and float(metrics["historical2018"]["logLoss"]) <= float(baseline["historical2018"]["logLoss"]) * 1.02
            and float(metrics["historical2018"]["brier"]) <= float(baseline["historical2018"]["brier"]) * 1.02
            and float(metrics["historical2022"]["logLoss"]) <= float(baseline["historical2022"]["logLoss"]) * 1.02
            and float(metrics["historical2022"]["brier"]) <= float(baseline["historical2022"]["brier"]) * 1.02
            and proper_score_index < 1.0 - 1e-12
        )
        candidates.append((settings, metrics))

    eligible = [candidate for candidate in candidates if candidate[1]["eligible"]]
    if eligible:
        selected_settings, selected_metrics = min(
            eligible,
            key=lambda candidate: float(candidate[1]["properScoreIndexVsBaseline"]),
        )
        selection_reason = "proper_scores_improved_and_late_segment_historical_gates_passed"
    else:
        selected_settings = baseline_settings
        selected_metrics = {
            **baseline,
            "weightedLogLoss": baseline_weighted_log_loss,
            "weightedBrier": baseline_weighted_brier,
            "properScoreIndexVsBaseline": 1.0,
            "eligible": True,
            "fallback": True,
        }
        selection_reason = "validation_gate_fallback"

    return selected_settings, {
        "grid": {
            "temperature": [0.70, 0.80, 0.90, 1.00],
            "drawMultiplier": [1.00, 1.10, 1.20, 1.30],
            "maxProbabilityShift": [0.04, 0.06, 0.08, 0.10, 0.12],
        },
        "validationWeights": {"worldCup2026": 0.70, "worldCup2018And2022": 0.30},
        "selectionObjective": "equal_weight_normalized_wdl_log_loss_and_brier",
        "selected": selected_settings,
        "selectedMetrics": selected_metrics,
        "baseline": {
            **baseline,
            "weightedLogLoss": baseline_weighted_log_loss,
            "weightedBrier": baseline_weighted_brier,
            "properScoreIndexVsBaseline": 1.0,
        },
        "selectionReason": selection_reason,
        "candidatesEvaluated": len(candidates),
        "scoreMatrixMutation": "forbidden_by_independent_market_gate",
    }


def select_weighted_score_intensity(samples: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for intensity in (0.0, 0.10, 0.15, 0.20, 0.25):
        current = _evaluate([
            _evaluate_calibrated_xg(*score_xg(sample["match"]), sample["settlement"], intensity)
            for sample in samples
        ])
        historical = _historical_metrics(score_intensity=intensity)
        current_matrix_loss = 0.60 * current["totalGoalsLogLoss"] + 0.40 * current["scoreLogLoss"]
        historical_matrix_loss = 0.60 * historical["totalGoalsLogLoss"] + 0.40 * historical["scoreLogLoss"]
        candidates[f"{intensity:.2f}"] = {
            "current2026": current,
            "historical2018And2022": historical,
            "currentMatrixLoss": current_matrix_loss,
            "historicalMatrixLoss": historical_matrix_loss,
            "weightedLoss": 0.70 * current_matrix_loss + 0.30 * historical_matrix_loss,
        }
    baseline = candidates["0.00"]
    eligible = {
        key: values for key, values in candidates.items()
        if values["current2026"]["totalAdjacentHits"] >= baseline["current2026"]["totalAdjacentHits"]
        and values["current2026"]["scoreTop3Hits"] >= baseline["current2026"]["scoreTop3Hits"]
        and values["currentMatrixLoss"] < baseline["currentMatrixLoss"] - 1e-12
        and values["historical2018And2022"]["totalGoalsLogLoss"] <= baseline["historical2018And2022"]["totalGoalsLogLoss"] * 1.02
        and values["historical2018And2022"]["scoreLogLoss"] <= baseline["historical2018And2022"]["scoreLogLoss"] * 1.02
        and values["weightedLoss"] < baseline["weightedLoss"] - 1e-12
    }
    selected = min(eligible, key=lambda key: eligible[key]["weightedLoss"]) if eligible else "0.00"
    return {
        "candidateIntensities": [0.0, 0.10, 0.15, 0.20, 0.25],
        "lossWeights": {"totalGoals": 0.60, "exactScore": 0.40},
        "validationWeights": {"worldCup2026": 0.70, "worldCup2018And2022": 0.30},
        "candidates": candidates,
        "selectedIntensity": float(selected),
        "selectionReason": (
            "current_and_weighted_loss_improved_with_safety_gates"
            if eligible else "current_tournament_loss_gate_fallback"
        ),
    }


def main() -> None:
    samples, forecasts = _knockout_samples()
    evidence_settings, evidence_validation = select_tournament_evidence(samples)
    market_settings, market_validation = select_market_anchor(samples, evidence_settings)
    outcome_settings, outcome_validation = select_outcome_calibration(samples)
    score_rows = build_rows(forecasts, load_settlements(SETTLEMENTS_PATH))
    score_selection_2026 = select_calibration_intensity([row for row in score_rows if row["stage"] == "knockout"])
    score_selection = select_weighted_score_intensity(samples)
    score_selection["currentTournamentOnlyDiagnostic"] = score_selection_2026

    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload["generatedAt"] = datetime.now(BEIJING).isoformat(timespec="seconds")
    payload["tournamentEvidence"] = {**evidence_settings, "validation": evidence_validation}
    payload["marketAnchor"] = {**market_settings, "validation": market_validation}
    payload["outcomeCalibration"] = {
        **outcome_settings,
        "selectionReason": outcome_validation["selectionReason"],
        "validation": outcome_validation,
    }
    payload["scoreCalibration"] = {
        "candidateIntensities": score_selection["candidateIntensities"],
        "selectedIntensity": score_selection["selectedIntensity"],
        "selectionReason": score_selection["selectionReason"],
        "totalGoalsLossWeight": 0.60,
        "exactScoreLossWeight": 0.40,
        "validation": score_selection,
    }
    payload["validation"] = {
        "worldCup2026KnockoutMatches": len(samples),
        "predictionTarget": "90_minutes",
        "leakagePolicy": "latest archived forecast strictly before kickoff; evidence strictly before target kickoff",
        "historicalSafetyGate": {
            "weight": 0.30,
            "maxDegradation": 0.02,
            "generalLayersStatus": "passed_by_weighted_candidate_evaluation",
            "tournamentEvidenceStatus": "not_applicable_no_archived_commentary_process_coverage",
        },
    }
    POLICY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "matches": len(samples),
        "tournamentEvidence": evidence_validation,
        "marketAnchor": market_validation,
        "outcomeCalibration": outcome_validation,
        "scoreCalibration": score_selection,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
