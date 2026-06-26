from pipeline.current_tournament import (
    Standing,
    apply_current_tournament_context,
    best_third_snapshot,
    draw_suffices_for_scenario,
    group_scenarios,
    late_scoreboard_pressure,
    motivation_xg_adjustment,
    mutual_draw_utility,
    result_form_adjustment,
)


def fixture(date, home, away, home_score, away_score, status="FINISHED"):
    return {
        "utcDate": date,
        "status": status,
        "stage": "GROUP_STAGE",
        "group": "GROUP_A",
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": home_score, "away": away_score}},
    }


def test_motivation_is_not_applied_before_third_group_match():
    matches = [
        fixture("2026-06-11T12:00:00Z", "Team A", "Team B", 1, 0),
    ]
    seeds = [{
        "kickoff": "2026-06-20T12:00:00+00:00",
        "home_team": "Team A",
        "away_team": "Team C",
        "group": "GROUP_A",
        "base_xg": [1.4, 1.0],
        "coverage": 0.8,
    }]

    apply_current_tournament_context(seeds, matches)

    assert seeds[0]["base_xg"] == [1.4, 1.0]
    assert not seeds[0]["current_tournament"]["applied"]


def test_secured_team_and_must_win_team_get_bounded_third_match_adjustment():
    matches = [
        fixture("2026-06-11T12:00:00Z", "Team A", "Team B", 2, 0),
        fixture("2026-06-12T12:00:00Z", "Team C", "Team D", 1, 0),
        fixture("2026-06-16T12:00:00Z", "Team A", "Team C", 1, 0),
        fixture("2026-06-17T12:00:00Z", "Team D", "Team B", 1, 0),
    ]
    seeds = [{
        "kickoff": "2026-06-22T12:00:00+00:00",
        "home_team": "Team A",
        "away_team": "Team B",
        "group": "GROUP_A",
        "base_xg": [1.4, 1.0],
        "coverage": 0.8,
    }]

    apply_current_tournament_context(seeds, matches)

    context = seeds[0]["current_tournament"]
    assert context["homeMotivation"] == "secured_top_two"
    assert context["awayMotivation"] == "must_win"
    assert context["applied"]
    assert seeds[0]["base_xg"] != [1.4, 1.0]
    assert seeds[0]["coverage"] == 0.78


def test_two_match_result_form_is_shrunk_and_bounded():
    attack, defense = result_form_adjustment(
        Standing(played=2, points=6, goals_for=8, goals_against=0),
        goal_average=1.5,
    )

    assert 0 < attack <= 0.06
    assert 0 < defense <= 0.06


def test_group_scenarios_detect_secured_and_must_win_states():
    matches = [
        fixture("2026-06-11T12:00:00Z", "Team A", "Team B", 2, 0),
        fixture("2026-06-12T12:00:00Z", "Team C", "Team D", 1, 0),
        fixture("2026-06-16T12:00:00Z", "Team A", "Team C", 1, 0),
        fixture("2026-06-17T12:00:00Z", "Team D", "Team B", 1, 0),
        fixture("2026-06-22T12:00:00Z", "Team A", "Team D", None, None, status="TIMED"),
        fixture("2026-06-22T12:00:00Z", "Team B", "Team C", None, None, status="TIMED"),
    ]
    cutoff = __import__("datetime").datetime.fromisoformat("2026-06-22T12:00:00+00:00")

    secured = group_scenarios(matches, "GROUP_A", cutoff, "Team A", max_goals=2)
    must_win = group_scenarios(matches, "GROUP_A", cutoff, "Team B", max_goals=2)

    assert secured["state"] == "draw_advances"
    assert secured["positionRange"] == [1, 3]
    assert must_win["state"] in {"must_win", "goal_difference_chase"}


def test_late_pressure_reacts_to_parallel_scoreboard_state():
    safe_draw = late_scoreboard_pressure("draw_advances", 0, parallel_result_helps=True)
    chase = late_scoreboard_pressure("must_win", 0, parallel_result_helps=False)

    assert safe_draw["attackMultiplier"] < 1
    assert chase["attackMultiplier"] > 1
    assert chase["defensiveRiskMultiplier"] > 1


def test_first_place_path_keeps_secured_team_attacking():
    base_attack, base_defense = motivation_xg_adjustment(
        "secured_top_two",
        {"firstPlacePathIncentive": False, "thirdScenarioShare": 0.0},
    )
    chase_attack, chase_defense = motivation_xg_adjustment(
        "secured_top_two",
        {"firstPlacePathIncentive": True, "thirdScenarioShare": 0.0},
    )

    assert chase_attack > base_attack
    assert chase_defense < base_defense


def test_mutual_draw_utility_overrides_first_place_open_game_boost():
    scenario = {
        "state": "draw_advances",
        "positionRange": [1, 3],
        "thirdScenarioShare": 0.45,
        "firstPlacePathIncentive": True,
    }
    open_attack, open_defense = motivation_xg_adjustment(
        "draw_advances",
        scenario,
        draw_suffices=False,
        mutual_draw_utility=False,
    )
    safe_attack, safe_defense = motivation_xg_adjustment(
        "draw_advances",
        scenario,
        draw_suffices=True,
        mutual_draw_utility=True,
    )

    assert draw_suffices_for_scenario("draw_advances", scenario)
    assert mutual_draw_utility("draw_advances", "draw_advances", scenario, scenario)
    assert safe_attack < open_attack
    assert safe_defense > open_defense


def test_eliminated_team_opens_game_instead_of_only_sitting_deep():
    attack, defense = motivation_xg_adjustment("eliminated")

    assert attack > 0
    assert defense < 0


def test_best_third_snapshot_uses_cross_group_order():
    matches = [
        {**fixture("2026-06-11T12:00:00Z", "A1", "A2", 2, 0), "group": "GROUP_A"},
        {**fixture("2026-06-12T12:00:00Z", "A3", "A4", 1, 0), "group": "GROUP_A"},
        {**fixture("2026-06-16T12:00:00Z", "A1", "A3", 1, 0), "group": "GROUP_A"},
        {**fixture("2026-06-17T12:00:00Z", "A4", "A2", 1, 0), "group": "GROUP_A"},
        {**fixture("2026-06-11T13:00:00Z", "B1", "B2", 1, 0), "group": "GROUP_B"},
        {**fixture("2026-06-12T13:00:00Z", "B3", "B4", 3, 0), "group": "GROUP_B"},
        {**fixture("2026-06-16T13:00:00Z", "B1", "B3", 1, 0), "group": "GROUP_B"},
        {**fixture("2026-06-17T13:00:00Z", "B4", "B2", 1, 0), "group": "GROUP_B"},
    ]
    cutoff = __import__("datetime").datetime.fromisoformat("2026-06-22T12:00:00+00:00")

    snapshot = best_third_snapshot(matches, cutoff)

    assert len(snapshot) == 2
    assert snapshot[0]["points"] >= snapshot[1]["points"]
