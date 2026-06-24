from __future__ import annotations

from dataclasses import dataclass
from typing import Any


OUTCOMES = ("home", "draw", "away")
SAFE_MOTIVATIONS = {"secured_first", "secured_top_two", "draw_advances"}
FORCE_MOTIVATIONS = {"must_win", "goal_difference_chase"}
MAX_DRAW_SHIFT = 0.045


@dataclass(frozen=True)
class DrawRiskResult:
    probabilities: dict[str, float]
    metadata: dict[str, Any]


def _normalized(probabilities: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(probabilities.get(outcome, 0.0))) for outcome in OUTCOMES)
    if total <= 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {
        outcome: max(0.0, float(probabilities.get(outcome, 0.0))) / total
        for outcome in OUTCOMES
    }


def _role_probabilities(probabilities: dict[str, float]) -> tuple[str, str, float, float, float]:
    favorite = "home" if probabilities["home"] >= probabilities["away"] else "away"
    underdog = "away" if favorite == "home" else "home"
    return favorite, underdog, probabilities[favorite], probabilities["draw"], probabilities[underdog]


def _motivation_labels(seed: dict[str, Any] | None) -> tuple[list[str], float]:
    if not seed:
        return [], 1.0
    current = seed.get("current_tournament") or {}
    states = [
        str(current.get("homeMotivation") or ""),
        str(current.get("awayMotivation") or ""),
    ]
    labels: list[str] = []
    multiplier = 1.0
    if any(state in SAFE_MOTIVATIONS for state in states):
        labels.append("third_round_conservation_or_draw_utility")
    if all(state not in FORCE_MOTIVATIONS for state in states) and any(
        state == "draw_advances" for state in states
    ):
        labels.append("draw_advances_without_must_win_opponent")
    if any(
        bool((current.get(side) or {}).get("rotationCandidate"))
        for side in ("homeScenarios", "awayScenarios")
    ):
        labels.append("rotation_candidate")
    if any(state in FORCE_MOTIVATIONS for state in states):
        labels.append("must_win_or_goal_difference_chase_present")
        multiplier = 0.65
    return labels, multiplier


def _total_expected_goals(seed: dict[str, Any] | None) -> float | None:
    if not seed:
        return None
    try:
        home, away = seed.get("base_xg", [None, None])
        if home is None or away is None:
            return None
        return float(home) + float(away)
    except (TypeError, ValueError):
        return None


def apply_draw_risk_layer(
    probabilities: dict[str, float],
    seed: dict[str, Any] | None = None,
) -> DrawRiskResult:
    """Apply a conservative draw-risk redistribution.

    The layer does not change xG or the score matrix. It only moves a small
    amount of probability from win/loss outcomes into the draw outcome when the
    original probabilities show one of the known draw blind spots:

    * 20%-25% ordinary watch band that the model historically under-emphasized.
    * moderate-favorite matches where underdog upset probability looks too high
      relative to draw probability.
    * low-draw-probability strong-favorite stall risk, capped and only for
      lower-total-goals shapes or third-round conservation contexts.
    * matchday-three conservation/draw-utility context from the group model.
    """

    base = _normalized(probabilities)
    favorite, underdog, favorite_probability, draw_probability, underdog_probability = _role_probabilities(base)
    total_xg = _total_expected_goals(seed)
    motivation_labels, motivation_multiplier = _motivation_labels(seed)
    contributions: list[dict[str, Any]] = []

    def add_contribution(label: str, amount: float, favorite_share: float) -> None:
        contributions.append({
            "label": label,
            "amount": amount,
            "fromFavorite": amount * favorite_share,
            "fromUnderdog": amount * (1 - favorite_share),
        })

    if 0.20 <= draw_probability <= 0.25 and 0.50 <= favorite_probability <= 0.72:
        add_contribution("draw_watch_band_20_25", 0.018, 0.65)

    if (
        0.18 <= draw_probability <= 0.23
        and 0.50 <= favorite_probability <= 0.62
        and underdog_probability >= 0.20
    ):
        contributions.append({
            "label": "misallocated_underdog_upset_to_draw",
            "amount": 0.018,
            "fromFavorite": 0.0,
            "fromUnderdog": 0.018,
        })

    lower_total_or_context = total_xg is None or total_xg <= 3.05 or bool(motivation_labels)
    if (
        draw_probability < 0.16
        and favorite_probability >= 0.78
        and underdog_probability <= 0.08
        and lower_total_or_context
    ):
        contributions.append({
            "label": "low_probability_strong_favorite_stall_guard",
            "amount": 0.025,
            "fromFavorite": 0.025,
            "fromUnderdog": 0.0,
        })

    if motivation_labels and 0.16 <= draw_probability <= 0.27:
        add_contribution("third_round_motivation_draw_utility", 0.014, 0.70)

    if not contributions:
        return DrawRiskResult(
            probabilities=base,
            metadata={
                "status": "not_triggered",
                "applied": False,
                "layer": "draw_risk_probability_redistribution_v1",
                "labels": [],
                "drawShift": 0.0,
                "preAdjustment": {key: round(value, 5) for key, value in base.items()},
                "postAdjustment": {key: round(value, 5) for key, value in base.items()},
            },
        )

    favorite_take = sum(float(item["fromFavorite"]) for item in contributions) * motivation_multiplier
    underdog_take = sum(float(item["fromUnderdog"]) for item in contributions) * motivation_multiplier
    total_shift = favorite_take + underdog_take
    if total_shift > MAX_DRAW_SHIFT:
        scale = MAX_DRAW_SHIFT / total_shift
        favorite_take *= scale
        underdog_take *= scale
        total_shift = MAX_DRAW_SHIFT

    favorite_take = min(favorite_take, max(0.0, base[favorite] - 0.01))
    underdog_take = min(underdog_take, max(0.0, base[underdog] - 0.01))
    total_shift = favorite_take + underdog_take
    if total_shift <= 0:
        return DrawRiskResult(
            probabilities=base,
            metadata={
                "status": "not_triggered",
                "applied": False,
                "layer": "draw_risk_probability_redistribution_v1",
                "labels": [],
                "drawShift": 0.0,
                "preAdjustment": {key: round(value, 5) for key, value in base.items()},
                "postAdjustment": {key: round(value, 5) for key, value in base.items()},
            },
        )

    adjusted = dict(base)
    adjusted["draw"] += total_shift
    adjusted[favorite] -= favorite_take
    adjusted[underdog] -= underdog_take
    adjusted = _normalized(adjusted)
    labels = [str(item["label"]) for item in contributions] + motivation_labels
    return DrawRiskResult(
        probabilities=adjusted,
        metadata={
            "status": "enabled",
            "applied": True,
            "layer": "draw_risk_probability_redistribution_v1",
            "labels": sorted(set(labels)),
            "drawShift": round(adjusted["draw"] - base["draw"], 5),
            "favoriteOutcome": favorite,
            "underdogOutcome": underdog,
            "motivationMultiplier": motivation_multiplier,
            "totalExpectedGoals": round(total_xg, 4) if total_xg is not None else None,
            "preAdjustment": {key: round(value, 5) for key, value in base.items()},
            "postAdjustment": {key: round(value, 5) for key, value in adjusted.items()},
        },
    )
