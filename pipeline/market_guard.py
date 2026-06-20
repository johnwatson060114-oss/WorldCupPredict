from __future__ import annotations

from typing import Any

from .model import normalized_market_probabilities, outcome_probabilities, score_matrix


MARKET_PROBABILITY_GAP_THRESHOLD = 0.15
MARKET_FAVORITE_THRESHOLD = 0.55
MARKET_STRENGTH_BLEND = 0.35
MARKET_STRENGTH_MAX_XG_SHIFT = 0.20


def market_conflict_decision(
    model_probabilities: dict[str, float],
    market_probabilities: dict[str, float | None],
    gap_threshold: float = MARKET_PROBABILITY_GAP_THRESHOLD,
    favorite_threshold: float = MARKET_FAVORITE_THRESHOLD,
) -> dict[str, Any]:
    if not model_probabilities or any(market_probabilities.get(key) is None for key in model_probabilities):
        return {
            "status": "unavailable",
            "blocked": True,
            "maxGap": None,
            "modelFavorite": None,
            "marketFavorite": None,
            "reason": "缺少完整官方市场概率，不能进入正式资金方案",
        }

    market = {key: float(market_probabilities[key]) for key in model_probabilities}
    max_gap = max(abs(float(model_probabilities[key]) - market[key]) for key in model_probabilities)
    model_favorite = max(model_probabilities, key=model_probabilities.get)
    market_favorite = max(market, key=market.get)
    favorite_conflict = model_favorite != market_favorite and market[market_favorite] >= favorite_threshold
    blocked = max_gap > gap_threshold or favorite_conflict

    if max_gap > gap_threshold:
        reason = f"模型与市场最大概率差 {max_gap:.1%} 超过 {gap_threshold:.0%}"
    elif favorite_conflict:
        reason = f"市场热门概率 {market[market_favorite]:.1%}，但模型首选方向相反"
    else:
        reason = "模型与市场未触发严重冲突门槛"
    return {
        "status": "conflict" if blocked else "clear",
        "blocked": blocked,
        "maxGap": round(max_gap, 6),
        "modelFavorite": model_favorite,
        "marketFavorite": market_favorite,
        "reason": reason,
    }


def _market_implied_xg_split(total_xg: float, market: dict[str, float]) -> tuple[float, float]:
    target_points = market["home"] + 0.5 * market["draw"]
    low, high = 0.15, max(0.15, total_xg - 0.15)
    for _ in range(40):
        home_xg = (low + high) / 2
        away_xg = max(0.15, total_xg - home_xg)
        probabilities = outcome_probabilities(score_matrix(home_xg, away_xg))
        expected_points = probabilities["home"] + 0.5 * probabilities["draw"]
        if expected_points < target_points:
            low = home_xg
        else:
            high = home_xg
    home_xg = (low + high) / 2
    return home_xg, max(0.15, total_xg - home_xg)


def apply_market_strength_calibration(
    seed: dict[str, Any],
    odds: dict[str, float | None],
    blend: float = MARKET_STRENGTH_BLEND,
    max_xg_shift: float = MARKET_STRENGTH_MAX_XG_SHIFT,
) -> dict[str, Any]:
    """Bound extreme model/market strength conflicts without changing total xG."""

    market_zh = normalized_market_probabilities(odds)
    if any(market_zh.get(key) is None for key in ("胜", "平", "负")):
        return {"applied": False, "reason": "incomplete_market"}

    market = {
        "home": float(market_zh["胜"]),
        "draw": float(market_zh["平"]),
        "away": float(market_zh["负"]),
    }
    base_home, base_away = map(float, seed["base_xg"])
    model = outcome_probabilities(score_matrix(base_home, base_away))
    max_gap = max(abs(model[key] - market[key]) for key in model)
    if max_gap <= MARKET_PROBABILITY_GAP_THRESHOLD:
        return {"applied": False, "reason": "within_threshold", "maxGap": round(max_gap, 6)}

    market_home, market_away = _market_implied_xg_split(base_home + base_away, market)
    home_shift = max(-max_xg_shift, min(max_xg_shift, blend * (market_home - base_home)))
    away_shift = max(-max_xg_shift, min(max_xg_shift, blend * (market_away - base_away)))
    adjusted_home = max(0.15, base_home + home_shift)
    adjusted_away = max(0.15, base_away + away_shift)
    seed["base_xg"] = [adjusted_home, adjusted_away]
    seed["model_decomposition"] = {
        **seed.get("model_decomposition", {}),
        "preMarketExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
        "marketStrengthCalibration": {
            "applied": True,
            "method": "bounded_1x2_strength_shrinkage_v1",
            "blend": blend,
            "maxXgShift": max_xg_shift,
            "maxProbabilityGap": round(max_gap, 6),
            "homeShift": round(home_shift, 4),
            "awayShift": round(away_shift, 4),
        },
        "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
    }
    return seed["model_decomposition"]["marketStrengthCalibration"]
