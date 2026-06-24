from pipeline.draw_risk import apply_draw_risk_layer


def test_low_probability_strong_favorite_stall_guard_is_capped():
    result = apply_draw_risk_layer(
        {"home": 0.864, "draw": 0.120, "away": 0.016},
        {"base_xg": [2.35, 0.20]},
    )

    assert result.metadata["applied"]
    assert "low_probability_strong_favorite_stall_guard" in result.metadata["labels"]
    assert round(result.probabilities["draw"] - 0.120, 3) == 0.025
    assert result.probabilities["home"] > result.probabilities["draw"]
    assert abs(sum(result.probabilities.values()) - 1) < 1e-12


def test_misallocated_underdog_upset_probability_moves_to_draw():
    result = apply_draw_risk_layer(
        {"home": 0.544, "draw": 0.214, "away": 0.242},
        {"base_xg": [2.25, 1.46]},
    )

    assert result.metadata["applied"]
    assert "misallocated_underdog_upset_to_draw" in result.metadata["labels"]
    assert result.probabilities["draw"] > result.probabilities["away"]
    assert result.probabilities["home"] > result.probabilities["draw"]


def test_must_win_context_dampens_draw_utility_shift():
    calm = apply_draw_risk_layer(
        {"home": 0.54, "draw": 0.23, "away": 0.23},
        {
            "base_xg": [1.4, 1.1],
            "current_tournament": {
                "homeMotivation": "draw_advances",
                "awayMotivation": "competitive",
            },
        },
    )
    chase = apply_draw_risk_layer(
        {"home": 0.54, "draw": 0.23, "away": 0.23},
        {
            "base_xg": [1.4, 1.1],
            "current_tournament": {
                "homeMotivation": "draw_advances",
                "awayMotivation": "must_win",
            },
        },
    )

    assert calm.metadata["drawShift"] > chase.metadata["drawShift"]
    assert "must_win_or_goal_difference_chase_present" in chase.metadata["labels"]
