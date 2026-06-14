from pathlib import Path

import pytest

from pipeline.sporttery import filter_by_beijing_date, load_fixture, parse_api_snapshots, parse_spf_html

FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_reads_odds_handicap_single_and_scores():
    matches = load_fixture(FIXTURES / "sporttery-spf.html", FIXTURES / "sporttery-score.html")
    netherlands = matches["2040171"]
    assert netherlands.handicap == -1
    assert netherlands.win_draw_loss == {"胜": 1.8, "平": 3.3, "负": 3.7}
    assert "胜平负" in netherlands.single_markets
    assert netherlands.scores["2:1"] == 8.0
    assert matches["2040170"].win_draw_loss["胜"] is None


def test_beijing_date_filter_uses_kickoff_not_lottery_label():
    matches = load_fixture(FIXTURES / "sporttery-spf.html")
    selected = filter_by_beijing_date(matches.values(), "2026-06-15")
    assert [match.match_id for match in selected] == ["2040170", "2040171", "2040172", "2040173"]


def test_structure_change_stops_parser():
    with pytest.raises(ValueError, match="structure changed"):
        parse_spf_html("<html><body>changed</body></html>")


def test_api_snapshot_reads_live_markets_scores_and_single_flags():
    base = {
        "matchId": 537358,
        "matchDate": "2026-06-15",
        "matchTime": "10:00:00",
        "matchNumStr": "周日012",
        "homeTeamAbbName": "瑞典",
        "awayTeamAbbName": "突尼斯",
        "had": {"h": "1.67", "d": "3.35", "a": "4.30"},
        "hhad": {"goalLine": "-1", "h": "3.32", "d": "3.17", "a": "1.95"},
        "poolList": [
            {"poolCode": "HAD", "poolStatus": "Selling", "single": 1},
            {"poolCode": "HHAD", "poolStatus": "Selling", "single": 0},
        ],
    }
    score = {
        "matchId": 537358,
        "crs": {"s01s00": "7.25", "s01s01": "3.90", "s1sh": "300.0"},
        "poolList": [{"poolCode": "CRS", "poolStatus": "Selling", "single": 0}],
    }

    matches = parse_api_snapshots(
        {"value": {"matchInfoList": [{"subMatchList": [base]}]}},
        {"value": {"matchInfoList": [{"subMatchList": [score]}]}},
    )

    match = matches["537358"]
    assert match.kickoff_text == "06-15 10:00"
    assert match.handicap == -1
    assert match.win_draw_loss == {"胜": 1.67, "平": 3.35, "负": 4.3}
    assert match.scores == {"1:0": 7.25, "1:1": 3.9, "胜其它": 300.0}
    assert match.single_markets == {"胜平负"}
