from pipeline.portfolio import build_portfolios, path_probability, round_to_ticket, settle_leg, simulate_portfolio
from pipeline.simulation import TournamentSimulation


def quote(match_id: str, edge: float, odds: float = 2.0, single: bool = True):
    return {
        "id": f"q-{match_id}", "matchId": match_id, "label": f"A{match_id} vs B{match_id}",
        "market": "胜平负", "selection": "胜", "odds": odds, "modelProbability": 0.60,
        "robustExpectedReturn": edge, "available": True, "singleEligible": single,
        "recommendation": "重点推荐", "coverage": 0.90,
    }


def shared_simulation(*match_ids: str, paths: int = 100) -> TournamentSimulation:
    scores = {match_id: [(1, 0) if index % 2 == 0 else (0, 1) for index in range(paths)] for match_id in match_ids}
    halftime = {match_id: [(0, 0) for _ in range(paths)] for match_id in match_ids}
    return TournamentSimulation(paths=paths, seed=1, scores_by_match=scores, halftime_scores_by_match=halftime)


def test_rounding_is_two_yuan_increment():
    assert round_to_ticket(11.9) == 10
    assert round_to_ticket(2.0) == 2
    assert round_to_ticket(1.9) == 0


def test_portfolios_use_common_stake_sizing_and_distinct_parlay_matches():
    portfolios = build_portfolios(
        [quote("1", 0.12)],
        bankroll=200,
        simulation=shared_simulation("1"),
    )
    stakes_by_strategy = {}
    for portfolio in portfolios:
        assert portfolio["stake"] <= 200
        assert portfolio["stake"] % 2 == 0
        for ticket in portfolio["tickets"]:
            assert ticket["stake"] % 2 == 0
            ids = [leg["matchId"] for leg in ticket["legs"]]
            assert len(ids) == len(set(ids))
        single = next(ticket for ticket in portfolio["tickets"] if ticket["type"] == "单关")
        stakes_by_strategy[portfolio["key"]] = single["stake"]

    assert len(set(stakes_by_strategy.values())) == 1


def test_cross_day_quotes_only_enter_through_parlays():
    same_day = [quote("1", 0.12, odds=1.80)]
    cross_day = [
        {**quote("2", 0.12, odds=1.80), "matchDate": "2026-06-19", "kickoffBeijing": "2026-06-19T03:00:00+08:00"},
        {**quote("3", 0.12, odds=1.80), "matchDate": "2026-06-19", "kickoffBeijing": "2026-06-19T06:00:00+08:00"},
        {**quote("4", 0.12, odds=1.80), "matchDate": "2026-06-20", "kickoffBeijing": "2026-06-20T03:00:00+08:00"},
    ]

    portfolios = {
        item["key"]: item
        for item in build_portfolios(
            same_day,
            bankroll=200,
            simulation=shared_simulation("1", "2", "3", "4"),
            parlay_quotes=same_day + cross_day,
        )
    }

    assert all(
        leg["matchId"] == "1"
        for ticket in portfolios["conservative"]["tickets"]
        for leg in ticket["legs"]
    )
    assert any(ticket["type"] == "2串1" for ticket in portfolios["balanced"]["tickets"])
    assert any(ticket["type"] == "3串1" for ticket in portfolios["aggressive"]["tickets"])
    balanced_2x1 = next(ticket for ticket in portfolios["balanced"]["tickets"] if ticket["type"] == "2串1")
    aggressive_2x1 = next(ticket for ticket in portfolios["aggressive"]["tickets"] if ticket["type"] == "2串1")
    assert balanced_2x1["stake"] == aggressive_2x1["stake"] == 10


def test_negative_edge_conservative_empty_balanced_aggressive_fallback():
    """保守: negative_edge_fallback=False → 0元不投。
    均衡/激进: fallback → entertainment-mode tickets with combo coverage."""
    portfolios = build_portfolios([quote("1", -0.01)], bankroll=200, simulation=shared_simulation("1"))
    # Conservative: no fallback → 0 stake, 0 tickets
    assert portfolios[0]["stake"] == 0, "conservative should not bet on negative edge"
    assert len(portfolios[0]["tickets"]) == 0, "conservative should have no tickets"
    # Balanced and aggressive: fallback → entertainment mode with tickets
    for p in portfolios[1:]:
        assert p["entertainmentMode"], f"{p['key']} should be in entertainment mode"
        assert len(p["tickets"]) >= 1, f"{p['key']} should have tickets"


def test_observation_only_quote_strict_path_no_longer_requires_recommendation():
    """After removing singleEligible/recommendation gates, a positive-edge
    quote is accepted via the strict path regardless of its recommendation
    label.  Market and odds still gate per-strategy."""
    observed = quote("1", 4.0, odds=50.0)
    observed.update({"market": "半全场", "selection": "负负", "recommendation": "观察"})

    portfolios = build_portfolios([observed], bankroll=200, simulation=shared_simulation("1"))

    # conservative: market "半全场" not in single_markets → no tickets
    assert not portfolios[0]["tickets"]
    # balanced: market "半全场" not in single_markets → no tickets
    assert not portfolios[1]["tickets"]
    # aggressive: semi-full IS in single_markets, odds 50 ≤ 80 → accepted (strict path)
    assert len(portfolios[2]["tickets"]) >= 1, "aggressive should accept 半全场 with +4 edge"
    assert not portfolios[2]["entertainmentMode"], "should use strict path, not fallback"


