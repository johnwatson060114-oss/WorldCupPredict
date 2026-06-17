from pipeline.drawdown import (
    adjusted_max_singles,
    drawdown_ratio,
    edge_multiplier,
    stake_multiplier,
)


def test_drawdown_ratio_at_full_bankroll():
    assert drawdown_ratio(200, 200) == 1.0


def test_drawdown_ratio_at_75_percent():
    assert drawdown_ratio(150, 200) == 0.75


def test_drawdown_ratio_floor():
    assert drawdown_ratio(0, 200) == 0.001


def test_stake_multiplier_quadratic():
    assert stake_multiplier(1.0) == 1.0
    assert stake_multiplier(0.75) == 0.5625
    assert stake_multiplier(0.5) == 0.25


def test_stake_multiplier_clamped():
    assert stake_multiplier(0.001) == 0.01
    assert stake_multiplier(1.5) == 1.0


def test_edge_multiplier_increases_when_underwater():
    assert edge_multiplier(1.0) == 1.0
    assert edge_multiplier(0.75) == 1.0 / 0.75  # ~1.333
    assert edge_multiplier(0.05) == 3.0  # clamped at max


def test_max_singles_reduction():
    assert adjusted_max_singles(4, 1.0) == 4
    assert adjusted_max_singles(4, 0.75) == 3
    assert adjusted_max_singles(2, 0.75) == 1
