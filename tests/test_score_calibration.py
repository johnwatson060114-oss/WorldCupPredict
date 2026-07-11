import math

from pipeline.model import outcome_probabilities, score_matrix, total_goals_probabilities
from pipeline.score_calibration import apply_score_matrix_calibration


def _bucket_probability(totals: dict[str, float], buckets: set[str]) -> float:
    return sum(totals[bucket] for bucket in buckets)


def test_score_calibration_ignores_matches_without_current_tournament_evidence():
    matrix = score_matrix(1.4, 1.1)

    result = apply_score_matrix_calibration(matrix, {}, 1.4, 1.1)

    assert result.matrix is matrix
    assert result.metadata == {"applied": False, "reason": "no_current_tournament_evidence"}


def test_close_knockout_calibration_keeps_nil_nil_and_preserves_outcomes():
    matrix = score_matrix(1.24, 1.22)
    result = apply_score_matrix_calibration(
        matrix,
        {"knockout_context": {"policy": "knockout_tension_close_game_v2"}},
        1.24,
        1.22,
        intensity=0.25,
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
        intensity=0.25,
    )

    before_totals = total_goals_probabilities(matrix)
    after_totals = total_goals_probabilities(result.matrix)

    assert result.metadata["profile"] == "favorite_tail"
    assert result.metadata["policy"] == "adaptive_score_total_matrix_calibration_v4"
    assert result.metadata["intensity"] == 0.25
    assert _bucket_probability(after_totals, {"4", "5", "6", "7+"}) > _bucket_probability(before_totals, {"4", "5", "6", "7+"})
    assert result.matrix[3][1] > matrix[3][1]
    assert result.matrix[3][2] > matrix[3][2]
    assert math.isclose(sum(sum(row) for row in result.matrix), 1.0, rel_tol=1e-9)
    for key, value in outcome_probabilities(matrix).items():
        assert math.isclose(outcome_probabilities(result.matrix)[key], value, abs_tol=1e-9)


def test_explicit_zero_intensity_returns_base_matrix_without_rounding_drift():
    matrix = score_matrix(2.0, 0.8)
    result = apply_score_matrix_calibration(
        matrix,
        {"tournament_evidence": {"policy": "current_tournament_evidence_v1"}},
        2.0,
        0.8,
        intensity=0.0,
    )

    assert not result.metadata["applied"]
    assert result.metadata["intensity"] == 0.0
    assert result.matrix == matrix
