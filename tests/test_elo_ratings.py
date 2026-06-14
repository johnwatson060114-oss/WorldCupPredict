from pipeline.elo_ratings import EloRatingsClient, expected_goals_from_elo


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
