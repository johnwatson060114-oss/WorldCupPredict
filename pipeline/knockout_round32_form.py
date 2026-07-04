from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import ROOT
from .knockout_context import is_knockout_stage


DEFAULT_PROFILE_PATH = ROOT / "pipeline" / "data" / "knockout-round32-performance.json"
FORBIDDEN_EVIDENCE_KEYS = {"xg_adjustment", "probability_delta", "home_probability", "away_probability"}
MAX_ATTACK_DELTA = (-0.08, 0.025)
MAX_DEFENSE_DELTA = (-0.05, 0.025)
MAX_COVERAGE_PENALTY = 0.06


LABEL_EFFECTS: dict[str, dict[str, float]] = {
    "extra_time_load": {
        "attack": -0.025,
        "defense": -0.012,
        "coverage": 0.015,
        "late_attack": 0.965,
        "late_risk": 1.025,
    },
    "penalty_shootout_load": {
        "attack": -0.012,
        "defense": -0.006,
        "coverage": 0.010,
        "late_attack": 0.985,
        "late_risk": 1.010,
    },
    "visible_cramp_or_fatigue": {
        "attack": -0.030,
        "defense": -0.018,
        "coverage": 0.020,
        "late_attack": 0.940,
        "late_risk": 1.035,
    },
    "late_survival_pressure": {
        "attack": -0.008,
        "defense": -0.012,
        "coverage": 0.008,
        "late_attack": 0.980,
        "late_risk": 1.020,
    },
    "underwhelming_favorite": {
        "attack": -0.025,
        "defense": 0.000,
        "coverage": 0.012,
        "late_attack": 0.985,
        "late_risk": 1.000,
    },
    "card_suspension_risk": {
        "attack": 0.000,
        "defense": 0.000,
        "coverage": 0.015,
        "late_attack": 1.000,
        "late_risk": 1.010,
    },
    "injury_doubtful": {
        "attack": -0.015,
        "defense": -0.006,
        "coverage": 0.020,
        "late_attack": 0.980,
        "late_risk": 1.010,
    },
}


