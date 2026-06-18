from pipeline.elo_ratings import EloRatingsClient, allocate_total_goals_by_elo, expected_goals_from_elo


def test_ratings_parser_joins_codes_to_localized_names(monkeypatch):
    client = EloRatingsClient()
    payloads = {
        "en.teams.tsv": "DE\tGermany\nCW\tCuraçao\n",
        "World.tsv": "1\t1\tDE\t1932\n80\t80\tCW\t1320\n",
    }
    monkeypatch.setattr(client, "_text", lambda filename: payloads[filename])

    assert client.ratings() == {"德国": 1932, "库拉索": 1320}


def test_elo_expected_goals_favor_stronger_team_and_keep_total():
    home, away = expected_goals_from_elo(1932, 1320)

    assert home > away
    assert abs(home + away - 2.55) < 0.0001


def test_world_cup_team_aliases_resolve_elo_names(monkeypatch):
    client = EloRatingsClient()
    payloads = {
        "en.teams.tsv": "CV\tCape Verde\nCD\tDR Congo\nBA\tBosnia and Herzegovina\nES\tSpain\n",
        "World.tsv": "1\t0\tCV\t1578\n2\t0\tCD\t1652\n3\t0\tBA\t1616\n4\t0\tES\t2157\n",
    }
    monkeypatch.setattr(client, "_text", lambda filename: payloads[filename])

    assert client.ratings() == {"佛得角": 1578, "民主刚果": 1652, "波黑": 1616, "西班牙": 2157}


def test_elo_allocator_preserves_goal_model_total():
    home, away = allocate_total_goals_by_elo(3.10, 1980, 1700)
    assert abs(home + away - 3.10) < 1e-9
    assert home > away
