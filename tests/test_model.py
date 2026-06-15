import math

from pipeline.model import (
    half_full_probabilities,
    normalized_market_probabilities,
    outcome_probabilities,
    score_matrix,
    total_goals_probabilities,
)


def test_score_matrix_is_normalized():
    matrix = score_matrix(1.9, 0.8)
    assert math.isclose(sum(sum(row) for row in matrix), 1.0, rel_tol=1e-9)


def test_handicap_mapping_minus_one():
    matrix = score_matrix(2.0, 0.7)
    normal = outcome_probabilities(matrix)
    minus_one = outcome_probabilities(matrix, -1)
    assert minus_one["home"] < normal["home"]
    assert math.isclose(sum(minus_one.values()), 1.0, rel_tol=1e-9)


def test_market_margin_is_removed():
    values = normalized_market_probabilities({"胜": 1.80, "平": 3.30, "负": 3.70})
    assert math.isclose(sum(value for value in values.values() if value), 1.0, rel_tol=1e-9)


def test_total_goals_and_half_full_are_normalized():
    matrix = score_matrix(1.7, 1.1)
    totals = total_goals_probabilities(matrix)
    half_full = half_full_probabilities(1.7, 1.1)
    assert set(totals) == {"0", "1", "2", "3", "4", "5", "6", "7+"}
    assert math.isclose(sum(totals.values()), 1.0, rel_tol=1e-9)
    assert len(half_full) == 9
    assert math.isclose(sum(half_full.values()), 1.0, rel_tol=1e-9)
