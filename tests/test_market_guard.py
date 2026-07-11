from pipeline.market_guard import (
    apply_bounded_market_anchor,
    apply_market_strength_calibration,
    market_conflict_decision,
)


def test_probability_gap_over_fifteen_points_blocks_market():
    decision = market_conflict_decision(
        {"胜": 0.40, "平": 0.30, "负": 0.30},
        {"胜": 0.70, "平": 0.20, "负": 0.10},
    )
    assert decision["blocked"]
    assert decision["status"] == "conflict"
    assert decision["maxGap"] == 0.3


def test_opposite_market_favorite_over_fifty_five_percent_blocks_market():
    decision = market_conflict_decision(
        {"胜": 0.44, "平": 0.11, "负": 0.45},
        {"胜": 0.56, "平": 0.10, "负": 0.34},
        gap_threshold=0.20,
    )
    assert decision["blocked"]
    assert decision["modelFavorite"] == "负"
    assert decision["marketFavorite"] == "胜"


def test_incomplete_market_probabilities_are_not_formally_eligible():
    decision = market_conflict_decision(
        {"胜": 0.50, "平": 0.30, "负": 0.20},
        {"胜": 0.50, "平": None, "负": 0.20},
    )
    assert decision["status"] == "unavailable"
    assert decision["blocked"]


def test_extreme_market_conflict_is_bounded_and_preserves_total_xg():
    seed = {"base_xg": [1.1, 1.45], "model_decomposition": {}}
    result = apply_market_strength_calibration(
        seed,
        {"胜": 1.45, "平": 3.83, "负": 5.60},
    )

    assert result["applied"]
    assert result["homeShift"] <= 0.20
    assert result["awayShift"] >= -0.20
    assert abs(sum(seed["base_xg"]) - 2.55) < 1e-9
    assert seed["base_xg"][0] > 1.1
    assert seed["base_xg"][1] < 1.45


def test_dual_axis_anchor_de_vigs_both_markets_and_respects_caps():
    seed = {"base_xg": [1.0, 1.0], "model_decomposition": {}}
    result = apply_bounded_market_anchor(
        seed,
        {"\u80dc": 1.30, "\u5e73": 5.0, "\u8d1f": 10.0},
        {"0": 20.0, "1": 8.0, "2": 4.0, "3": 3.0, "4": 4.0, "5": 7.0, "6": 12.0, "7+": 18.0},
        observed_at="2026-07-10T12:00:00+08:00",
        settings={"strengthBlend": 0.45, "totalGoalsBlend": 0.15, "maxSideXgShift": 0.20, "maxTotalXgShift": 0.25},
    )

    assert result["applied"]
    assert abs(result["xgShift"]["home"]) <= 0.2
    assert abs(result["xgShift"]["away"]) <= 0.2
    assert abs(result["totalXgShift"]) <= 0.25
    assert abs(sum(result["deViggedOutcomeProbabilities"].values()) - 1.0) < 1e-6
    assert abs(sum(result["deViggedTotalGoalsProbabilities"].values()) - 1.0) < 1e-6
    assert result["observedAt"] == "2026-07-10T12:00:00+08:00"


def test_dual_axis_anchor_falls_back_when_both_markets_are_incomplete():
    seed = {"base_xg": [1.2, 0.9], "model_decomposition": {}}
    result = apply_bounded_market_anchor(seed, {"\u80dc": 2.0}, {"2": 3.0})

    assert not result["applied"]
    assert result["reason"] == "incomplete_pre_kickoff_markets"
    assert seed["base_xg"] == [1.2, 0.9]


def test_production_market_anchor_is_diagnostic_when_validation_gate_fails():
    seed = {"base_xg": [1.2, 0.9], "model_decomposition": {}}
    result = apply_bounded_market_anchor(
        seed,
        {"\u80dc": 1.8, "\u5e73": 3.4, "\u8d1f": 4.8},
        {"0": 12.0, "1": 5.0, "2": 3.0, "3": 3.4, "4": 6.0, "5": 12.0, "6": 20.0, "7+": 30.0},
    )

    assert not result["applied"]
    assert result["reason"] == "validation_gate_fallback_to_diagnostic_only"
    assert seed["base_xg"] == [1.2, 0.9]
