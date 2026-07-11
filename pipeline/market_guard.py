from __future__ import annotations

from typing import Any

from .final_sprint_policy import load_final_sprint_policy
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


def _normalize_available_odds(odds: dict[str, float | None]) -> dict[str, float] | None:
    if not odds or any(value is None or float(value) <= 1 for value in odds.values()):
        return None
    implied = {str(key): 1 / float(value) for key, value in odds.items()}
    margin = sum(implied.values())
    if margin <= 0:
        return None
    return {key: value / margin for key, value in implied.items()}


def _wdl_market(odds: dict[str, float | None]) -> dict[str, float] | None:
    aliases = {
        "home": ("home", "\u80dc"),
        "draw": ("draw", "\u5e73"),
        "away": ("away", "\u8d1f"),
    }
    selected: dict[str, float | None] = {}
    for outcome, keys in aliases.items():
        selected[outcome] = next((odds.get(key) for key in keys if odds.get(key) is not None), None)
    return _normalize_available_odds(selected)


def _total_goals_market(odds: dict[str, float | None]) -> dict[str, float] | None:
    selected = {bucket: odds.get(bucket) for bucket in ("0", "1", "2", "3", "4", "5", "6", "7+")}
    return _normalize_available_odds(selected)


def apply_bounded_market_anchor(
    seed: dict[str, Any],
    win_draw_loss_odds: dict[str, float | None],
    total_goals_odds: dict[str, float | None],
    observed_at: str | None = None,
    settings: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Use de-vigged pre-kickoff markets as bounded strength and total-xG anchors."""

    policy = settings or load_final_sprint_policy()["marketAnchor"]
    strength_blend = float(policy["strengthBlend"])
    total_blend = float(policy["totalGoalsBlend"])
    max_side_shift = float(policy["maxSideXgShift"])
    max_total_shift = float(policy["maxTotalXgShift"])
    wdl = _wdl_market(win_draw_loss_odds)
    totals = _total_goals_market(total_goals_odds)
    base_home, base_away = map(float, seed["base_xg"])
    base_total = base_home + base_away

    if wdl is None and totals is None:
        metadata = {
            "applied": False,
            "policy": "bounded_dual_axis_market_anchor_v1",
            "reason": "incomplete_pre_kickoff_markets",
            "observedAt": observed_at,
        }
        seed["market_calibration"] = metadata
        return metadata

    market_total = None
    target_total = base_total
    total_shift = 0.0
    if totals is not None:
        market_total = sum((7 if bucket == "7+" else int(bucket)) * probability for bucket, probability in totals.items())
        total_shift = max(-max_total_shift, min(max_total_shift, total_blend * (market_total - base_total)))
        target_total = max(0.30, base_total + total_shift)

    strength_home, strength_away = base_home, base_away
    if wdl is not None:
        market_home, market_away = _market_implied_xg_split(base_total, wdl)
        strength_home = base_home + strength_blend * (market_home - base_home)
        strength_away = base_away + strength_blend * (market_away - base_away)

    strength_total = max(0.30, strength_home + strength_away)
    candidate_home = strength_home / strength_total * target_total
    candidate_away = strength_away / strength_total * target_total
    home_shift = max(-max_side_shift, min(max_side_shift, candidate_home - base_home))
    away_shift = max(-max_side_shift, min(max_side_shift, candidate_away - base_away))
    adjusted_home = max(0.15, base_home + home_shift)
    adjusted_away = max(0.15, base_away + away_shift)
    side_cap_hit = abs(candidate_home - base_home) > max_side_shift or abs(candidate_away - base_away) > max_side_shift
    total_cap_hit = bool(totals is not None and abs(total_blend * (market_total - base_total)) > max_total_shift)
    anchor_enabled = strength_blend > 0 or total_blend > 0
    metadata = {
        "applied": anchor_enabled,
        "policy": "bounded_dual_axis_market_anchor_v1",
        "reason": None if anchor_enabled else "validation_gate_fallback_to_diagnostic_only",
        "observedAt": observed_at,
        "strengthBlend": strength_blend if wdl is not None else 0.0,
        "totalGoalsBlend": total_blend if totals is not None else 0.0,
        "deViggedOutcomeProbabilities": wdl,
        "deViggedTotalGoalsProbabilities": totals,
        "marketExpectedTotalGoals": round(market_total, 4) if market_total is not None else None,
        "preCalibrationExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
        "postCalibrationExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
        "xgShift": {"home": round(adjusted_home - base_home, 4), "away": round(adjusted_away - base_away, 4)},
        "totalXgShift": round(adjusted_home + adjusted_away - base_total, 4),
        "bounds": {"maxSideXgShift": max_side_shift, "maxTotalXgShift": max_total_shift},
        "sideCapHit": side_cap_hit,
        "totalCapHit": total_cap_hit,
    }
    seed["base_xg"] = [adjusted_home, adjusted_away] if anchor_enabled else [base_home, base_away]
    seed["market_calibration"] = metadata
    seed["model_decomposition"] = {
        **seed.get("model_decomposition", {}),
        "marketCalibration": metadata,
        "adjustedExpectedGoals": (
            metadata["postCalibrationExpectedGoals"]
            if anchor_enabled
            else metadata["preCalibrationExpectedGoals"]
        ),
    }
    return metadata
