from pipeline.market_guard import apply_market_strength_calibration, market_conflict_decision


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