@dataclass(frozen=True)
class Round32TeamAdjustment:
    team: str
    attack_delta: float = 0.0
    defense_delta: float = 0.0
    coverage_penalty: float = 0.0
    late_attack_multiplier: float = 1.0
    late_defensive_risk_multiplier: float = 1.0
    labels: tuple[str, ...] = ()
    confidence: float = 0.0
    source_urls: tuple[str, ...] = ()
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "attackDelta": round(self.attack_delta, 4),
            "defenseDelta": round(self.defense_delta, 4),
            "coveragePenalty": round(self.coverage_penalty, 4),
            "lateAttackMultiplier": round(self.late_attack_multiplier, 4),
            "lateDefensiveRiskMultiplier": round(self.late_defensive_risk_multiplier, 4),
            "labels": list(self.labels),
            "confidence": round(self.confidence, 4),
            "sourceUrls": list(self.source_urls),
            "summary": self.summary,
        }


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_EVIDENCE_KEYS.intersection(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    low, high = bounds
    return max(low, min(high, value))


def load_knockout_round32_profiles(path: Path = DEFAULT_PROFILE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles: dict[str, dict[str, Any]] = {}
    for profile in payload.get("teams", []):
        if _contains_forbidden_key(profile):
            raise ValueError("round32 evidence cannot provide direct probability or xG adjustments")
        team = str(profile.get("team") or "").strip()
        if not team:
            raise ValueError("round32 team profile is missing team")
        profiles[team] = profile
    return profiles


def team_round32_adjustment(
    team: str,
    profile: dict[str, Any] | None,
    target_date: str,
) -> Round32TeamAdjustment:
    if not profile:
        return Round32TeamAdjustment(team=team, summary="no round32 evidence")

    available = [
        match for match in profile.get("matches", [])
        if match.get("observedDate") and date.fromisoformat(str(match["observedDate"])) < date.fromisoformat(target_date)
    ]
    if not available:
        return Round32TeamAdjustment(team=team, summary="round32 evidence is after the prediction cutoff")

    attack = 0.0
    defense = 0.0
    coverage = 0.0
    late_attack = 1.0
    late_risk = 1.0
    labels: list[str] = []
    confidence_weight = 0.0
    evidence_count = 0
    source_urls: list[str] = []
    for match in available:
        confidence = max(0.0, min(1.0, float(match.get("evidenceConfidence") or 0.5)))
        confidence_weight += confidence
        evidence_count += 1
        for url in match.get("sourceUrls", []):
            if url and url not in source_urls:
                source_urls.append(str(url))
        for label in match.get("labels", []):
            label = str(label)
            effect = LABEL_EFFECTS.get(label)
            if not effect:
                continue
            labels.append(label)
            attack += effect["attack"] * confidence
            defense += effect["defense"] * confidence
            coverage += effect["coverage"] * confidence
            late_attack *= 1.0 - ((1.0 - effect["late_attack"]) * confidence)
            late_risk *= 1.0 + ((effect["late_risk"] - 1.0) * confidence)

    if not labels:
        return Round32TeamAdjustment(
            team=team,
            confidence=round(confidence_weight / max(1, evidence_count), 4),
            source_urls=tuple(source_urls),
            summary=str(profile.get("summary") or "round32 evidence observed without active labels"),
        )

    return Round32TeamAdjustment(
        team=team,
        attack_delta=_clamp(attack, MAX_ATTACK_DELTA),
        defense_delta=_clamp(defense, MAX_DEFENSE_DELTA),
        coverage_penalty=min(MAX_COVERAGE_PENALTY, coverage),
        late_attack_multiplier=max(0.90, min(1.02, late_attack)),
        late_defensive_risk_multiplier=max(0.98, min(1.08, late_risk)),
        labels=tuple(sorted(set(labels))),
        confidence=round(confidence_weight / max(1, evidence_count), 4),
        source_urls=tuple(source_urls),
        summary=str(profile.get("summary") or "round32 process evidence applied conservatively"),
    )


def apply_knockout_round32_form(
    seeds: list[dict[str, Any]],
    target_date: str,
    profiles: dict[str, dict[str, Any]],
) -> None:
    for seed in seeds:
        if not is_knockout_stage(seed.get("stage"), seed.get("group"), target_date):
            continue

        home = team_round32_adjustment(str(seed["home_team"]), profiles.get(str(seed["home_team"])), target_date)
        away = team_round32_adjustment(str(seed["away_team"]), profiles.get(str(seed["away_team"])), target_date)
        if not home.labels and not away.labels:
            continue

        base_home, base_away = map(float, seed["base_xg"])
        home_net = home.attack_delta - away.defense_delta
        away_net = away.attack_delta - home.defense_delta
        adjusted_home = max(0.15, base_home + home_net)
        adjusted_away = max(0.15, base_away + away_net)
        seed["base_xg"] = [adjusted_home, adjusted_away]
        seed["coverage"] = round(
            max(0.0, float(seed.get("coverage", 0.70)) - home.coverage_penalty - away.coverage_penalty),
            3,
        )
        seed["knockout_round32_form"] = {
            "policy": "knockout_round32_process_form_v1",
            "predictionTarget": "90_minutes",
            "home": home.to_dict(),
            "away": away.to_dict(),
            "homeLatePressure": {
                "attackMultiplier": round(home.late_attack_multiplier, 4),
                "defensiveRiskMultiplier": round(home.late_defensive_risk_multiplier, 4),
            },
            "awayLatePressure": {
                "attackMultiplier": round(away.late_attack_multiplier, 4),
                "defensiveRiskMultiplier": round(away.late_defensive_risk_multiplier, 4),
            },
            "xgNet": {"home": round(home_net, 4), "away": round(away_net, 4)},
            "adjustedExpectedGoals": {
                "home": round(adjusted_home, 4),
                "away": round(adjusted_away, 4),
            },
            "applied": True,
        }
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "preRound32ExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "round32ProcessNet": {"home": round(home_net, 4), "away": round(away_net, 4)},
            "adjustedExpectedGoals": {
                "home": round(adjusted_home, 4),
                "away": round(adjusted_away, 4),
            },
            "round32ProcessLayer": "knockout_round32_process_form_v1",
        }
