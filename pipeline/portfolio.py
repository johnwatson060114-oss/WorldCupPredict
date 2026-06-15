from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    subtitle: str
    kelly_fraction: float
    bankroll_cap: float
    score_cap: float
    max_parlay: int


STRATEGIES = (
    Strategy("conservative", "稳健", "单关为主，低回撤", 0.25, 0.25, 0.02, 2),
    Strategy("balanced", "均衡", "单关 + 1注2串1", 0.50, 0.40, 0.05, 2),
    Strategy("aggressive", "激进", "受控串关 + 比分小注", 0.75, 0.60, 0.10, 3),
)


def fractional_kelly(probability: float, odds: float, fraction: float) -> float:
    if odds <= 1:
        return 0.0
    full = (probability * odds - 1) / (odds - 1)
    return max(0.0, full * fraction)


def round_to_ticket(value: float) -> int:
    return max(0, int(value // 2) * 2)


def _single_candidates(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("singleEligible")
        and quote.get("recommendation") in {"重点推荐", "小注可选"}
        and (quote.get("robustExpectedReturn") or -1) > 0
        and quote.get("odds")
    ]


def _parlay_candidates(quotes: list[dict[str, Any]], size: int) -> list[tuple[dict[str, Any], ...]]:
    positive = [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("market") != "比分"
        and quote.get("recommendation") in {"重点推荐", "小注可选"}
        and (quote.get("robustExpectedReturn") or -1) > 0
        and quote.get("odds")
    ]
    combinations = []
    for group in itertools.combinations(positive, size):
        if len({item["matchId"] for item in group}) == size:
            combinations.append(group)
    return combinations


def build_portfolios(quotes: list[dict[str, Any]], bankroll: int = 200, seed: int = 20260614) -> list[dict[str, Any]]:
    results = []
    for strategy in STRATEGIES:
        cap = round_to_ticket(bankroll * strategy.bankroll_cap)
        tickets: list[dict[str, Any]] = []
        used = 0
        singles = sorted(_single_candidates(quotes), key=lambda item: item["robustExpectedReturn"], reverse=True)
        for quote in singles:
            robust_probability = (1 + quote["robustExpectedReturn"]) / quote["odds"]
            suggested = round_to_ticket(bankroll * fractional_kelly(robust_probability, quote["odds"], strategy.kelly_fraction))
            maximum = round_to_ticket(bankroll * (strategy.score_cap if quote["market"] == "比分" else 0.12))
            stake = min(maximum, max(2, suggested), cap - used)
            if stake < 2:
                continue
            tickets.append(_ticket_from_quotes([quote], stake, "比分" if quote["market"] == "比分" else "单关"))
            used += stake
        if strategy.max_parlay >= 2 and used + 2 <= cap:
            candidates = _parlay_candidates(quotes, 2)
            if candidates:
                best = max(candidates, key=lambda group: math.prod(1 + item["robustExpectedReturn"] for item in group))
                stake = min(round_to_ticket(bankroll * (0.05 if strategy.key != "aggressive" else 0.12)), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "2串1"))
                    used += stake
        if strategy.max_parlay >= 3 and used + 2 <= cap:
            candidates = _parlay_candidates(quotes, 3)
            if candidates:
                best = max(candidates, key=lambda group: math.prod(1 + item["robustExpectedReturn"] for item in group))
                stake = min(round_to_ticket(bankroll * 0.08), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "3串1"))
                    used += stake
        simulation = simulate_portfolio(tickets, bankroll, seed + len(results))
        results.append({
            "key": strategy.key,
            "name": strategy.name,
            "subtitle": strategy.subtitle,
            "stake": used,
            "retainedCash": bankroll - used,
            "tickets": tickets,
            **simulation,
        })
    return results


def _ticket_from_quotes(quotes: list[dict[str, Any]], stake: int, ticket_type: str) -> dict[str, Any]:
    combined_odds = math.prod(float(quote["odds"]) for quote in quotes)
    model_probability = math.prod(float(quote["modelProbability"]) for quote in quotes)
    robust_probability = math.prod((1 + float(quote["robustExpectedReturn"])) / float(quote["odds"]) for quote in quotes)
    return {
        "id": "-".join(quote["id"] for quote in quotes),
        "type": ticket_type,
        "legs": [{
            "matchId": quote["matchId"],
            "label": quote["label"],
            "market": quote["market"],
            "selection": quote["selection"],
            "odds": quote["odds"],
        } for quote in quotes],
        "stake": stake,
        "combinedOdds": round(combined_odds, 3),
        "modelProbability": round(model_probability, 5),
        "robustExpectedReturn": round(robust_probability * combined_odds - 1, 5),
        "potentialPayout": round(stake * combined_odds, 2),
    }


def simulate_portfolio(tickets: list[dict[str, Any]], bankroll: int, seed: int, samples: int = 30_000) -> dict[str, Any]:
    randomizer = random.Random(seed)
    outcomes = []
    total_stake = sum(ticket["stake"] for ticket in tickets)
    for _ in range(samples):
        payout = 0.0
        match_draws: dict[str, float] = {}
        for ticket in tickets:
            wins = True
            for leg in ticket["legs"]:
                draw = match_draws.setdefault(leg["matchId"], randomizer.random())
                leg_probability = ticket["modelProbability"] ** (1 / max(1, len(ticket["legs"])))
                if draw >= leg_probability:
                    wins = False
                    break
            if wins:
                payout += ticket["potentialPayout"]
        outcomes.append(bankroll - total_stake + payout)
    outcomes.sort()
    profits = [value - bankroll for value in outcomes]
    expected_profit = sum(profits) / samples
    p05 = outcomes[int(samples * 0.05)]
    median = outcomes[int(samples * 0.50)]
    p95 = outcomes[int(samples * 0.95)]
    histogram = _histogram(outcomes, bins=44)
    return {
        "expectedProfit": round(expected_profit, 1),
        "profitProbability": round(sum(value > bankroll for value in outcomes) / samples, 4),
        "lossProbability": round(sum(value < bankroll for value in outcomes) / samples, 4),
        "worstCase95": round(p05 - bankroll),
        "p05": round(p05),
        "median": round(median),
        "p95": round(p95),
        "maxPayout": round(max(outcomes)),
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
