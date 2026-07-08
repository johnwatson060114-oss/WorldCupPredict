import math

from pipeline.model import outcome_probabilities, score_matrix, total_goals_probabilities
from pipeline.score_calibration import apply_score_matrix_calibration


def _bucket_probability(totals: dict[str, float], buckets: set[str]) -> float:
    return sum(totals[bucket] for bucket in buckets)


def test_score_calibration_ignores_non_knockout_matches():
    matrix = score_matrix(1.4, 1.1)

    result = apply_score_matrix_calibration(matrix, {}, 1.4, 1.1)

    assert result.matrix is matrix
    assert result.metadata == {"applied": False, "reason": "not_knockout"}


def test_close_knockout_calibration_keeps_nil_nil_and_preserves_outcomes():
    matrix = score_matrix(1.24, 1.22)
    result = apply_score_matrix_calibration(
        matrix,
        {"knockout_context": {"policy": "knockout_tension_close_game_v2"}},
        1.24,
        1.22,
    )

    before_totals = total_goals_probabilities(matrix)
    after_totals = total_goals_probabilities(result.matrix)

    assert result.metadata["applied"]
    assert result.metadata["profile"] == "close_late_tail"
    assert _bucket_probability(after_totals, {"3", "4", "5", "6", "7+"}) > _bucket_probability(before_totals, {"3", "4", "5", "6", "7+"})
    assert after_totals["0"] > before_totals["0"]
    assert result.matrix[0][0] > matrix[0][0]
    assert math.isclose(sum(sum(row) for row in result.matrix), 1.0, rel_tol=1e-9)
    for key, value in outcome_probabilities(matrix).items():
        assert math.isclose(outcome_probabilities(result.matrix)[key], value, abs_tol=1e-9)


def test_favorite_knockout_calibration_widens_tail_and_preserves_outcomes():
    matrix = score_matrix(2.2, 0.7)
    result = apply_score_matrix_calibration(
        matrix,
        {"knockout_context": {"policy": "knockout_underdog_chase_favorite_tempo_v1"}},
        2.2,
        0.7,
    )

    before_totals = total_goals_probabilities(matrix)
    after_totals = total_goals_probabilities(result.matrix)

    assert result.metadata["profile"] == "favorite_tail"
    assert result.metadata["policy"] == "knockout_score_total_matrix_calibration_v3"
    assert result.metadata["intensity"] == 0.25
    assert _bucket_probability(after_totals, {"4", "5", "6", "7+"}) > _bucket_probability(before_totals, {"4", "5", "6", "7+"})
    assert result.matrix[3][1] > matrix[3][1]
    assert result.matrix[3][2] > matrix[3][2]
    assert math.isclose(sum(sum(row) for row in result.matrix), 1.0, rel_tol=1e-9)
    for key, value in outcome_probabilities(matrix).items():
        assert math.isclose(outcome_probabilities(result.matrix)[key], value, abs_tol=1e-9)
