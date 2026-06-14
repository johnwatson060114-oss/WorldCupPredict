from pipeline.portfolio import build_portfolios, round_to_ticket


def quote(match_id: str, edge: float, odds: float = 2.0, single: bool = True):
    return {
        "id": f"q-{match_id}", "matchId": match_id, "label": f"A{match_id} vs B{match_id}",
        "market": "胜平负", "selection": "胜", "odds": odds, "modelProbability": 0.60,
        "robustExpectedReturn": edge, "available": True, "singleEligible": single,
    }


def test_rounding_is_two_yuan_increment():
    assert round_to_ticket(11.9) == 10
    assert round_to_ticket(2.0) == 2
    assert round_to_ticket(1.9) == 0


def test_portfolios_respect_bankroll_caps_and_distinct_parlay_matches():
    portfolios = build_portfolios([quote("1", 0.12), quote("2", 0.10), quote("3", 0.08)], bankroll=200)
    caps = {"conservative": 50, "balanced": 80, "aggressive": 120}
    for portfolio in portfolios:
        assert portfolio["stake"] <= caps[portfolio["key"]]
        assert portfolio["stake"] % 2 == 0
        for ticket in portfolio["tickets"]:
            assert ticket["stake"] % 2 == 0
            ids = [leg["matchId"] for leg in ticket["legs"]]
            assert len(ids) == len(set(ids))


def test_negative_edge_produces_no_ticket():
    portfolios = build_portfolios([quote("1", -0.01)], bankroll=200)
    assert all(not portfolio["tickets"] for portfolio in portfolios)
