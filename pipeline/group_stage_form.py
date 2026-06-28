from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import ROOT
from .tournament_form import form_decay, tournament_matchday_index


DEFAULT_PROFILE_PATH = ROOT / "pipeline" / "data" / "group-stage-performance.json"
MATCHDAY_WEIGHTS = {1: 0.25, 2: 0.35, 3: 0.40}
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


def _weighted(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def _clamp(value: float, cap: float) -> float:
    return max(-cap, min(cap, value))


@dataclass(frozen=True)
class GroupStageAdjustment:
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
    coverage: float
    tactical_status: str
    objective_status: str
    credibility_labels: tuple[str, ...]
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
            "coverage": round(self.coverage, 4),
            "objectiveAdmissionStatus": self.objective_status,
            "tacticalAdmissionStatus": self.tactical_status,
            "credibilityLabels": list(self.credibility_labels),
            "summary": self.summary,
        }


def load_group_stage_profiles(path: Path = DEFAULT_PROFILE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles: dict[str, dict[str, Any]] = {}
    for profile in payload.get("teams", []):
        if _contains_forbidden_key(profile.get("evidence", {})):
            raise ValueError("group-stage evidence cannot provide direct probability or xG adjustments")
        team = str(profile.get("team") or "").strip()
        if not team:
            raise ValueError("group-stage team profile is missing team")
        profiles[team] = profile
    return profiles


def team_group_stage_adjustment(
    team: str,
    profile: dict[str, Any] | None,
    target_date: str,
) -> GroupStageAdjustment:
    target_matchday = tournament_matchday_index(target_date)
    if not profile:
        return GroupStageAdjustment(
            team=team,
            objective_attack=0.0,
            objective_defense=0.0,
            tactical_attack=0.0,
            tactical_defense=0.0,
            combined_attack=0.0,
            combined_defense=0.0,
            decay=1.0,
            observed_matchdays=(),
            target_matchday=target_matchday,
            confidence=0.0,
            coverage=0.0,
            tactical_status="missing",
            objective_status="missing",
            credibility_labels=("missing_profile",),
            summary="No group-stage profile is available.",
        )

    cutoff = date.fromisoformat(target_date)
    available = [
        match for match in profile.get("matches", [])
        if match.get("observedDate") and date.fromisoformat(str(match["observedDate"])) < cutoff
    ]
    if not available:
        return GroupStageAdjustment(
            team=team,
            objective_attack=0.0,
            objective_defense=0.0,
            tactical_attack=0.0,
            tactical_defense=0.0,
            combined_attack=0.0,
            combined_defense=0.0,
            decay=1.0,
            observed_matchdays=(),
            target_matchday=target_matchday,
            confidence=0.0,
            coverage=0.0,
            tactical_status="future_unavailable",
            objective_status="future_unavailable",
            credibility_labels=("post_match_information_blocked",),
            summary="Group-stage evidence is not visible at the forecast cutoff.",
        )

    objective_attack_values: list[tuple[float, float]] = []
    objective_defense_values: list[tuple[float, float]] = []
    tactical_attack_values: list[tuple[float, float]] = []
    tactical_defense_values: list[tuple[float, float]] = []
    confidences: list[tuple[float, float]] = []
    coverages: list[tuple[float, float]] = []
    matchdays: list[int] = []
    labels: set[str] = set()
    objective_statuses: set[str] = set()
    tactical_statuses: set[str] = set()

    for match in available:
        matchday = int(match.get("observedMatchday", 1))
        matchdays.append(matchday)
        credibility = max(0.0, min(1.0, float(match.get("credibilityWeight", 0.0))))
        base_weight = MATCHDAY_WEIGHTS.get(matchday, 0.0)
        weight = base_weight * credibility
        labels.update(str(label) for label in match.get("credibilityLabels", []))

        objective = match.get("objectiveForm", {})
        objective_status = str(objective.get("admissionStatus", "observation_only"))
        objective_statuses.add(objective_status)
        if objective_status == "enabled" and weight > 0:
            objective_attack_values.append((float(objective.get("attackDelta", 0.0)), weight))
            objective_defense_values.append((float(objective.get("defenseDelta", 0.0)), weight))

        tactical = match.get("tacticalCandidate", {})
        tactical_status = str(tactical.get("admissionStatus", "observation_only"))
        tactical_statuses.add(tactical_status)
        if tactical_status == "enabled" and weight > 0:
            tactical_attack_values.append((float(tactical.get("attackDelta", 0.0)), weight))
            tactical_defense_values.append((float(tactical.get("defenseDelta", 0.0)), weight))

        confidences.append((float(match.get("evidenceConfidence", 0.0)), base_weight))
        coverages.append((credibility, base_weight))

    latest_matchday = max(matchdays)
    decay = form_decay(latest_matchday, target_matchday)
    objective_attack = _weighted(objective_attack_values) * OBJECTIVE_MULTIPLIER
    objective_defense = _weighted(objective_defense_values) * OBJECTIVE_MULTIPLIER
    tactical_attack = _clamp(_weighted(tactical_attack_values), MAX_TACTICAL_DIRECTION_XG)
    tactical_defense = _clamp(_weighted(tactical_defense_values), MAX_TACTICAL_DIRECTION_XG)
    combined_attack = _clamp(objective_attack + tactical_attack, MAX_TEAM_DIRECTION_XG) * decay
    combined_defense = _clamp(objective_defense + tactical_defense, MAX_TEAM_DIRECTION_XG) * decay

    return GroupStageAdjustment(
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
        coverage=max(0.0, min(1.0, _weighted(coverages))),
        tactical_status="enabled" if "enabled" in tactical_statuses else "observation_only",
        objective_status="enabled" if "enabled" in objective_statuses else "observation_only",
        credibility_labels=tuple(sorted(labels)),
        summary=str(profile.get("summary") or "Group-stage commentary-gated form profile."),
    )


def apply_group_stage_form(
    seeds: list[dict[str, Any]],
    target_date: str,
    profiles: dict[str, dict[str, Any]],
) -> None:
    for seed in seeds:
        home_team = str(seed["home_team"])
        away_team = str(seed["away_team"])
        home = team_group_stage_adjustment(home_team, profiles.get(home_team), target_date)
        away = team_group_stage_adjustment(away_team, profiles.get(away_team), target_date)
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
        seed["coverage"] = max(
            0.0,
            float(seed.get("coverage", 0.70)) - 0.02 * (1.0 - min(home.coverage, away.coverage)),
        )
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "longTermExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "objectiveFormNet": {"home": round(objective_home, 4), "away": round(objective_away, 4)},
            "tacticalNet": {"home": round(tactical_home, 4), "away": round(tactical_away, 4)},
            "groupStageFormNet": {"home": round(combined_home, 4), "away": round(combined_away, 4)},
            "tournamentFormNet": {"home": round(combined_home, 4), "away": round(combined_away, 4)},
            "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
            "formLayer": "group_stage_commentary_gated_v1",
        }
        applied = not math.isclose(combined_home, 0.0) or not math.isclose(combined_away, 0.0)
        form_payload = {
            "sourceRound": "current_tournament_group_stage",
            "commentaryMode": "minute_by_minute_events",
            "home": home.to_dict(),
            "away": away.to_dict(),
            "applied": applied,
        }
        seed["group_stage_form"] = form_payload
        seed["tournament_form"] = form_payload
