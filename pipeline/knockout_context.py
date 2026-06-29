from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .model import outcome_probabilities, score_matrix


KNOCKOUT_START_DATE = date(2026, 6, 28)
KNOCKOUT_STAGE_MARKERS = {
    "LAST_32",
    "ROUND_OF_32",
    "ROUND_OF_16",
    "LAST_16",
    "QUARTER_FINALS",
    "QUARTER_FINAL",
    "SEMI_FINALS",
    "SEMI_FINAL",
    "THIRD_PLACE",
    "FINAL",
}


@dataclass(frozen=True)
class KnockoutAdjustment:
    home_xg: float
    away_xg: float
    home_net: float
    away_net: float
    favorite_side: str | None
    policy: str
    home_late_attack_multiplier: float
    away_late_attack_multiplier: float
    home_late_defensive_risk_multiplier: float
    away_late_defensive_risk_multiplier: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "favoriteSide": self.favorite_side,
            "xgNet": {"home": round(self.home_net, 4), "away": round(self.away_net, 4)},
            "adjustedExpectedGoals": {
                "home": round(self.home_xg, 4),
                "away": round(self.away_xg, 4),
            },
            "homeLatePressure": {
                "attackMultiplier": round(self.home_late_attack_multiplier, 4),
                "defensiveRiskMultiplier": round(self.home_late_defensive_risk_multiplier, 4),
            },
            "awayLatePressure": {
                "attackMultiplier": round(self.away_late_attack_multiplier, 4),
                "defensiveRiskMultiplier": round(self.away_late_defensive_risk_multiplier, 4),
            },
            "applied": abs(self.home_net) > 1e-12 or abs(self.away_net) > 1e-12,
        }


def is_knockout_stage(stage: str | None, group: str | None = None, target_date: str | None = None) -> bool:
    if group:
        return False
    normalized = str(stage or "").upper().replace("-", "_").replace(" ", "_")
    if normalized in KNOCKOUT_STAGE_MARKERS:
        return True
    if normalized.startswith(("ROUND_", "LAST_", "QUARTER", "SEMI")):
        return True
    if normalized == "GROUP_STAGE":
        return False
    if target_date:
        return date.fromisoformat(target_date) >= KNOCKOUT_START_DATE
    return False


def knockout_adjust_xg(home_xg: float, away_xg: float) -> KnockoutAdjustment:
    probabilities = outcome_probabilities(score_matrix(home_xg, away_xg))
    favorite_side = "home" if probabilities["home"] >= probabilities["away"] else "away"
    favorite_probability = max(probabilities["home"], probabilities["away"])
    total = home_xg + away_xg

    if favorite_probability < 0.52:
        home_net = -0.010
        away_net = -0.010
        policy = "knockout_tension_close_game_v2"
        home_attack = away_attack = 0.995
        home_risk = away_risk = 1.01
    else:
        favorite_net = 0.0
        underdog_net = 0.0
        if favorite_side == "home":
            home_net, away_net = favorite_net, underdog_net
            home_attack, away_attack = 0.985, 1.060
            home_risk, away_risk = 0.995, 1.055
        else:
            home_net, away_net = underdog_net, favorite_net
            home_attack, away_attack = 1.060, 0.985
            home_risk, away_risk = 1.055, 0.995
        policy = "knockout_underdog_chase_favorite_tempo_v1"

    adjusted_home = max(0.15, home_xg + home_net)
    adjusted_away = max(0.15, away_xg + away_net)
    return KnockoutAdjustment(
        home_xg=adjusted_home,
        away_xg=adjusted_away,
        home_net=adjusted_home - home_xg,
        away_net=adjusted_away - away_xg,
        favorite_side=favorite_side,
        policy=policy,
        home_late_attack_multiplier=home_attack,
        away_late_attack_multiplier=away_attack,
        home_late_defensive_risk_multiplier=home_risk,
        away_late_defensive_risk_multiplier=away_risk,
    )


def apply_knockout_context(
    seeds: list[dict[str, Any]],
    target_date: str,
    matches: list[dict[str, Any]] | None = None,
) -> None:
    del matches
    for seed in seeds:
        if not is_knockout_stage(seed.get("stage"), seed.get("group"), target_date):
            continue
        base_home, base_away = map(float, seed["base_xg"])
        adjustment = knockout_adjust_xg(base_home, base_away)
        seed["base_xg"] = [adjustment.home_xg, adjustment.away_xg]
        seed["coverage"] = max(0.0, float(seed.get("coverage", 0.70)) - 0.01)
        seed["stage"] = seed.get("stage") or "ROUND_OF_32"
        seed["knockout_context"] = adjustment.to_dict()
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "preKnockoutExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "knockoutNet": {"home": round(adjustment.home_net, 4), "away": round(adjustment.away_net, 4)},
            "adjustedExpectedGoals": {
                "home": round(adjustment.home_xg, 4),
                "away": round(adjustment.away_xg, 4),
            },
            "knockoutLayer": adjustment.policy,
        }
