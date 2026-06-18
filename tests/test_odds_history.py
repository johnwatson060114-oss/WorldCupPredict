from datetime import datetime
from zoneinfo import ZoneInfo

from pipeline.odds_history import closing_line_value, save_odds_snapshot, snapshot_kind
from pipeline.sporttery import SportteryMatch


def test_snapshot_kind_marks_only_final_sixty_minutes():
    assert snapshot_kind(60) == "closing_60m"
    assert snapshot_kind(0) == "closing_60m"
    assert snapshot_kind(61) == "daily"
    assert snapshot_kind(-1) == "daily"


def test_compact_snapshot_preserves_market_odds_and_index(tmp_path):
    match = SportteryMatch(
        match_id="m1",
        lottery_code="周五001",
        kickoff_text="06-19 14:00",
        match_date="2026-06-19",
        league_name="世界杯",
        home_team="A",
        away_team="B",
        win_draw_loss={"胜": 2.0, "平": 3.0, "负": 4.0},
    )
    observed = datetime(2026, 6, 19, 13, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    path = save_odds_snapshot([match], observed, tmp_path)
    assert path.exists()
    assert (tmp_path / "index.json").exists()
    assert "closing_60m" in path.read_text(encoding="utf-8")


def test_closing_line_value_is_positive_when_open_price_beats_close():
    assert closing_line_value(2.20, 2.00) == 0.10
