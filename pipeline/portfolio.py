from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from .simulation import TournamentSimulation


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    subtitle: str
    kelly_fraction: float
    bankroll_cap: float
    score_cap: float
    max_parlay: int
    single_markets: tuple[str, ...]
    parlay_markets: tuple[str, ...]
    min_coverage: float
    min_probability: float
    min_edge: float
    max_odds: float
    max_singles: int
    max_volatile_parlay_legs: int
    rules: tuple[str, ...]


STRATEGIES = (
    Strategy(
        "conservative", "稳健", "高胜率单关，拒绝串关", 0.25, 0.25, 0.0, 1,
        ("胜平负", "总进球数"), (), 0.80, 0.55, 0.02, 2.25, 2, 0,
        ("只选覆盖率≥80%的高概率单关", "仅胜平负/总进球数", "不做串关和比分"),
    ),
    Strategy(
        "balanced", "均衡", "价值单关 + 1注2串1", 0.50, 0.40, 0.0, 2,
        ("胜平负", "让球胜平负", "总进球数"), ("胜平负", "让球胜平负", "总进球数"),
        0.78, 0.35, 0.01, 4.50, 3, 0,
        ("优先稳健正期望标的", "覆盖胜平负/让球/总进球", "最多1注2串1"),
    ),
    Strategy(
        "aggressive", "激进", "高赔率市场 + 受控串关", 0.75, 0.60, 0.10, 3,
        ("胜平负", "让球胜平负", "比分", "总进球数", "半全场"),
        ("胜平负", "让球胜平负", "比分", "总进球数", "半全场"),
        0.75, 0.08, 0.0, 80.0, 4, 1,
        ("允许比分/半全场小注", "按赔率与稳健期望共同排序", "可做2串1和3串1"),
    ),
)


def fractional_kelly(probability: float, odds: float, fraction: float) -> float:
    if odds <= 1:
        return 0.0
    full = (probability * odds - 1) / (odds - 1)
    return max(0.0, full * fraction)


