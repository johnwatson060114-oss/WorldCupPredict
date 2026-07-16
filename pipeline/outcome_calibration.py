from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .final_sprint_policy import load_final_sprint_policy


OUTCOMES = ("home", "draw", "away")


@dataclass(frozen=True)
class OutcomeCalibrationResult:
    probabilities: dict[str, float]
    metadata: dict[str, Any]


def _normalize(probabilities: dict[str, float]) -> dict[str, float]:
    values = {key: max(0.0, float(probabilities.get(key, 0.0))) for key in OUTCOMES}
    total = sum(values.values())
    if total <= 0:
        return {key: 1.0 / len(OUTCOMES) for key in OUTCOMES}
    return {key: value / total for key, value in values.items()}


def calibrate_outcome_probabilities(
    probabilities: dict[str, float],
    *,
    temperature: float,
    draw_multiplier: float,
    max_probability_shift: float,
) -> dict[str, float]:
    """Calibrate W/D/L proper scores without changing the score matrix.

    The transform first adjusts the draw mass, then applies temperature scaling.
    A final linear blend back to the original distribution guarantees that no
    individual outcome moves farther than the validation-selected bound.
    """

    base = _normalize(probabilities)
    bounded_temperature = max(float(temperature), 1e-6)
    bounded_draw_multiplier = max(float(draw_multiplier), 0.0)
    weighted = {
        "home": base["home"],
        "draw": base["draw"] * bounded_draw_multiplier,
        "away": base["away"],
    }
    exponent = 1.0 / bounded_temperature
    powered = {key: value**exponent for key, value in weighted.items()}
    candidate = _normalize(powered)

    raw_max_shift = max(abs(candidate[key] - base[key]) for key in OUTCOMES)
    shift_cap = max(0.0, float(max_probability_shift))
    blend = min(1.0, shift_cap / raw_max_shift) if raw_max_shift > 0 else 1.0
    calibrated = {
        key: base[key] + blend * (candidate[key] - base[key])
        for key in OUTCOMES
    }
    return _normalize(calibrated)


def _validation_summary(validation: Any) -> dict[str, Any] | None:
    if not isinstance(validation, dict):
        return None
    selected = validation.get("selectedMetrics") or {}
    return {
        "validationWeights": validation.get("validationWeights"),
        "selectionObjective": validation.get("selectionObjective"),
        "selectionReason": validation.get("selectionReason"),
        "current2026": selected.get("current2026"),
        "current2026LateSegment": selected.get("current2026LateSegment") or selected.get("current2026LateHoldout"),
        "historical2018And2022": selected.get("historical2018And2022"),
        "historical2018": selected.get("historical2018"),
        "historical2022": selected.get("historical2022"),
    }


def apply_outcome_probability_calibration(
    probabilities: dict[str, float],
    seed: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
) -> OutcomeCalibrationResult:
    base = _normalize(probabilities)
    current_tournament_context = bool(
        seed.get("final_four_context")
        or seed.get("knockout_context")
        or seed.get("tournament_evidence")
        or seed.get("finalFourContext")
        or seed.get("knockoutContext")
        or seed.get("tournamentEvidence")
    )
    if not current_tournament_context:
        return OutcomeCalibrationResult(
            probabilities=base,
            metadata={
                "applied": False,
                "policy": "proper_score_outcome_calibration_v1",
                "reason": "not_current_tournament_context",
            },
        )

    policy = settings or load_final_sprint_policy().get("outcomeCalibration", {})
    temperature = float(policy.get("selectedTemperature", 1.0))
    draw_multiplier = float(policy.get("selectedDrawMultiplier", 1.0))
    max_probability_shift = float(policy.get("maxProbabilityShift", 0.0))
    calibrated = calibrate_outcome_probabilities(
        base,
        temperature=temperature,
        draw_multiplier=draw_multiplier,
        max_probability_shift=max_probability_shift,
    )
    max_shift = max(abs(calibrated[key] - base[key]) for key in OUTCOMES)
    applied = max_shift > 1e-12
    before_top = max(OUTCOMES, key=base.get)
    after_top = max(OUTCOMES, key=calibrated.get)

    return OutcomeCalibrationResult(
        probabilities=calibrated,
        metadata={
            "applied": applied,
            "policy": "proper_score_outcome_calibration_v1",
            "reason": None if applied else str(policy.get("selectionReason") or "validation_gate_fallback"),
            "temperature": temperature,
            "drawMultiplier": draw_multiplier,
            "maxProbabilityShift": max_probability_shift,
            "actualMaxProbabilityShift": round(max_shift, 6),
            "preCalibration": {key: round(base[key], 6) for key in OUTCOMES},
            "postCalibration": {key: round(calibrated[key], 6) for key in OUTCOMES},
            "topSelectionBefore": before_top,
            "topSelectionAfter": after_top,
            "topSelectionChanged": before_top != after_top,
            "scoreMatrixChanged": False,
            "validation": _validation_summary(policy.get("validation")),
        },
    )
