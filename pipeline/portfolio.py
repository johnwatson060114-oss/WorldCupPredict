from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from .drawdown import (
    adjusted_max_singles,
    drawdown_ratio,
    edge_multiplier,
    stake_multiplier as dr_stake_multiplier,
)
from .simulation import TournamentSimulation


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    subtitle: str
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
    # Combo quality gates (entertainment/fallback mode).
    # min_combo_roi: expected ROI floor — combos below this are rejected.
    # min_payout_ratio: worst-case (minimum) individual payout / total stake.
    #   Prevents combos where the most likely outcome still loses most of the
    #   stake (e.g. 100%-coverage 胜平负 where every payout < cost).
    min_combo_roi: float = -1.0
    min_payout_ratio: float = 0.0


STRATEGIES = (
    Strategy(
        "conservative", "稳健", "低波动单关精选", 0.0, 1,
        ("胜平负", "让球胜平负", "总进球数"), (), 0.80, 0.55, 0.02, 2.25, 2, 0,
        ("低波动：只做次日单关", "胜平负/让球/总进球", "高覆盖与正稳健期望优先", "无正期望时0元不投"),
        max_combo_per_market=1, min_combo_coverage=0.55,
        negative_edge_fallback=False, negative_edge_min=0.0,
        min_combo_roi=0.05, min_payout_ratio=0.80,
    ),
    Strategy(
        "balanced", "均衡", "中波动复式 + 跨天2串1", 0.0, 2,
        ("胜平负", "让球胜平负", "总进球数"), ("胜平负", "让球胜平负", "总进球数"),
        0.78, 0.35, 0.01, 4.50, 3, 0,
        ("中波动：次日单关 + 在售跨天2串1", "胜平负/让球/总进球", "复式提高覆盖，接受中等赔率波动", "预期回报率≥-10%，最差情况返本≥60%"),
        max_combo_per_market=2, min_combo_coverage=0.55, combo_edge_tolerance=-0.01,
        negative_edge_fallback=False, negative_edge_min=0.0,
        min_combo_roi=-0.10, min_payout_ratio=0.60,
    ),
    Strategy(
        "aggressive", "激进", "高波动全玩法 + 跨天3串1", 0.10, 3,
        ("胜平负", "让球胜平负", "比分", "总进球数", "半全场"),
        ("胜平负", "让球胜平负", "比分", "总进球数", "半全场"),
        0.75, 0.08, 0.0, 80.0, 4, 1,
        ("高波动：次日单关 + 在售跨天2/3串1", "比分/半全场可入池", "赔率弹性更高，命中概率更低", "预期回报率≥-15%，最差返本≥40%"),
        max_combo_per_market=2, min_combo_coverage=0.35, combo_edge_tolerance=-0.05,
        negative_edge_fallback=False, negative_edge_min=0.0,
        min_combo_roi=-0.15, min_payout_ratio=0.40,
    ),
)


