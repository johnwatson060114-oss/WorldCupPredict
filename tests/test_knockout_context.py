from pipeline.knockout_context import apply_knockout_context, is_knockout_stage, knockout_adjust_xg


def test_knockout_stage_is_inferred_after_group_stage_dates():
    assert is_knockout_stage(None, None, "2026-06-29")
    assert not is_knockout_stage(None, "GROUP_A", "2026-06-29")


def test_knockout_context_does_not_boost_favorite_xg():
    adjustment = knockout_adjust_xg(1.9, 0.8)

    assert adjustment.favorite_side == "home"
    assert adjustment.home_xg <= 1.9
    assert adjustment.away_xg >= 0.8
    assert adjustment.away_late_attack_multiplier > adjustment.home_late_attack_multiplier


def test_apply_knockout_context_records_decomposition():
    seeds = [{"home_team": "A", "away_team": "B", "base_xg": [1.6, 1.0], "coverage": 0.82}]

    apply_knockout_context(seeds, "2026-06-29")

    assert seeds[0]["knockout_context"]["applied"]
    assert seeds[0]["model_decomposition"]["knockoutLayer"]
    assert round(seeds[0]["coverage"], 4) == 0.81
