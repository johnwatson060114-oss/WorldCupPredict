from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import ROOT


DEFAULT_PROFILE_PATH = ROOT / "pipeline" / "data" / "first-round-performance.json"
MAX_TEAM_DIRECTION_XG = 0.18
CURRENT_TOURNAMENT_FORM_MULTIPLIER = 1.5
DECAY_START_MATCHDAYS = 2
DECAY_HALF_LIFE_MATCHDAYS = 2.0
TOURNAMENT_BOUNDARIES_BY_YEAR = {
    2018: (
        date(2018, 6, 19),
        date(2018, 6, 24),
        date(2018, 6, 28),
        date(2018, 7, 3),
        date(2018, 7, 7),
        date(2018, 7, 11),
        date(2018, 7, 15),
    ),
    2022: (
        date(2022, 11, 24),
        date(2022, 11, 28),
        date(2022, 12, 2),
        date(2022, 12, 6),
        date(2022, 12, 10),
        date(2022, 12, 14),
        date(2022, 12, 18),
    ),
    2026: (
        date(2026, 6, 17),
        date(2026, 6, 23),
        date(2026, 6, 27),
        date(2026, 7, 3),
        date(2026, 7, 7),
        date(2026, 7, 11),
        date(2026, 7, 15),
        date(2026, 7, 19),
    ),
}

FORBIDDEN_COMMENTARY_KEYS = {
    "xg_adjustment",
    "probability_delta",
    "attack_delta",
    "defense_delta",
}


@dataclass(frozen=True)
class TeamFormAdjustment:
    team: str
    attack_delta: float
    defense_delta: float
    decay: float
    observed_matchday: int
    target_matchday: int
    confidence: float
    admission_status: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "attackDelta": round(self.attack_delta, 4),
            "defenseDelta": round(self.defense_delta, 4),
            "decay": round(self.decay, 4),
            "observedMatchday": self.observed_matchday,
            "targetMatchday": self.target_matchday,
            "confidence": round(self.confidence, 4),
            "admissionStatus": self.admission_status,
            "summary": self.summary,
        }


def _contains_forbidden_commentary_key(value: Any) -> bool:
    if isinstance(value, dict):
        if FORBIDDEN_COMMENTARY_KEYS.intersection(value):
            return True
        return any(_contains_forbidden_commentary_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_commentary_key(item) for item in value)
    return False


def tournament_matchday_index(target_date: str) -> int:
    """Map World Cup calendar dates to a coarse team matchday index.

    Knockout rounds continue the index so a group-stage signal starts fading
    only after two subsequent team matchdays.
    """

    current = date.fromisoformat(target_date)
    boundaries = TOURNAMENT_BOUNDARIES_BY_YEAR.get(current.year, TOURNAMENT_BOUNDARIES_BY_YEAR[2026])
    for index, boundary in enumerate(boundaries, start=1):
        if current <= boundary:
            return index
    return len(boundaries) + 1


def form_decay(observed_matchday: int, target_matchday: int) -> float:
    elapsed = max(0, target_matchday - observed_matchday)
    if elapsed <= DECAY_START_MATCHDAYS:
        return 1.0
    return 0.5 ** ((elapsed - DECAY_START_MATCHDAYS) / DECAY_HALF_LIFE_MATCHDAYS)


def load_first_round_profiles(path: Path = DEFAULT_PROFILE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles: dict[str, dict[str, Any]] = {}
    for profile in payload.get("teams", []):
        commentary = profile.get("commentaryEvidence", {})
        if _contains_forbidden_commentary_key(commentary):
            raise ValueError("commentary evidence cannot provide xG or probability adjustments")
        team = str(profile.get("team") or "").strip()
        if not team:
            raise ValueError("first-round team profile is missing team")
        profiles[team] = profile
    return profiles


def team_form_adjustment(
    team: str,
    profile: dict[str, Any] | None,
    target_date: str,
) -> TeamFormAdjustment:
    if not profile:
        return TeamFormAdjustment(team, 0.0, 0.0, 1.0, 1, tournament_matchday_index(target_date), 0.0, "missing", "没有首轮表现档案")

    objective = profile.get("objectiveForm", {})
    observed_matchday = int(profile.get("observedMatchday", 1))
    target_matchday = tournament_matchday_index(target_date)
    observed_date = profile.get("observedDate")
    if observed_date and date.fromisoformat(target_date) <= date.fromisoformat(str(observed_date)):
        return TeamFormAdjustment(
            team, 0.0, 0.0, 1.0, observed_matchday, target_matchday, 0.0,
            "future_unavailable", "该首轮表现当时尚未发生，已阻断赛后信息泄漏",
        )
    decay = form_decay(observed_matchday, target_matchday)
    status = str(objective.get("admissionStatus", "observation_only"))
    enabled = status == "enabled"
    raw_attack = (
        float(objective.get("attackDelta", 0.0)) * CURRENT_TOURNAMENT_FORM_MULTIPLIER
        if enabled else 0.0
    )
    raw_defense = (
        float(objective.get("defenseDelta", 0.0)) * CURRENT_TOURNAMENT_FORM_MULTIPLIER
        if enabled else 0.0
    )
    attack = max(-MAX_TEAM_DIRECTION_XG, min(MAX_TEAM_DIRECTION_XG, raw_attack)) * decay
    defense = max(-MAX_TEAM_DIRECTION_XG, min(MAX_TEAM_DIRECTION_XG, raw_defense)) * decay
    confidence = max(0.0, min(1.0, float(profile.get("evidenceConfidence", 0.0))))
    return TeamFormAdjustment(
        team=team,
        attack_delta=attack,
        defense_delta=defense,
        decay=decay,
        observed_matchday=observed_matchday,
        target_matchday=target_matchday,
        confidence=confidence,
        admission_status=status,
        summary=str(profile.get("summary") or "首轮状态信号"),
    )


def apply_tournament_form(
    seeds: list[dict[str, Any]],
    target_date: str,
    profiles: dict[str, dict[str, Any]],
) -> None:
    for seed in seeds:
        home_team = str(seed["home_team"])
        away_team = str(seed["away_team"])
        home = team_form_adjustment(home_team, profiles.get(home_team), target_date)
        away = team_form_adjustment(away_team, profiles.get(away_team), target_date)
        base_home, base_away = map(float, seed["base_xg"])

        # Positive defense_delta means stronger defense and therefore lowers
        # the opponent's scoring mean. Each team's own directional signal is
        # capped before the two sides are combined.
        home_net = home.attack_delta - away.defense_delta
        away_net = away.attack_delta - home.defense_delta
        adjusted_home = max(0.15, base_home + home_net)
        adjusted_away = max(0.15, base_away + away_net)
        seed["base_xg"] = [adjusted_home, adjusted_away]
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "longTermExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "tournamentFormNet": {"home": round(home_net, 4), "away": round(away_net, 4)},
            "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
            "formLayer": "current_tournament_weighted_v2",
        }
        seed["tournament_form"] = {
            "sourceRound": "current_tournament_from_group_matchday_1",
            "commentaryMode": "text_only",
            "home": home.to_dict(),
            "away": away.to_dict(),
            "applied": not math.isclose(home_net, 0.0) or not math.isclose(away_net, 0.0),
        }
