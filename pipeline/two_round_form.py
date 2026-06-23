from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import ROOT
from .tournament_form import form_decay, tournament_matchday_index


DEFAULT_PROFILE_PATH = ROOT / "pipeline" / "data" / "two-round-performance.json"
MATCHDAY_WEIGHTS = {1: 0.45, 2: 0.55}
MAX_TACTICAL_DIRECTION_XG = 0.05
MAX_TEAM_DIRECTION_XG = 0.18
OBJECTIVE_MULTIPLIER = 1.5
FORBIDDEN_EVIDENCE_KEYS = {"xg_adjustment", "probability_delta", "home_probability", "away_probability"}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_EVIDENCE_KEYS.intersection(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


@dataclass(frozen=True)
class TeamTournamentAdjustment:
    team: str
    objective_attack: float
    objective_defense: float
    tactical_attack: float
    tactical_defense: float
    combined_attack: float
    combined_defense: float
    decay: float
    observed_matchdays: tuple[int, ...]
    target_matchday: int
    confidence: float
    tactical_status: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "objectiveAttackDelta": round(self.objective_attack, 4),
            "objectiveDefenseDelta": round(self.objective_defense, 4),
            "tacticalAttackDelta": round(self.tactical_attack, 4),
            "tacticalDefenseDelta": round(self.tactical_defense, 4),
            "attackDelta": round(self.combined_attack, 4),
            "defenseDelta": round(self.combined_defense, 4),
            "decay": round(self.decay, 4),
            "observedMatchdays": list(self.observed_matchdays),
            "targetMatchday": self.target_matchday,
            "confidence": round(self.confidence, 4),
            "tacticalAdmissionStatus": self.tactical_status,
            "summary": self.summary,
        }


def load_two_round_profiles(path: Path = DEFAULT_PROFILE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles: dict[str, dict[str, Any]] = {}
    for profile in payload.get("teams", []):
        if _contains_forbidden_key(profile.get("evidence", {})):
            raise ValueError("two-round evidence cannot provide direct probability or xG adjustments")
        team = str(profile.get("team") or "").strip()
        if not team:
            raise ValueError("two-round team profile is missing team")
        profiles[team] = profile
    return profiles


def _weighted(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def team_tournament_adjustment(
    team: str,
    profile: dict[str, Any] | None,
    target_date: str,
) -> TeamTournamentAdjustment:
    target_matchday = tournament_matchday_index(target_date)
    if not profile:
        return TeamTournamentAdjustment(
            team, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, (), target_matchday,
            0.0, "missing", "没有可用的两轮赛事档案",
        )
    available = [
        match for match in profile.get("matches", [])
        if match.get("observedDate") and date.fromisoformat(str(match["observedDate"])) < date.fromisoformat(target_date)
    ]
    if not available:
        return TeamTournamentAdjustment(
            team, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, (), target_matchday,
            0.0, "future_unavailable", "档案中的比赛在预测截止时间后，已阻断信息泄漏",
        )
    objective_attack_values: list[tuple[float, float]] = []
    objective_defense_values: list[tuple[float, float]] = []
    tactical_attack_values: list[tuple[float, float]] = []
    tactical_defense_values: list[tuple[float, float]] = []
    confidences: list[tuple[float, float]] = []
    tactical_statuses: set[str] = set()
    matchdays: list[int] = []
    for match in available:
        matchday = int(match.get("observedMatchday", 1))
        matchdays.append(matchday)
        weight = MATCHDAY_WEIGHTS.get(matchday, 0.0)
        objective = match.get("objectiveForm", {})
        objective_attack_values.append((float(objective.get("attackDelta", 0.0)), weight))
        objective_defense_values.append((float(objective.get("defenseDelta", 0.0)), weight))
        tactical = match.get("tacticalCandidate", {})
        status = str(tactical.get("admissionStatus", "observation_only"))
        tactical_statuses.add(status)
        if status == "enabled":
            tactical_attack_values.append((float(tactical.get("attackDelta", 0.0)), weight))
            tactical_defense_values.append((float(tactical.get("defenseDelta", 0.0)), weight))
        confidences.append((float(match.get("evidenceConfidence", 0.0)), weight))

    objective_attack = _weighted(objective_attack_values) * OBJECTIVE_MULTIPLIER
    objective_defense = _weighted(objective_defense_values) * OBJECTIVE_MULTIPLIER
    tactical_attack = max(
        -MAX_TACTICAL_DIRECTION_XG,
        min(MAX_TACTICAL_DIRECTION_XG, _weighted(tactical_attack_values)),
    )
    tactical_defense = max(
        -MAX_TACTICAL_DIRECTION_XG,
        min(MAX_TACTICAL_DIRECTION_XG, _weighted(tactical_defense_values)),
    )
    latest_matchday = max(matchdays)
    decay = form_decay(latest_matchday, target_matchday)
    combined_attack = max(
        -MAX_TEAM_DIRECTION_XG,
        min(MAX_TEAM_DIRECTION_XG, objective_attack + tactical_attack),
    ) * decay
    combined_defense = max(
        -MAX_TEAM_DIRECTION_XG,
        min(MAX_TEAM_DIRECTION_XG, objective_defense + tactical_defense),
    ) * decay
    tactical_status = "enabled" if "enabled" in tactical_statuses else "observation_only"
    return TeamTournamentAdjustment(
        team=team,
        objective_attack=objective_attack * decay,
        objective_defense=objective_defense * decay,
        tactical_attack=tactical_attack * decay,
        tactical_defense=tactical_defense * decay,
        combined_attack=combined_attack,
        combined_defense=combined_defense,
        decay=decay,
        observed_matchdays=tuple(sorted(set(matchdays))),
        target_matchday=target_matchday,
        confidence=max(0.0, min(1.0, _weighted(confidences))),
        tactical_status=tactical_status,
        summary=str(profile.get("summary") or "本届前两轮综合状态"),
    )


def apply_two_round_form(
    seeds: list[dict[str, Any]],
    target_date: str,
    profiles: dict[str, dict[str, Any]],
) -> None:
    for seed in seeds:
        home = team_tournament_adjustment(str(seed["home_team"]), profiles.get(str(seed["home_team"])), target_date)
        away = team_tournament_adjustment(str(seed["away_team"]), profiles.get(str(seed["away_team"])), target_date)
        base_home, base_away = map(float, seed["base_xg"])
        objective_home = home.objective_attack - away.objective_defense
        objective_away = away.objective_attack - home.objective_defense
        tactical_home = home.tactical_attack - away.tactical_defense
        tactical_away = away.tactical_attack - home.tactical_defense
        combined_home = home.combined_attack - away.combined_defense
        combined_away = away.combined_attack - home.combined_defense
        adjusted_home = max(0.15, base_home + combined_home)
        adjusted_away = max(0.15, base_away + combined_away)
        seed["base_xg"] = [adjusted_home, adjusted_away]
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "longTermExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "objectiveFormNet": {"home": round(objective_home, 4), "away": round(objective_away, 4)},
            "tacticalNet": {"home": round(tactical_home, 4), "away": round(tactical_away, 4)},
            "tournamentFormNet": {"home": round(combined_home, 4), "away": round(combined_away, 4)},
            "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
            "formLayer": "two_round_evidence_weighted_v1",
        }
        seed["tournament_form"] = {
            "sourceRound": "current_tournament_matchdays_1_2",
            "commentaryMode": "event_timeline",
            "home": home.to_dict(),
            "away": away.to_dict(),
            "applied": not math.isclose(combined_home, 0.0) or not math.isclose(combined_away, 0.0),
        }
