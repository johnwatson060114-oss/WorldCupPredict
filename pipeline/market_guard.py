from __future__ import annotations

from typing import Any


MARKET_PROBABILITY_GAP_THRESHOLD = 0.15
MARKET_FAVORITE_THRESHOLD = 0.55


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