STANDARD_KELLY_FRACTION = 0.25
ENTERTAINMENT_STAKE_FRACTION = 0.03
PARLAY_STAKE_FRACTIONS = {2: 0.05, 3: 0.04}
DEFAULT_SINGLE_CAP = 0.12


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
        if quote.get("formalEligible") is True
        and quote.get("available")
        and quote.get("market") in strategy.single_markets
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
    required_match_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], ...]]:
    positive = [
        quote for quote in quotes
        if quote.get("formalEligible") is True
        and quote.get("available")
        and quote.get("market") in strategy.parlay_markets
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
            and (
                required_match_ids is None
                or any(item["matchId"] in required_match_ids for item in group)
            )
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
        if quote.get("formalEligible") is True
        and quote.get("available")
        and quote.get("market") in strategy.single_markets
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
            # If size-1 doesn't meet the combo-level threshold, don't try
            # larger combos — adding a worse pick can't fix a failing best pick.
            if pick_size == 1 and (coverage < strategy.min_combo_coverage or combined_edge < strategy.combo_edge_tolerance):
                break
    return combos


def _combo_fallback_groups(
    quotes: list[dict[str, Any]],
    strategy: Strategy,
) -> list[tuple[dict[str, Any], ...]]:
    """Degraded-mode combo selection based on probability coverage.

    When real-time sporttery odds are unavailable, all robustExpectedReturn
    values are model-computed and universally negative. Edge-based filtering
    is meaningless in this regime — it either produces zero bets or selects
    extreme near-1.01 handicap bets that don't exist on real sporttery.

    Instead, this function selects combos by model probability coverage,
    which still carries predictive signal. This is the natural home for
    复式投注 (multi-selection combos): buying 2 selections in the same
    market to increase hit probability.

    - Drops singleEligible (degraded mode never has it).
    - Does NOT filter by edge (all edges are fake when odds are snapshots).
    - Sorts by modelProbability descending (most likely outcomes first).
    - Does NOT break on size-1 failure — 复式 exists precisely because
      size-2 achieves coverage that size-1 alone cannot.
    - Only checks min_combo_coverage at the combo level.
    """
    fallback_coverage = max(0.60, strategy.min_coverage - 0.15)
    # Use a generous individual-probability floor so the top 2 options
    # per market both pass.  The combo-level min_combo_coverage is the
    # real quality gate — this pre-filter just removes noise (< 10%).
    fallback_probability = max(0.05, strategy.min_probability - 0.25)
    fallback_max_odds = max(strategy.max_odds, 200.0)

    relaxed = [
        quote for quote in quotes
        if quote.get("available")
        and quote.get("market") in strategy.single_markets
        and quote.get("recommendation") in {"重点推荐", "小注可选", "观察", "不建议"}
        and float(quote.get("coverage") or 0) >= fallback_coverage
        and float(quote.get("modelProbability") or 0) >= fallback_probability
        and quote.get("odds")
        and float(quote["odds"]) <= fallback_max_odds
    ]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for quote in relaxed:
        key = (quote["matchId"], quote["market"])
        groups.setdefault(key, []).append(quote)

    combos: list[tuple[dict[str, Any], ...]] = []
    for (_match_id, _market), group in groups.items():
        sorted_group = sorted(
            group,
            key=lambda q: float(q["modelProbability"]),
            reverse=True,
        )
        max_pick = min(strategy.max_combo_per_market, len(sorted_group))
        if max_pick <= 0:
            continue

        for pick_size in range(1, max_pick + 1):
            combo = tuple(sorted_group[:pick_size])
            coverage = sum(float(q["modelProbability"]) for q in combo)
            if coverage >= strategy.min_combo_coverage:
                # Reject combos that cover ALL outcomes of a multi-outcome
                # market (e.g. win+draw+loss on 胜平负).  Hitting is
                # guaranteed but the payout never covers total stake.
                if pick_size == len(group) and len(group) > 1:
                    continue
                combos.append(combo)
            # Do NOT break if size-1 fails coverage.
            # 复式投注: 让胜+让平 together cover >55% even when
            # neither alone reaches the threshold.

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
    parlay_quotes: list[dict[str, Any]] | None = None,
    strategy_bankrolls: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    results = []
    for strategy in STRATEGIES:
        # --- Drawdown protection ---
        strategy_br = (strategy_bankrolls or {}).get(strategy.key, float(bankroll))
        strategy_br = max(strategy_br, 2.0)  # never below minimum ticket
        dr = drawdown_ratio(strategy_br, float(bankroll))
        stake_mult = dr_stake_multiplier(dr)
        edge_mult = edge_multiplier(dr)

        cap = round_to_ticket(bankroll)
        tickets: list[dict[str, Any]] = []
        used = 0
        entertainment_mode = False

        # Get single-ticket candidate combos
        adjusted_min_edge = strategy.min_edge * edge_mult
        strict_quotes = _filter_quotes(quotes, strategy, edge_min=adjusted_min_edge)
        combos = _build_combo_groups(strict_quotes, strategy)

        # Formal portfolios never fall back to negative-edge or simulated
        # odds. Entertainment betting is an explicit user action and is kept
        # outside tracked strategy performance.

        # Sort combos: larger combos (more picks) first, then by coverage.
        # This ensures the 复式 (multi-pick) version of a match+market gets
        # priority over the single-pick version, since they share a matchId.
        combos.sort(
            key=lambda c: (len(c), sum(float(q["modelProbability"]) for q in c)),
            reverse=True,
        )

        used_match_ids: set[str] = set()
        effective_max_singles = adjusted_max_singles(strategy.max_singles, dr)
        for combo in combos:
            match_id = combo[0]["matchId"]
            if len(used_match_ids) >= effective_max_singles or match_id in used_match_ids:
                continue

            # Calculate stakes for each leg in the combo.
            # In entertainment mode, allocate proportionally to each leg's
            # model probability so the high-confidence outcome carries more
            # money (improving worst-case payout ratio).
            # Then validate: expected ROI and minimum payout ratio must pass
            # strategy thresholds.
            combo_stake = 0
            combo_tickets: list[dict[str, Any]] = []
            combo_coverage = sum(float(q["modelProbability"]) for q in combo)

            # Determine per-leg weight (probability-proportional)
            probs = [float(q["modelProbability"]) for q in combo]
            total_prob = sum(probs) or 1.0

            for idx, quote in enumerate(combo):
                weight = probs[idx] / total_prob
                if entertainment_mode:
                    coverage_ratio = combo_coverage / max(strategy.min_combo_coverage, 0.01)
                    suggested = round_to_ticket(bankroll * ENTERTAINMENT_STAKE_FRACTION * coverage_ratio * weight * len(combo) * stake_mult)
                else:
                    robust_probability = (1 + quote["robustExpectedReturn"]) / quote["odds"]
                    suggested = round_to_ticket(bankroll * fractional_kelly(robust_probability, quote["odds"], STANDARD_KELLY_FRACTION) * stake_mult)
                maximum = round_to_ticket(bankroll * (strategy.score_cap if quote["market"] == "比分" else DEFAULT_SINGLE_CAP) * stake_mult)
                stake = min(maximum, max(2, suggested), cap - used - combo_stake)
                if stake < 2:
                    continue
                ticket = _ticket_from_quotes(
                    [quote], stake, "比分" if quote["market"] == "比分" else "单关", simulation
                )
                combo_tickets.append(ticket)
                combo_stake += stake

            # --- Combo quality gate: ROI + worst-case payout ratio ---
            if len(combo_tickets) >= 2 and combo_stake >= 4:
                expected_return = sum(
                    probs[i] * combo_tickets[i]["potentialPayout"]
                    for i in range(len(combo_tickets))
                )
                expected_roi = (expected_return - combo_stake) / combo_stake
                min_payout = min(t["potentialPayout"] for t in combo_tickets)
                min_payout_ratio = min_payout / combo_stake

                if expected_roi < strategy.min_combo_roi or min_payout_ratio < strategy.min_payout_ratio:
                    # Combo fails quality gate — skip it entirely
                    continue

                # Tag combo tickets for frontend display
                coverage_pct = round(combo_coverage * 100)
                for t in combo_tickets:
                    t["comboGroup"] = {
                        "matchId": match_id,
                        "market": combo[0]["market"],
                        "size": len(combo),
                        "coveragePct": coverage_pct,
                        "expectedRoi": round(expected_roi * 100),
                        "minPayoutRatio": round(min_payout_ratio * 100),
                    }
            elif len(combo_tickets) == 1 and len(combo) > 1:
                # Multi-leg combo but only 1 leg got budget — downgrade to single
                pass
            elif len(combo_tickets) == 1 and len(combo) == 1:
                # Single ticket (not a combo).
                # In entertainment mode, skip ultra-low-odds bets (e.g. 1.01)
                # — the upside is negligible and the budget is better spent on combos.
                if entertainment_mode and float(combo[0]["odds"]) < 1.20:
                    continue

            tickets.extend(combo_tickets)
            used += combo_stake
            used_match_ids.add(match_id)

        cross_day_parlays = parlay_quotes is not None
        parlay_source = parlay_quotes if cross_day_parlays else quotes
        current_match_ids = {quote["matchId"] for quote in quotes}

        # Parlay logic: legs must come from matches NOT already covered by
        # single tickets.  Without this guard you get wasteful duplicates like
        # 单关(A) + 单关(B) + 2串1(A,B) — same exposure, double the cost.
        # Normal parlays introduce new match exposures. Cross-day parlays may
        # reuse a current-day match as the required anchor, but combinations
        # made entirely from future matches are not today's recommendations.
        if strategy.max_parlay >= 2 and used + 2 <= cap:
            filtered_parlay_quotes = [
                q for q in _filter_quotes(parlay_source, strategy, edge_min=adjusted_min_edge)
                if q["matchId"] not in used_match_ids
                or (cross_day_parlays and q["matchId"] in current_match_ids)
            ]
            candidates = _parlay_candidates(
                filtered_parlay_quotes,
                2,
                strategy,
                required_match_ids=current_match_ids if cross_day_parlays else None,
            )
            if candidates:
                best = max(candidates, key=lambda group: _parlay_score(group, strategy))
                stake = min(round_to_ticket(bankroll * PARLAY_STAKE_FRACTIONS[2] * stake_mult), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "2串1", simulation))
                    used += stake
        if strategy.max_parlay >= 3 and used + 2 <= cap:
            filtered_parlay_quotes = [
                q for q in _filter_quotes(parlay_source, strategy, edge_min=adjusted_min_edge)
                if q["matchId"] not in used_match_ids
                or (cross_day_parlays and q["matchId"] in current_match_ids)
            ]
            candidates = _parlay_candidates(
                filtered_parlay_quotes,
                3,
                strategy,
                required_match_ids=current_match_ids if cross_day_parlays else None,
            )
            if candidates:
                best = max(candidates, key=lambda group: _parlay_score(group, strategy))
                stake = min(round_to_ticket(bankroll * PARLAY_STAKE_FRACTIONS[3] * stake_mult), cap - used)
                if stake >= 2:
                    tickets.append(_ticket_from_quotes(list(best), stake, "3串1", simulation))
                    used += stake

        simulation_summary = simulate_portfolio(tickets, int(strategy_br), simulation)
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
        "kickoffBeijing": quote.get("kickoffBeijing"),
        "lotteryCode": quote.get("lotteryCode"),
        "matchDate": quote.get("matchDate"),
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
