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


def test_portfolios_respect_bankroll_caps_and_distinct_parlay_matches():
    portfolios = build_portfolios(
        [quote("1", 0.12), quote("2", 0.10), quote("3", 0.08)],
        bankroll=200,
        simulation=shared_simulation("1", "2", "3"),
    )
    caps = {"conservative": 50, "balanced": 80, "aggressive": 120}
    for portfolio in portfolios:
        assert portfolio["stake"] <= caps[portfolio["key"]]
        assert portfolio["stake"] % 2 == 0
        for ticket in portfolio["tickets"]:
            assert ticket["stake"] % 2 == 0
            ids = [leg["matchId"] for leg in ticket["legs"]]
            assert len(ids) == len(set(ids))


def test_negative_edge_produces_no_ticket():
    portfolios = build_portfolios([quote("1", -0.01)], bankroll=200, simulation=shared_simulation("1"))
    assert all(not portfolio["tickets"] for portfolio in portfolios)


def test_observation_only_quote_never_enters_a_formal_portfolio():
    observed = quote("1", 4.0, odds=50.0)
    observed.update({"market": "半全场", "selection": "负负", "recommendation": "观察"})

    portfolios = build_portfolios([observed], bankroll=200, simulation=shared_simulation("1"))

    assert all(not portfolio["tickets"] for portfolio in portfolios)


def test_strategy_market_and_parlay_rules_are_materially_different():
    quotes = [
        quote("1", 0.12, odds=1.80),
        {**quote("2", 0.10, odds=2.20), "market": "总进球数", "selection": "2", "modelProbability": 0.56},
        {**quote("3", 0.09, odds=2.50), "market": "让球胜平负", "selection": "-1 平", "handicap": -1, "modelProbability": 0.48},
        {**quote("4", 0.20, odds=8.00), "market": "半全场", "selection": "胜胜", "modelProbability": 0.18},
        {**quote("5", 0.15, odds=12.0, single=False), "market": "比分", "selection": "2:0", "modelProbability": 0.12},
    ]
    portfolios = {
        item["key"]: item
        for item in build_portfolios(
            quotes,
            bankroll=200,
            simulation=shared_simulation("1", "2", "3", "4", "5"),
        )
    }

    conservative = portfolios["conservative"]
    assert conservative["tickets"]
    assert all(ticket["type"] == "单关" for ticket in conservative["tickets"])
    assert {leg["market"] for ticket in conservative["tickets"] for leg in ticket["legs"]} <= {"胜平负", "总进球数"}

    balanced = portfolios["balanced"]
    assert any(ticket["type"] == "2串1" for ticket in balanced["tickets"])
    assert not {"比分", "半全场"} & {leg["market"] for ticket in balanced["tickets"] for leg in ticket["legs"]}

    aggressive = portfolios["aggressive"]
    aggressive_markets = {leg["market"] for ticket in aggressive["tickets"] for leg in ticket["legs"]}
    assert {"比分", "半全场"} & aggressive_markets
    assert any(ticket["type"] == "3串1" for ticket in aggressive["tickets"])
    assert conservative["strategyRules"] != balanced["strategyRules"] != aggressive["strategyRules"]


def test_all_markets_settle_from_the_same_score_path():
    score = (2, 1)
    halftime = (1, 0)

    assert settle_leg({"market": "胜平负", "selection": "胜"}, score, halftime)
    assert settle_leg({"market": "让球胜平负", "selection": "-1 平", "handicap": -1}, score, halftime)
    assert settle_leg({"market": "比分", "selection": "2:1"}, score, halftime)
    assert settle_leg({"market": "总进球数", "selection": "3"}, score, halftime)
    assert settle_leg({"market": "半全场", "selection": "胜胜"}, score, halftime)


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
