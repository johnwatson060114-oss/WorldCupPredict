from pipeline.zgzcw_history import (
    HALF_FULL_SELECTIONS,
    TOTAL_GOALS_SELECTIONS,
    parse_compact_page,
    parse_score_page,
    parse_spf_page,
    sales_issue,
)


def test_sales_issue_uses_sporttery_1130_boundary():
    assert sales_issue("2026-06-18T01:00:00+08:00") == "2026-06-17"
    assert sales_issue("2026-06-18T12:00:00+08:00") == "2026-06-18"


def test_parses_portugal_closing_score_odds_and_winner_marker():
    values = "6.75 5.80 9.50 5.25 7.50 35.00 11.00 12.00 45.00 23.00 28.00 70.00 20.00 15.00 -11.00 33.00 100.0 500.0 31.00 100.0 41.00 350.0 200.0 150.0 1000 600.0 500.0 1000 1000 1000 500.0"
    html = f"<table><tr id='tr_2040182'><input id='ht_2040182' value='{values}'></tr></table>"
    assert parse_score_page(html)["2040182"]["比分"]["1:1"] == 11.0


def test_parses_compact_and_spf_markets():
    total_html = "<table><tr id='tr_2040182'><input id='ht_2040182' value='15 5.6 -3.9 3.65 4.4 8 14 18'></tr></table>"
    half_html = "<table><tr id='tr_2040182'><input id='ht_2040182' value='1.5 25 70 3.85 -8.2 30 27 25 24'></tr></table>"
    spf_html = """
    <table><tr id="tr_2040182">
      <div id="ch_2040182_49"><a id="td_2040182_49_0">1.14</a><a id="td_2040182_49_1">5.80</a><a id="td_2040182_49_2">12.50</a></div>
      <div id="ch_2040182_22"><em class="rq">-2</em><a id="td_2040182_22_0">2.51</a><a id="td_2040182_22_1">4.00</a><a id="td_2040182_22_2">2.08</a></div>
    </tr></table>
    """
    total = parse_compact_page(total_html, "总进球数", TOTAL_GOALS_SELECTIONS)
    half = parse_compact_page(half_html, "半全场", HALF_FULL_SELECTIONS)
    assert total["2040182"]["总进球数"]["2"] == 3.9
    assert half["2040182"]["半全场"]["平平"] == 8.2
    odds = parse_spf_page(spf_html)["2040182"]
    assert odds["胜平负"]["平"] == 5.8
    assert odds["让球胜平负"]["-2 负"] == 2.08
