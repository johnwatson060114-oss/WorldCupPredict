from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


OUTCOME_KEYS = ("home", "draw", "away")
HALF_FULL_SELECTIONS = (
    "\u80dc\u80dc",
    "\u80dc\u5e73",
    "\u80dc\u8d1f",
    "\u5e73\u80dc",
    "\u5e73\u5e73",
    "\u5e73\u8d1f",
    "\u8d1f\u80dc",
    "\u8d1f\u5e73",
    "\u8d1f\u8d1f",
)
FULL_OUTCOME_BY_LABEL = {
    "\u80dc": "home",
    "\u5e73": "draw",
    "\u8d1f": "away",
}
DEFAULT_OUTCOME_ASSIST_WEIGHT = 0.20
KNOCKOUT_HALF_FULL_WEIGHTS = {
    "\u80dc\u80dc": 0.95,
    "\u80dc\u5e73": 1.30,
    "\u80dc\u8d1f": 1.30,
    "\u5e73\u80dc": 1.20,
    "\u5e73\u5e73": 0.95,
    "\u5e73\u8d1f": 1.20,
    "\u8d1f\u80dc": 1.30,
    "\u8d1f\u5e73": 1.30,
    "\u8d1f\u8d1f": 0.95,
}


@dataclass(frozen=True)
class HalfFullSignal:
    half_full_probabilities: dict[str, float]
    outcome_signal: dict[str, float]
    assisted_outcomes: dict[str, float]
    metadata: dict[str, object]


@dataclass(frozen=True)
class HalfFullMarketCalibration:
    probabilities: dict[str, float]
    metadata: dict[str, object]


def normalize_distribution(probabilities: Mapping[str, float], keys: tuple[str, ...]) -> dict[str, float]:
    values = {key: max(0.0, float(probabilities.get(key, 0.0))) for key in keys}
    total = sum(values.values())
    if total <= 0:
        return {key: 1 / len(keys) for key in keys}
    return {key: value / total for key, value in values.items()}


def apply_half_full_market_calibration(
    half_full: Mapping[str, float],
    seed: Mapping[str, object] | None = None,
) -> HalfFullMarketCalibration:
    normalized = normalize_distribution(half_full, HALF_FULL_SELECTIONS)
    seed = seed or {}
    knockout_context = (
        seed.get("knockout_context")
        or seed.get("knockoutContext")
        or seed.get("tournament_evidence")
        or seed.get("tournamentEvidence")
    )
    if not knockout_context:
        return HalfFullMarketCalibration(
            probabilities=normalized,
            metadata={"applied": False, "reason": "not_knockout"},
        )

    weighted = {
        selection: normalized[selection] * KNOCKOUT_HALF_FULL_WEIGHTS[selection]
        for selection in HALF_FULL_SELECTIONS
    }
    calibrated = normalize_distribution(weighted, HALF_FULL_SELECTIONS)
    top_before = max(normalized, key=normalized.get)
    top_after = max(calibrated, key=calibrated.get)

    return HalfFullMarketCalibration(
        probabilities=calibrated,
        metadata={
            "applied": True,
            "policy": "current_tournament_half_full_late_swing_v3",
            "sourceKnockoutPolicy": (
                knockout_context.get("policy")
                if isinstance(knockout_context, Mapping)
                else None
            ),
            "weights": KNOCKOUT_HALF_FULL_WEIGHTS,
            "topSelectionBefore": top_before,
            "topSelectionAfter": top_after,
            "topProbabilityBefore": normalized[top_before],
            "topProbabilityAfter": calibrated[top_after],
        },
    )


def apply_opponent_adjusted_half_split(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    seed: Mapping[str, object] | None,
    blend: float,
) -> HalfFullMarketCalibration:
    baseline_calibration = apply_half_full_market_calibration(baseline, seed)
    candidate_calibration = apply_half_full_market_calibration(candidate, seed)
    bounded_blend = min(1.0, max(0.0, float(blend)))
    probabilities = normalize_distribution({
        key: (1.0 - bounded_blend) * baseline_calibration.probabilities[key]
        + bounded_blend * candidate_calibration.probabilities[key]
        for key in HALF_FULL_SELECTIONS
    }, HALF_FULL_SELECTIONS)
    return HalfFullMarketCalibration(
        probabilities=probabilities,
        metadata={
            "applied": bounded_blend > 0,
            "policy": "opponent_adjusted_half_split_v1",
            "blend": bounded_blend,
            "baselineCalibration": baseline_calibration.metadata,
            "candidateCalibration": candidate_calibration.metadata,
            "topSelectionBefore": max(baseline_calibration.probabilities, key=baseline_calibration.probabilities.get),
            "topSelectionAfter": max(probabilities, key=probabilities.get),
        },
    )


def half_full_to_outcomes(half_full: Mapping[str, float]) -> dict[str, float]:
    normalized = normalize_distribution(half_full, HALF_FULL_SELECTIONS)
    outcomes = {key: 0.0 for key in OUTCOME_KEYS}
    for selection, probability in normalized.items():
        full_label = selection[1]
        outcomes[FULL_OUTCOME_BY_LABEL[full_label]] += probability
    return outcomes


def blend_outcomes(
    base_outcomes: Mapping[str, float],
    auxiliary_outcomes: Mapping[str, float],
    weight: float = DEFAULT_OUTCOME_ASSIST_WEIGHT,
) -> dict[str, float]:
    bounded_weight = min(1.0, max(0.0, weight))
    base = normalize_distribution(base_outcomes, OUTCOME_KEYS)
    auxiliary = normalize_distribution(auxiliary_outcomes, OUTCOME_KEYS)
    blended = {
        key: (1 - bounded_weight) * base[key] + bounded_weight * auxiliary[key]
        for key in OUTCOME_KEYS
    }
    return normalize_distribution(blended, OUTCOME_KEYS)


def build_half_full_signal(
    half_full: Mapping[str, float],
    base_outcomes: Mapping[str, float],
    weight: float = DEFAULT_OUTCOME_ASSIST_WEIGHT,
) -> HalfFullSignal:
    normalized_half_full = normalize_distribution(half_full, HALF_FULL_SELECTIONS)
    outcome_signal = half_full_to_outcomes(normalized_half_full)
    assisted = blend_outcomes(base_outcomes, outcome_signal, weight)
    base = normalize_distribution(base_outcomes, OUTCOME_KEYS)
    deltas = {key: assisted[key] - base[key] for key in OUTCOME_KEYS}
    max_delta = max(abs(value) for value in deltas.values())
    top_half_full = max(normalized_half_full, key=normalized_half_full.get)

    return HalfFullSignal(
        half_full_probabilities=normalized_half_full,
        outcome_signal=outcome_signal,
        assisted_outcomes=assisted,
        metadata={
            "applied": True,
            "policy": "half_full_specialist_v1",
            "role": "auxiliary_wdl_calibration",
            "assistWeight": weight,
            "topHalfFullSelection": top_half_full,
            "topHalfFullProbability": normalized_half_full[top_half_full],
            "outcomeSignal": outcome_signal,
            "outcomeDelta": deltas,
            "maxOutcomeDelta": max_delta,
            "note": (
                "Aggregates the specialist half-time/full-time distribution into "
                "a conservative W/D/L calibration signal."
            ),
        },
    )