def round_to_ticket(value: float) -> int:
    return max(0, int(value // 2) * 2)


def _single_candidates(quotes: list[dict[str, Any]], strategy: Strategy) -> list[dict[str, Any]]:
    candidates = [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("singleEligible")
        and quote.get("market") in strategy.single_markets
        and quote.get("recommendation") in {"重点推荐", "小注可选"}
        and float(quote.get("coverage") or 0) >= strategy.min_coverage
        and float(quote.get("modelProbability") or 0) >= strategy.min_probability
        and float(quote.get("robustExpectedReturn") or -1) >= strategy.min_edge
        and quote.get("odds")
        and float(quote["odds"]) <= strategy.max_odds
    ]
    return sorted(candidates, key=lambda item: _candidate_score(item, strategy), reverse=True)


def _parlay_candidates(
    quotes: list[dict[str, Any]],
    size: int,
    strategy: Strategy,
) -> list[tuple[dict[str, Any], ...]]:
    positive = [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("market") in strategy.parlay_markets
        and quote.get("recommendation") in {"重点推荐", "小注可选"}
        and float(quote.get("coverage") or 0) >= strategy.min_coverage
        and float(quote.get("modelProbability") or 0) >= strategy.min_probability
        and float(quote.get("robustExpectedReturn") or -1) >= strategy.min_edge
        and quote.get("odds")
        and float(quote["odds"]) <= strategy.max_odds
    ]
    combinations = []
    for group in itertools.combinations(positive, size):
        volatile_legs = sum(item["market"] in {"比分", "半全场"} for item in group)
        if (
            len({item["matchId"] for item in group}) == size
            and volatile_legs <= strategy.max_volatile_parlay_legs
        ):
            combinations.append(group)
    return combinations


def _candidate_score(quote: dict[str, Any], strategy: Strategy) -> tuple[float, float]:
    probability = float(quote["modelProbability"])
    robust_edge = float(quote["robustExpectedReturn"])
    odds = float(quote["odds"])
    if strategy.key == "conservative":
        return probability, robust_edge
    if strategy.key == "balanced":
        return robust_edge, probability
    return robust_edge * math.log(max(odds, 1.01)), odds


def _parlay_score(group: tuple[dict[str, Any], ...], strategy: Strategy) -> float:
    edge_score = math.prod(1 + float(item["robustExpectedReturn"]) for item in group)
    if strategy.key == "aggressive":
        return edge_score * math.log(math.prod(float(item["odds"]) for item in group))
    return edge_score


def build_portfolios(
    quotes: list[dict[str, Any]],
    bankroll: int = 200,
    simulation: TournamentSimulation | None = None,
) -> list[dict[str, Any]]:
    results = []
    for strategy in STRATEGIES:
        cap = round_to_ticket(bankroll * strategy.bankroll_cap)
        tickets: list[dict[str, Any]] = []
        used = 0
        parlay_reserve = 0
        if strategy.max_parlay == 2:
            parlay_reserve = round_to_ticket(bankroll * 0.05)
        elif strategy.max_parlay == 3:
            parlay_reserve = round_to_ticket(bankroll * 0.20)
        singles = _single_candidates(quotes, strategy)
        used_match_ids: set[str] = set()
        for quote in singles:
            if len(used_match_ids) >= strategy.max_singles or quote["matchId"] in used_match_ids:
                continue
            robust_probability = (1 + quote["robustExpectedReturn"]) / quote["odds"]
            suggested = round_to_ticket(bankroll * fractional_kelly(robust_probability, quote["odds"], strategy.kelly_fraction))
            maximum = round_to_ticket(bankroll * (strategy.score_cap if quote["market"] == "比分" else 0.12))
            stake = min(maximum, max(2, suggested), cap - parlay_reserve - used)
            if stake < 2:
                continue
            tickets.append(_ticket_from_quotes(
                [quote], stake, "比分" if quote["market"] == "比分" else "单关", simulation
            ))
            used += stake
            used_match_ids.add(quote["matchId"])
        if strategy.max_parlay >= 2 and used + 2 <= cap:
            candidates = _parlay_candidates(quotes, 2, strategy)
            if candidates:
                best = max(candidates, key=lambda group: _parlay_score(group, strategy))
                stake = min(round_to_ticket(bankroll * (0.05 if strategy.key != "aggressive" else 0.12)), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "2串1", simulation))
                    used += stake
        if strategy.max_parlay >= 3 and used + 2 <= cap:
            candidates = _parlay_candidates(quotes, 3, strategy)
            if candidates:
                best = max(candidates, key=lambda group: _parlay_score(group, strategy))
                stake = min(round_to_ticket(bankroll * 0.08), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "3串1", simulation))
                    used += stake
        simulation_summary = simulate_portfolio(tickets, bankroll, simulation)
        results.append({
            "key": strategy.key,
            "name": strategy.name,
            "subtitle": strategy.subtitle,
            "stake": used,
            "retainedCash": bankroll - used,
            "strategyRules": list(strategy.rules),
            "tickets": tickets,
            **simulation_summary,
        })
    return results


def _ticket_from_quotes(
    quotes: list[dict[str, Any]],
    stake: int,
    ticket_type: str,
    simulation: TournamentSimulation | None,
) -> dict[str, Any]:
    combined_odds = math.prod(float(quote["odds"]) for quote in quotes)
    legs = [{
        "matchId": quote["matchId"],
        "label": quote["label"],
        "market": quote["market"],
        "selection": quote["selection"],
        "handicap": quote.get("handicap"),
        "odds": quote["odds"],
        "excludedScores": quote.get("excludedScores", []),
    } for quote in quotes]
    if simulation is None:
        if quotes:
            raise ValueError("shared tournament simulation is required to price tickets")
        model_probability = 0.0
    else:
        model_probability = path_probability(legs, simulation)
    robust_ratios = []
    for quote in quotes:
        model = float(quote["modelProbability"])
        robust = (1 + float(quote["robustExpectedReturn"])) / float(quote["odds"])
        robust_ratios.append(min(1.0, robust / model) if model > 0 else 0.0)
    robust_probability = model_probability * min(robust_ratios, default=0.0)
    return {
        "id": "-".join(quote["id"] for quote in quotes),
        "type": ticket_type,
        "legs": legs,
        "stake": stake,
        "combinedOdds": round(combined_odds, 3),
        "modelProbability": round(model_probability, 5),
        "robustExpectedReturn": round(robust_probability * combined_odds - 1, 5),
        "potentialPayout": round(stake * combined_odds, 2),
    }