def test_strategy_market_and_parlay_rules_are_materially_different():
    quotes = [
        quote("1", 0.12, odds=1.80),
        {**quote("2", 0.10, odds=2.20), "market": "总进球数", "selection": "2", "modelProbability": 0.56},
        {**quote("3", 0.09, odds=2.50), "market": "让球胜平负", "selection": "-1 平", "handicap": -1, "modelProbability": 0.48},
        {**quote("4", 0.20, odds=8.00), "market": "半全场", "selection": "胜胜", "modelProbability": 0.18},
        {**quote("5", 0.15, odds=12.0, single=False), "market": "比分", "selection": "2:0", "modelProbability": 0.12},
        # Extra parlay-only legs on fresh matchIds.  Singles have already
        # claimed matches 1-4, so these feed the 2串1/3串1 pool without
        # duplicating existing single exposure.
        quote("6", 0.10, odds=2.00),
        quote("7", 0.10, odds=2.00),
        quote("8", 0.10, odds=2.00),
    ]
    portfolios = {
        item["key"]: item
        for item in build_portfolios(
            quotes,
            bankroll=200,
            simulation=shared_simulation("1", "2", "3", "4", "5", "6", "7", "8"),
        )
    }

    conservative = portfolios["conservative"]
    assert conservative["tickets"]
    assert all(ticket["type"] == "单关" for ticket in conservative["tickets"])
    assert {leg["market"] for ticket in conservative["tickets"] for leg in ticket["legs"]} <= {"胜平负", "总进球数"}

    balanced = portfolios["balanced"]
    assert any(ticket["type"] == "2串1" for ticket in balanced["tickets"]), "balanced should have 2串1 from unused matchIds"
    assert not {"比分", "半全场"} & {leg["market"] for ticket in balanced["tickets"] for leg in ticket["legs"]}

    aggressive = portfolios["aggressive"]
    aggressive_markets = {leg["market"] for ticket in aggressive["tickets"] for leg in ticket["legs"]}
    assert {"比分", "半全场"} & aggressive_markets
    assert any(ticket["type"] == "3串1" for ticket in aggressive["tickets"]), "aggressive should have 3串1 from unused matchIds"
    assert conservative["strategyRules"] != balanced["strategyRules"] != aggressive["strategyRules"]


def test_all_markets_settle_from_the_same_score_path():
    score = (2, 1)
    halftime = (1, 0)

    assert settle_leg({"market": "胜平负", "selection": "胜"}, score, halftime)
    assert settle_leg({"market": "让球胜平负", "selection": "-1 平", "handicap": -1}, score, halftime)
    assert settle_leg({"market": "比分", "selection": "2:1"}, score, halftime)
    assert settle_leg({"market": "总进球数", "selection": "3"}, score, halftime)
    assert settle_leg({"market": "半全场", "selection": "胜胜"}, score, halftime)


def test_drawdown_shrinks_stakes_but_does_not_silence_strategy():
    """Underwater aggressive should still bet — just smaller and pickier.
    Drawdown protection is continuous, not a binary kill switch."""
    # Quotes with barely-positive edge.  At dr=0.74 the edge requirement
    # rises to 0.0*1.35=0.0 (aggressive still accepts), and stakes shrink
    # to ~55 %.  The strategy should find tickets — just fewer/smaller ones.
    quotes = [
        quote("1", 0.12, odds=1.80),
        quote("2", 0.10, odds=2.00),
        quote("3", 0.08, odds=2.20),
    ]

    full = build_portfolios(
        quotes, bankroll=200, simulation=shared_simulation("1", "2", "3"),
    )
    aggressive_full = next(p for p in full if p["key"] == "aggressive")

    half = build_portfolios(
        quotes, bankroll=200, simulation=shared_simulation("1", "2", "3"),
        strategy_bankrolls={"aggressive": 148.0},  # dr=0.74
    )
    aggressive_half = next(p for p in half if p["key"] == "aggressive")

    # Must still have tickets — protection shrinks, doesn't silence
    assert len(aggressive_half["tickets"]) >= 1, "aggressive should still bet when underwater"
    # But total stake should be noticeably smaller
    assert aggressive_half["stake"] < aggressive_full["stake"], (
        f"underwater stake ({aggressive_half['stake']}) should be less than full ({aggressive_full['stake']})"
    )

    # Conservative (no override) stays unchanged
    conservative_full = next(p for p in full if p["key"] == "conservative")
    conservative_half = next(p for p in half if p["key"] == "conservative")
    assert conservative_half["stake"] == conservative_full["stake"]


def test_parlay_probability_and_payout_use_shared_paths_not_probability_roots():
    simulation = TournamentSimulation(
        paths=4,
        seed=1,
        scores_by_match={"m1": [(1, 0), (1, 0), (0, 1), (0, 1)], "m2": [(1, 0), (0, 1), (1, 0), (0, 1)]},
        halftime_scores_by_match={"m1": [(0, 0)] * 4, "m2": [(0, 0)] * 4},
    )
    legs = [
        {"matchId": "m1", "market": "胜平负", "selection": "胜", "odds": 2.0},
        {"matchId": "m2", "market": "胜平负", "selection": "胜", "odds": 2.0},
    ]
    ticket = {"legs": legs, "stake": 10, "potentialPayout": 40}

    assert path_probability(legs, simulation) == 0.25
    result = simulate_portfolio([ticket], 100, simulation)
    assert result["expectedProfit"] == 0.0
    assert result["simulationPaths"] == 4
    assert result["simulationMode"] == "shared_score_paths"
