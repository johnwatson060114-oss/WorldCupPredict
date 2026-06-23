from pipeline.two_round_form import (
    MAX_TACTICAL_DIRECTION_XG,
    MAX_TEAM_DIRECTION_XG,
    apply_two_round_form,
    team_tournament_adjustment,
)


def profile(tactical_status: str = "enabled") -> dict:
    return {
        "team": "A",
        "summary": "两轮状态",
        "matches": [
            {
                "observedMatchday": 1,
                "observedDate": "2026-06-11",
                "evidenceConfidence": 0.7,
                "objectiveForm": {"attackDelta": 0.10, "defenseDelta": 0.04},
                "tacticalCandidate": {
                    "attackDelta": 0.04,
                    "defenseDelta": 0.0,
                    "admissionStatus": tactical_status,
                },
            },
            {
                "observedMatchday": 2,
                "observedDate": "2026-06-18",
                "evidenceConfidence": 0.9,
                "objectiveForm": {"attackDelta": -0.02, "defenseDelta": 0.08},
                "tacticalCandidate": {
                    "attackDelta": 0.08,
                    "defenseDelta": 0.0,
                    "admissionStatus": tactical_status,
                },
            },
        ],
    }


def test_second_round_receives_fifty_five_percent_weight():
    result = team_tournament_adjustment("A", profile(), "2026-06-25")

    assert round(result.objective_attack, 4) == 0.051
    assert result.tactical_attack == MAX_TACTICAL_DIRECTION_XG
    assert result.observed_matchdays == (1, 2)


def test_shadow_tactical_layer_does_not_change_mean():
    result = team_tournament_adjustment("A", profile("observation_only"), "2026-06-25")

    assert result.tactical_attack == 0.0
    assert result.combined_attack == result.objective_attack


def test_total_team_direction_remains_bounded_and_decomposed():
    strong = profile()
    for match in strong["matches"]:
        match["objectiveForm"]["attackDelta"] = 0.5
        match["tacticalCandidate"]["attackDelta"] = 0.5
    seeds = [{"home_team": "A", "away_team": "B", "base_xg": [1.4, 1.0]}]

    apply_two_round_form(seeds, "2026-06-25", {"A": strong})

    assert seeds[0]["tournament_form"]["home"]["attackDelta"] == MAX_TEAM_DIRECTION_XG
    assert seeds[0]["model_decomposition"]["objectiveFormNet"]["home"] > 0
    assert seeds[0]["model_decomposition"]["tacticalNet"]["home"] == MAX_TACTICAL_DIRECTION_XG
