from pipeline.football_data import FootballDataClient, api_football_shape, localized_team_name


def test_beijing_date_filter_handles_utc_boundary():
    client = FootballDataClient(token="test")
    matches = [
        {"id": 1, "utcDate": "2026-06-14T16:30:00Z"},
        {"id": 2, "utcDate": "2026-06-15T15:59:00Z"},
        {"id": 3, "utcDate": "2026-06-15T16:00:00Z"},
    ]

    selected = client.matches_on_beijing_date("2026-06-15", matches)

    assert [match["id"] for match in selected] == [1, 2]


def test_team_names_are_localized_for_sporttery_matching():
    assert localized_team_name({"name": "Cape Verde Islands"}) == "佛得角"
    assert localized_team_name({"name": "Cape Verde"}) == "佛得角"
    assert localized_team_name({"name": "DR Congo"}) == "民主刚果"
    assert localized_team_name({"name": "Bosnia and Herzegovina"}) == "波黑"
    assert localized_team_name({"name": "Sweden"}) == "瑞典"


def test_football_data_scores_convert_to_model_shape_newest_first():
    converted = api_football_shape([
        {
            "utcDate": "2026-06-12T10:00:00Z",
            "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
            "score": {"fullTime": {"home": 1, "away": 0}},
        },
        {
            "utcDate": "2026-06-13T10:00:00Z",
            "homeTeam": {"id": 1}, "awayTeam": {"id": 3},
            "score": {"fullTime": {"home": 2, "away": 1}},
        },
    ])

    assert converted[0]["goals"] == {"home": 2, "away": 1}
