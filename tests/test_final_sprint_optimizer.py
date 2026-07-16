from __future__ import annotations

from pipeline.outcome_calibration import calibrate_outcome_probabilities
from tools.optimize_final_sprint import _base_outcome_probabilities


def test_outcome_optimizer_uses_precalibration_vector_once():
    pre = {"home": 0.26, "draw": 0.26, "away": 0.48}
    published = calibrate_outcome_probabilities(
        pre,
        temperature=0.7,
        draw_multiplier=1.3,
        max_probability_shift=0.06,
    )
    match = {
        "outcomeProbabilities": published,
        "outcomeCalibration": {"preCalibration": pre},
    }

    base = _base_outcome_probabilities(match)

    assert base == pre
    assert calibrate_outcome_probabilities(
        base,
        temperature=0.7,
        draw_multiplier=1.3,
        max_probability_shift=0.06,
    ) == published
    assert calibrate_outcome_probabilities(
        published,
        temperature=0.7,
        draw_multiplier=1.3,
        max_probability_shift=0.06,
    ) != published


def test_outcome_optimizer_falls_back_when_precalibration_is_invalid():
    published = {"home": 0.2, "draw": 0.3, "away": 0.5}
    match = {
        "outcomeProbabilities": published,
        "outcomeCalibration": {"preCalibration": {"home": 0.2, "draw": float("nan")}},
    }

    assert _base_outcome_probabilities(match) == published
