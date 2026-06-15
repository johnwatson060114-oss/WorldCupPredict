import math

from pipeline.simulation import MatchSimulationInput, rank_group, simulate_tournament


def input_match(match_id: str = "m1") -> MatchSimulationInput:
    return MatchSimulationInput(match_id, "A", "B", 1.7, 0.9)


def test_exactly_100000_paths_are_executed_and_reported():
    result = simulate_tournament([input_match()], paths=100_000, seed=42)
    summary = result.summaries["m1"]

    assert result.paths == 100_000
    assert len(result.scores_by_match["m1"]) == 100_000
    assert summary["quality"]["actualPaths"] == 100_000
    assert [item["paths"] for item in summary["quality"]["convergence"]] == [25_000, 50_000, 100_000]
    assert math.isclose(sum(summary["outcomes"].values()), 1.0, abs_tol=1e-12)


def test_fixed_seed_reproduces_every_path():
    first = simulate_tournament([input_match()], paths=5_000, seed=123)
    second = simulate_tournament([input_match()], paths=5_000, seed=123)

    assert first.scores_by_match == second.scores_by_match
    assert first.halftime_scores_by_match == second.halftime_scores_by_match
    assert first.summaries == second.summaries


def test_parameter_uncertainty_is_only_claimed_when_samples_are_supplied():
    fixed = simulate_tournament([input_match()], paths=100, seed=1)
    sampled = simulate_tournament([
        MatchSimulationInput("m1", "A", "B", 1.7, 0.9, parameter_samples=((1.4, 1.0), (2.0, 0.7)))
    ], paths=100, seed=1)

    assert fixed.parameter_uncertainty == "fixed"
    assert sampled.parameter_uncertainty == "posterior_or_bootstrap_samples"


def test_convergence_deltas_shrink_to_monte_carlo_scale():
    result = simulate_tournament([input_match()], paths=100_000, seed=7)
    convergence = result.summaries["m1"]["quality"]["convergence"]

    assert convergence[-1]["maxDeltaFromPrevious"] < 0.01
    assert all(value < 0.002 for value in result.summaries["m1"]["quality"]["monteCarloStandardError"].values())


def test_group_ranking_uses_head_to_head_then_conduct_score():
    results = [
        {"home": "A", "away": "B", "home_goals": 1, "away_goals": 0, "conduct": {"A": -2, "B": -1}},
        {"home": "A", "away": "C", "home_goals": 0, "away_goals": 1, "conduct": {}},
        {"home": "B", "away": "C", "home_goals": 2, "away_goals": 0, "conduct": {}},
    ]

    assert rank_group(["A", "B", "C"], results) == ["B", "A", "C"]

    conduct_tie = [
        {"home": "A", "away": "B", "home_goals": 0, "away_goals": 0, "conduct": {"A": -1, "B": -3}},
        {"home": "A", "away": "C", "home_goals": 0, "away_goals": 0, "conduct": {"C": -2}},
        {"home": "B", "away": "C", "home_goals": 0, "away_goals": 0, "conduct": {}},
    ]
    assert rank_group(["A", "B", "C"], conduct_tie) == ["A", "C", "B"]


def test_group_rank_probabilities_are_aggregated_across_shared_paths():
    matches = [
        MatchSimulationInput("m1", "A", "B", 1.2, 1.0, stage="group", group="G"),
        MatchSimulationInput("m2", "A", "C", 1.2, 1.0, stage="group", group="G"),
        MatchSimulationInput("m3", "B", "C", 1.2, 1.0, stage="group", group="G", stage_complete=True),
    ]
    result = simulate_tournament(matches, paths=2_000, seed=9)

    assert set(result.group_rank_probabilities["G"]) == {"A", "B", "C"}
    for position in range(3):
        assert math.isclose(sum(values[position] for values in result.group_rank_probabilities["G"].values()), 1.0)
