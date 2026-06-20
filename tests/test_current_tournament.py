from pipeline.current_tournament import Standing, apply_current_tournament_context, result_form_adjustment


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
    assert context["homeMotivation"] == "secured"
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
