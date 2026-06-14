from pathlib import Path

import pytest

from pipeline.sporttery import filter_by_beijing_date, load_fixture, parse_spf_html

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