def settle_leg(leg: dict[str, Any], score: tuple[int, int], halftime: tuple[int, int]) -> bool:
    home, away = score
    half_home, half_away = halftime
    market = leg["market"]
    selection = str(leg["selection"])

    def label(left: int, right: int) -> str:
        return "胜" if left > right else "平" if left == right else "负"

    if market == "胜平负":
        return selection == label(home, away)
    if market == "让球胜平负":
        handicap = int(leg.get("handicap") or 0)
        return selection.split()[-1] == label(home + handicap, away)
    if market == "比分":
        actual = f"{home}:{away}"
        if ":" in selection and selection.replace(":", "").isdigit():
            return selection == actual
        other = {"胜其它": "胜", "平其它": "平", "负其它": "负"}.get(selection)
        return bool(other and label(home, away) == other and actual not in set(leg.get("excludedScores", [])))
    if market == "总进球数":
        total = home + away
        return total >= 7 if selection in {"7", "7+"} else total == int(selection)
    if market == "半全场":
        return selection == f"{label(half_home, half_away)}{label(home, away)}"
    raise ValueError(f"unsupported market: {market}")


def path_probability(legs: list[dict[str, Any]], simulation: TournamentSimulation) -> float:
    wins = 0
    for path_index in range(simulation.paths):
        if all(settle_leg(
            leg,
            simulation.scores_by_match[leg["matchId"]][path_index],
            simulation.halftime_scores_by_match[leg["matchId"]][path_index],
        ) for leg in legs):
            wins += 1
    return wins / simulation.paths


def simulate_portfolio(
    tickets: list[dict[str, Any]],
    bankroll: int,
    simulation: TournamentSimulation | None,
) -> dict[str, Any]:
    total_stake = sum(ticket["stake"] for ticket in tickets)
    if simulation is None:
        if tickets:
            raise ValueError("shared tournament simulation is required to settle tickets")
        return {
            "expectedProfit": 0.0,
            "profitProbability": 0.0,
            "lossProbability": 0.0,
            "stopProbability": 0.0,
            "medianMaxDrawdown": 0.0,
            "worstCase95": 0,
            "p05": bankroll,
            "median": bankroll,
            "p95": bankroll,
            "maxPayout": bankroll,
            "simulationPaths": 0,
            "simulationMode": "no_tickets",
            "distribution": [{"bankroll": bankroll, "probability": 1.0}],
        }
    outcomes = []
    drawdowns = []
    for path_index in range(simulation.paths):
        payout = 0.0
        for ticket in tickets:
            if all(settle_leg(
                leg,
                simulation.scores_by_match[leg["matchId"]][path_index],
                simulation.halftime_scores_by_match[leg["matchId"]][path_index],
            ) for leg in ticket["legs"]):
                payout += ticket["potentialPayout"]
        closing = bankroll - total_stake + payout
        outcomes.append(closing)
        drawdowns.append(max(0.0, (bankroll - closing) / bankroll) if bankroll else 0.0)
    outcomes.sort()
    drawdowns.sort()
    profits = [value - bankroll for value in outcomes]
    expected_profit = sum(profits) / simulation.paths
    p05 = outcomes[int(simulation.paths * 0.05)]
    median = outcomes[int(simulation.paths * 0.50)]
    p95 = outcomes[int(simulation.paths * 0.95)]
    histogram = _histogram(outcomes, bins=44)
    return {
        "expectedProfit": round(expected_profit, 1),
        "profitProbability": round(sum(value > bankroll for value in outcomes) / simulation.paths, 4),
        "lossProbability": round(sum(value < bankroll for value in outcomes) / simulation.paths, 4),
        "stopProbability": round(sum(value <= 0 for value in outcomes) / simulation.paths, 4),
        "medianMaxDrawdown": round(drawdowns[int(simulation.paths * 0.50)], 4),
        "worstCase95": round(p05 - bankroll),
        "p05": round(p05),
        "median": round(median),
        "p95": round(p95),
        "maxPayout": round(max(outcomes)),
        "simulationPaths": simulation.paths,
        "simulationMode": "shared_score_paths",
        "distribution": histogram,
    }


def _histogram(values: list[float], bins: int) -> list[dict[str, float | int]]:
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [{"bankroll": round(low), "probability": 1.0}]
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = min(bins - 1, int((value - low) / width))
        counts[index] += 1
    return [
        {"bankroll": round(low + (index + 0.5) * width), "probability": round(count / len(values), 6)}
        for index, count in enumerate(counts)
    ]
