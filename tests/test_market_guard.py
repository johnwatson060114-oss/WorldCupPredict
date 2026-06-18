from pipeline.market_guard import market_conflict_decision


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
