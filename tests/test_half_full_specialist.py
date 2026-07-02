from __future__ import annotations

import math

from pipeline.half_full_specialist import (
    apply_half_full_market_calibration,
    build_half_full_signal,
    half_full_to_outcomes,
    normalize_distribution,
)


def test_half_full_to_outcomes_aggregates_by_fulltime_label():
    outcomes = half_full_to_outcomes({
        "\u80dc\u80dc": 0.20,
        "\u5e73\u80dc": 0.30,
        "\u8d1f\u5e73": 0.10,
        "\u8d1f\u8d1f": 0.40,
    })

    assert outcomes == {"home": 0.50, "draw": 0.10, "away": 0.40}


def test_normalize_distribution_fills_missing_half_full_options():
    probabilities = normalize_distribution({"\u80dc\u80dc": 2.0}, ("\u80dc\u80dc", "\u5e73\u5e73"))

    assert probabilities == {"\u80dc\u80dc": 1.0, "\u5e73\u5e73": 0.0}


def test_half_full_signal_blends_conservatively_into_outcomes():
    signal = build_half_full_signal(
        {"\u80dc\u80dc": 0.8, "\u5e73\u5e73": 0.2},
        {"home": 0.4, "draw": 0.35, "away": 0.25},
        weight=0.25,
    )

    assert math.isclose(sum(signal.assisted_outcomes.values()), 1.0)
    assert signal.outcome_signal == {"home": 0.8, "draw": 0.2, "away": 0.0}
    assert signal.assisted_outcomes["home"] > 0.4
    assert signal.assisted_outcomes["away"] < 0.25
    assert signal.metadata["policy"] == "half_full_specialist_v1"


def test_half_full_market_calibration_only_applies_to_knockout():
    half_full = {
        "\u80dc\u80dc": 0.5,
        "\u80dc\u5e73": 0.1,
        "\u80dc\u8d1f": 0.05,
        "\u5e73\u80dc": 0.1,
        "\u5e73\u5e73": 0.1,
        "\u5e73\u8d1f": 0.05,
        "\u8d1f\u80dc": 0.02,
        "\u8d1f\u5e73": 0.03,
        "\u8d1f\u8d1f": 0.05,
    }

    group = apply_half_full_market_calibration(half_full, {})
    knockout = apply_half_full_market_calibration(
        half_full,
        {"knockout_context": {"policy": "knockout_underdog_chase_favorite_tempo_v1"}},
    )

    assert group.metadata == {"applied": False, "reason": "not_knockout"}
    assert knockout.metadata["policy"] == "knockout_half_full_late_swing_v1"
    assert knockout.probabilities["\u80dc\u80dc"] < group.probabilities["\u80dc\u80dc"]
    assert knockout.probabilities["\u8d1f\u80dc"] > group.probabilities["\u8d1f\u80dc"]
    assert math.isclose(sum(knockout.probabilities.values()), 1.0)
