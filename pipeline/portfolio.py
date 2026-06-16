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
    max_combo_per_market: int = 1
    min_combo_coverage: float = 0.0
    combo_edge_tolerance: float = 0.0
    negative_edge_fallback: bool = False
    negative_edge_min: float = 0.0


STRATEGIES = (
    Strategy(
        "conservative", "稳健", "高胜率单关，拒绝串关", 0.25, 0.25, 0.0, 1,
        ("胜平负", "总进球数"), (), 0.80, 0.55, 0.02, 2.25, 2, 0,
        ("只选覆盖率≥80%的高概率单关", "仅胜平负/总进球数", "每玩法只选最佳单个选项"),
        max_combo_per_market=1, negative_edge_fallback=False,
    ),
    Strategy(
        "balanced", "均衡", "价值单关 + 1注2串1", 0.50, 0.40, 0.0, 2,
        ("胜平负", "让球胜平负", "总进球数"), ("胜平负", "让球胜平负", "总进球数"),
        0.78, 0.35, 0.01, 4.50, 3, 0,
        ("正期望优先，允许同场2选复式", "覆盖胜平负/让球/总进球", "最多1注2串1，无正EV时-8%以内"),
        max_combo_per_market=2, min_combo_coverage=0.55, combo_edge_tolerance=-0.01,
        negative_edge_fallback=True, negative_edge_min=-0.08,
    ),
    Strategy(
        "aggressive", "激进", "高赔率市场 + 受控串关", 0.75, 0.60, 0.10, 3,
        ("胜平负", "让球胜平负", "比分", "总进球数", "半全场"),
        ("胜平负", "让球胜平负", "比分", "总进球数", "半全场"),
        0.75, 0.08, 0.0, 80.0, 4, 1,
        ("允许比分/半全场小注，支持同场2选", "降级模式自动放宽至-20%边缘", "可做2串1和3串1，实验观察用"),
        max_combo_per_market=2, min_combo_coverage=0.40, combo_edge_tolerance=-0.05,
        negative_edge_fallback=True, negative_edge_min=-0.20,
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


def _filter_quotes(quotes: list[dict[str, Any]], strategy: Strategy, edge_min: float | None = None) -> list[dict[str, Any]]:
    """Filter quotes by strategy thresholds. Pass edge_min to override strategy.min_edge."""
    min_edge = edge_min if edge_min is not None else strategy.min_edge
    return [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("singleEligible")
        and quote.get("market") in strategy.single_markets
        and quote.get("recommendation") in {"重点推荐", "小注可选"}
        and float(quote.get("coverage") or 0) >= strategy.min_coverage
        and float(quote.get("modelProbability") or 0) >= strategy.min_probability
        and float(quote.get("robustExpectedReturn") or -1) >= min_edge
        and quote.get("odds")
        and float(quote["odds"]) <= strategy.max_odds
    ]


def _build_combo_groups(
    quotes: list[dict[str, Any]],
    strategy: Strategy,
) -> list[tuple[dict[str, Any], ...]]:
    """Group quotes by (matchId, market) and pick the best combos per group.

    For each match+market group, picks up to max_combo_per_market selections.
    Returns a flat list of combo-tuples (each combo is 1-2 quotes from the same match+market).
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for quote in quotes:
        key = (quote["matchId"], quote["market"])
        groups.setdefault(key, []).append(quote)

    combos: list[tuple[dict[str, Any], ...]] = []
    for (match_id, market), group in groups.items():
        sorted_group = sorted(group, key=lambda q: _candidate_score(q, strategy), reverse=True)
        max_pick = min(strategy.max_combo_per_market, len(sorted_group))
        if max_pick <= 0:
            continue
        # Try picking the best 1, then the best 2 (if allowed), as long as thresholds pass
        for pick_size in range(1, max_pick + 1):
            combo = tuple(sorted_group[:pick_size])
            coverage = sum(float(q["modelProbability"]) for q in combo)
            # Combined edge: weighted average of individual robustExpectedReturn
            combined_edge = sum(float(q["robustExpectedReturn"]) for q in combo) / pick_size
            if coverage >= strategy.min_combo_coverage and combined_edge >= strategy.combo_edge_tolerance:
                combos.append(combo)
            # If size-1 doesn't meet thresholds, don't try larger combos
            if pick_size == 1 and (coverage < strategy.min_coverage or combined_edge < strategy.min_edge):
                break
    return combos


def _combo_fallback_groups(
    quotes: list[dict[str, Any]],
    strategy: Strategy,
) -> list[tuple[dict[str, Any], ...]]:
    """Relaxed combo selection when no positive-EV combos exist.

    Drops the singleEligible requirement entirely (degraded mode may have
    no single-eligible quotes). Uses negative_edge_min as the relaxed edge
    floor, includes '观察' and '不建议' recommendations, and lowers
    coverage/probability bars for entertainment strategies.
    """
    # Further relaxed thresholds for fallback mode
    fallback_coverage = max(0.60, strategy.min_coverage - 0.15)
    fallback_probability = max(0.05, strategy.min_probability - 0.10)
    fallback_odds = max(strategy.max_odds, 200.0)  # no odds cap in fallback
    relaxed = [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("market") in strategy.single_markets
        and quote.get("recommendation") in {"重点推荐", "小注可选", "观察", "不建议"}
        and float(quote.get("coverage") or 0) >= fallback_coverage
        and float(quote.get("modelProbability") or 0) >= fallback_probability
        and float(quote.get("robustExpectedReturn") or -99) >= strategy.negative_edge_min
        and quote.get("odds")
        and float(quote["odds"]) <= fallback_odds
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for quote in relaxed:
        key = (quote["matchId"], quote["market"])
        groups.setdefault(key, []).append(quote)

    combos: list[tuple[dict[str, Any], ...]] = []
    for (match_id, market), group in groups.items():
        sorted_group = sorted(group, key=lambda q: _candidate_score(q, strategy), reverse=True)
        max_pick = min(strategy.max_combo_per_market, len(sorted_group))
        if max_pick <= 0:
            continue
        for pick_size in range(1, max_pick + 1):
            combo = tuple(sorted_group[:pick_size])
            coverage = sum(float(q["modelProbability"]) for q in combo)
            combined_edge = sum(float(q["robustExpectedReturn"]) for q in combo) / pick_size
            if coverage >= strategy.min_combo_coverage and combined_edge >= strategy.negative_edge_min:
                combos.append(combo)
            if pick_size == 1 and (coverage < strategy.min_coverage or combined_edge < strategy.negative_edge_min):
                break
    return combos


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
        entertainment_mode = False
        if strategy.max_parlay == 2:
            parlay_reserve = round_to_ticket(bankroll * 0.05)
        elif strategy.max_parlay == 3:
            parlay_reserve = round_to_ticket(bankroll * 0.20)

        # Get single-ticket candidate combos
        strict_quotes = _filter_quotes(quotes, strategy)
        combos = _build_combo_groups(strict_quotes, strategy)

        # Fallback to relaxed edge when no combos found
        if not combos and strategy.negative_edge_fallback:
            combos = _combo_fallback_groups(quotes, strategy)
            if combos:
                entertainment_mode = True

        used_match_ids: set[str] = set()
        for combo in combos:
            match_id = combo[0]["matchId"]
            if len(used_match_ids) >= strategy.max_singles or match_id in used_match_ids:
                continue

            # Calculate stake for each quote in the combo
            combo_stake = 0
            combo_tickets: list[dict[str, Any]] = []
            for quote in combo:
                robust_probability = (1 + quote["robustExpectedReturn"]) / quote["odds"]
                suggested = round_to_ticket(bankroll * fractional_kelly(robust_probability, quote["odds"], strategy.kelly_fraction))
                maximum = round_to_ticket(bankroll * (strategy.score_cap if quote["market"] == "比分" else 0.12))
                stake = min(maximum, max(2, suggested), cap - parlay_reserve - used - combo_stake)
                if stake < 2:
                    continue
                ticket = _ticket_from_quotes(
                    [quote], stake, "比分" if quote["market"] == "比分" else "单关", simulation
                )
                # Tag combo tickets for frontend display
                if len(combo) > 1:
                    coverage_pct = round(sum(float(q["modelProbability"]) for q in combo) * 100)
                    ticket["comboGroup"] = {
                        "matchId": match_id,
                        "market": quote["market"],
                        "size": len(combo),
                        "coveragePct": coverage_pct,
                    }
                combo_tickets.append(ticket)
                combo_stake += stake

            tickets.extend(combo_tickets)
            used += combo_stake
            used_match_ids.add(match_id)

        # Parlay logic (unchanged)
        if strategy.max_parlay >= 2 and used + 2 <= cap:
            parlay_quotes = _filter_quotes(quotes, strategy)
            candidates = _parlay_candidates(parlay_quotes, 2, strategy)
            if candidates:
                best = max(candidates, key=lambda group: _parlay_score(group, strategy))
                stake = min(round_to_ticket(bankroll * (0.05 if strategy.key != "aggressive" else 0.12)), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "2串1", simulation))
                    used += stake
        if strategy.max_parlay >= 3 and used + 2 <= cap:
            parlay_quotes = _filter_quotes(quotes, strategy)
            candidates = _parlay_candidates(parlay_quotes, 3, strategy)
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
            "entertainmentMode": entertainment_mode,
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
