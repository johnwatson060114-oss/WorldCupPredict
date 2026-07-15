from __future__ import annotations

import math

from pipeline.outcome_calibration import (
    apply_outcome_probability_calibration,
    calibrate_outcome_probabilities,
)


def test_probability_calibration_is_normalized_deterministic_and_bounded() -> None:
    probabilities = {"home": 0.52, "draw": 0.27, "away": 0.21}
    settings = {
        "selectedTemperature": 0.7,
        "selectedDrawMultiplier": 1.3,
        "maxProbabilityShift": 0.06,
        "selectionReason": "test",
    }

    first = apply_outcome_probability_calibration(
        probabilities,
        {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}},
        settings=settings,
    )
    second = apply_outcome_probability_calibration(
        probabilities,
        {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}},
        settings=settings,
    )

    assert first.probabilities == second.probabilities
    assert math.isclose(sum(first.probabilities.values()), 1.0, abs_tol=1e-12)
    assert max(
        abs(first.probabilities[key] - probabilities[key])
        for key in probabilities
    ) <= 0.06 + 1e-12
    assert first.metadata["applied"] is True
    assert first.metadata["scoreMatrixChanged"] is False


def test_probability_calibration_is_disabled_outside_current_tournament() -> None:
    probabilities = {"home": 0.45, "draw": 0.30, "away": 0.25}
    result = apply_outcome_probability_calibration(
        probabilities,
        {},
        settings={
            "selectedTemperature": 0.7,
            "selectedDrawMultiplier": 1.3,
            "maxProbabilityShift": 0.06,
        },
    )

    assert result.probabilities == probabilities
    assert result.metadata["applied"] is False
    assert result.metadata["reason"] == "not_current_tournament_context"


def test_zero_shift_cap_is_a_fail_safe_noop() -> None:
    probabilities = {"home": 0.50, "draw": 0.30, "away": 0.20}
    calibrated = calibrate_outcome_probabilities(
        probabilities,
        temperature=0.7,
        draw_multiplier=1.3,
        max_probability_shift=0.0,
    )

    assert calibrated == probabilities
