from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ROOT
from .final_sprint_policy import load_final_sprint_policy


FORECAST_SECTIONS = ("matches", "parlayMatches", "parlayCandidateMatches")
DEFAULT_HISTORY_DIR = ROOT / "public" / "data" / "history"
DEFAULT_SETTLEMENTS_PATH = ROOT / "public" / "data" / "settlements.json"


@dataclass(frozen=True)
class EvidenceMatch:
    match_id: str
    kickoff: datetime
    home_team: str
    away_team: str
    home_xg: float
    away_xg: float
    home_goals: int
    away_goals: int
    extra_time_load: bool
    half_home_goals: int | None = None
    half_away_goals: int | None = None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _forecast_xg(match: dict[str, Any]) -> tuple[float, float] | None:
    decomposition = match.get("modelDecomposition") or {}
    long_term = decomposition.get("longTermExpectedGoals") or match.get("expectedGoals") or {}
    if long_term.get("home") is None or long_term.get("away") is None:
        return None
    return float(long_term["home"]), float(long_term["away"])


def load_evidence_matches(
    history_dir: Path = DEFAULT_HISTORY_DIR,
    settlements_path: Path = DEFAULT_SETTLEMENTS_PATH,
) -> list[EvidenceMatch]:
    if not history_dir.exists() or not settlements_path.exists():
        return []
    settlements_payload = json.loads(settlements_path.read_text(encoding="utf-8"))
    settlements = {str(row["matchId"]): row for row in settlements_payload.get("matches", [])}
    forecasts: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for path in sorted(history_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = _parse_datetime(payload.get("generatedAt"))
        if generated_at is None:
            continue
        for section in FORECAST_SECTIONS:
            for match in payload.get(section, []):
                match_id = str(match.get("id") or "")
                kickoff = _parse_datetime(match.get("kickoff") or match.get("kickoffBeijing"))
                if match_id not in settlements or kickoff is None or generated_at >= kickoff:
                    continue
                previous = forecasts.get(match_id)
                if previous is None or generated_at > previous[0]:
                    forecasts[match_id] = (generated_at, match)

    result: list[EvidenceMatch] = []
    for match_id, (_generated_at, match) in forecasts.items():
        settlement = settlements[match_id]
        kickoff = _parse_datetime(match.get("kickoff") or match.get("kickoffBeijing"))
        xg = _forecast_xg(match)
        if kickoff is None or xg is None:
            continue
        raw = str(settlement.get("rawSettlementScore") or "").upper()
        result.append(EvidenceMatch(
            match_id=match_id,
            kickoff=kickoff,
            home_team=str(match.get("homeTeam") or ""),
            away_team=str(match.get("awayTeam") or ""),
            home_xg=xg[0],
            away_xg=xg[1],
            home_goals=int(settlement["homeScore"]),
            away_goals=int(settlement["awayScore"]),
            half_home_goals=(int(settlement["halfTimeHomeScore"]) if settlement.get("halfTimeHomeScore") is not None else None),
            half_away_goals=(int(settlement["halfTimeAwayScore"]) if settlement.get("halfTimeAwayScore") is not None else None),
            extra_time_load="AET" in raw or "PEN" in raw or "PENALT" in raw,
        ))
    return sorted(result, key=lambda row: row.kickoff)


def _team_evidence(
    team: str,
    cutoff: datetime,
    evidence: list[EvidenceMatch],
    half_life: float,
    shrinkage: float,
) -> dict[str, Any]:
    rows = [row for row in evidence if row.kickoff < cutoff and team in {row.home_team, row.away_team}]
    rows.sort(key=lambda row: row.kickoff, reverse=True)
    weighted_attack = weighted_defense = weight_total = 0.0
    first_attack = first_defense = first_weight_total = 0.0
    for index, row in enumerate(rows):
        is_home = row.home_team == team
        scored = row.home_goals if is_home else row.away_goals
        conceded = row.away_goals if is_home else row.home_goals
        expected_for = row.home_xg if is_home else row.away_xg
        expected_against = row.away_xg if is_home else row.home_xg
        weight = math.exp(-math.log(2) * index / max(half_life, 0.1))
        weighted_attack += (scored - expected_for) * weight
        weighted_defense += (conceded - expected_against) * weight
        weight_total += weight
        if row.half_home_goals is not None and row.half_away_goals is not None:
            half_scored = row.half_home_goals if is_home else row.half_away_goals
            half_conceded = row.half_away_goals if is_home else row.half_home_goals
            first_attack += (half_scored - expected_for * 0.45) * weight
            first_defense += (half_conceded - expected_against * 0.45) * weight
            first_weight_total += weight

    shrink = weight_total / (weight_total + max(shrinkage, 0.0)) if weight_total else 0.0
    attack = weighted_attack / weight_total * shrink if weight_total else 0.0
    defense = weighted_defense / weight_total * shrink if weight_total else 0.0
    first_shrink = first_weight_total / (first_weight_total + max(shrinkage, 0.0)) if first_weight_total else 0.0
    first_attack_residual = first_attack / first_weight_total * first_shrink if first_weight_total else 0.0
    first_defense_residual = first_defense / first_weight_total * first_shrink if first_weight_total else 0.0
    fatigue_attack = fatigue_defense_risk = 0.0
    rest_days: float | None = None
    extra_time_load = False
    if rows:
        rest_days = (cutoff - rows[0].kickoff).total_seconds() / 86400
        extra_time_load = rows[0].extra_time_load and rest_days <= 6.0
        if extra_time_load:
            fatigue_attack = -0.03
            fatigue_defense_risk = 0.02
    return {
        "team": team,
        "matchesUsed": len(rows),
        "effectiveWeight": round(weight_total, 4),
        "attackResidual": round(attack, 4),
        "defenseResidual": round(defense, 4),
        "halfTimeMatchesUsed": sum(1 for row in rows if row.half_home_goals is not None),
        "firstHalfAttackResidual": round(first_attack_residual, 4),
        "firstHalfDefenseResidual": round(first_defense_residual, 4),
        "restDays": round(rest_days, 2) if rest_days is not None else None,
        "extraTimeLoad": extra_time_load,
        "fatigueAttackDelta": fatigue_attack,
        "fatigueDefenseRiskDelta": fatigue_defense_risk,
    }


def apply_current_tournament_evidence(
    seeds: list[dict[str, Any]],
    target_date: str,
    evidence: list[EvidenceMatch] | None = None,
    settings: dict[str, float] | None = None,
) -> None:
    del target_date
    evidence = load_evidence_matches() if evidence is None else evidence
    policy = load_final_sprint_policy()
    settings = settings or policy["tournamentEvidence"]
    half_life = float(settings["halfLifeMatches"])
    shrinkage = float(settings["shrinkage"])
    cap = float(settings["maxSideXgShift"])
    for seed in seeds:
        cutoff = _parse_datetime(str(seed.get("kickoff") or ""))
        if cutoff is None:
            continue
        base_home, base_away = map(float, seed["base_xg"])
        home = _team_evidence(seed["home_team"], cutoff, evidence, half_life, shrinkage)
        away = _team_evidence(seed["away_team"], cutoff, evidence, half_life, shrinkage)
        home_raw = 0.5 * (home["attackResidual"] + away["defenseResidual"])
        away_raw = 0.5 * (away["attackResidual"] + home["defenseResidual"])
        home_raw += float(home["fatigueAttackDelta"]) + float(away["fatigueDefenseRiskDelta"])
        away_raw += float(away["fatigueAttackDelta"]) + float(home["fatigueDefenseRiskDelta"])
        home_delta = max(-cap, min(cap, home_raw))
        away_delta = max(-cap, min(cap, away_raw))
        adjusted_home = max(0.15, base_home + home_delta)
        adjusted_away = max(0.15, base_away + away_delta)
        seed["base_xg"] = [adjusted_home, adjusted_away]
        payload = {
            "policy": "current_tournament_evidence_v1",
            "predictionTarget": "90_minutes",
            "halfLifeMatches": half_life,
            "shrinkage": shrinkage,
            "maxSideXgShift": cap,
            "home": home,
            "away": away,
            "xgNet": {"home": round(adjusted_home - base_home, 4), "away": round(adjusted_away - base_away, 4)},
            "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
            "applied": abs(adjusted_home - base_home) > 1e-12 or abs(adjusted_away - base_away) > 1e-12,
            "diagnosticOnly": cap <= 0,
            "selectionReason": (settings.get("validation") or {}).get("selectionReason"),
        }
        half_settings = settings.get("halfFullEvidence") or policy.get("halfFullEvidence") or {}
        half_cap = float(half_settings.get("maxFirstHalfXgShift", 0.18))
        half_life_split = float(half_settings.get("halfLifeMatches", half_life))
        half_shrinkage = float(half_settings.get("shrinkage", shrinkage))
        half_home = _team_evidence(seed["home_team"], cutoff, evidence, half_life_split, half_shrinkage)
        half_away = _team_evidence(seed["away_team"], cutoff, evidence, half_life_split, half_shrinkage)
        home_half_raw = 0.5 * (float(half_home["firstHalfAttackResidual"]) + float(half_away["firstHalfDefenseResidual"]))
        away_half_raw = 0.5 * (float(half_away["firstHalfAttackResidual"]) + float(half_home["firstHalfDefenseResidual"]))
        home_half_delta = max(-half_cap, min(half_cap, home_half_raw))
        away_half_delta = max(-half_cap, min(half_cap, away_half_raw))
        first_home = max(0.05, adjusted_home * 0.45 + home_half_delta)
        first_away = max(0.05, adjusted_away * 0.45 + away_half_delta)
        payload["halfFullEvidence"] = {
            "policy": "opponent_adjusted_half_split_v1",
            "maxFirstHalfXgShift": half_cap,
            "halfLifeMatches": half_life_split,
            "shrinkage": half_shrinkage,
            "blend": float(half_settings.get("blend", 0.0)),
            "firstHalfXgShift": {"home": round(home_half_delta, 4), "away": round(away_half_delta, 4)},
            "firstHalfExpectedGoals": {"home": round(first_home, 4), "away": round(first_away, 4)},
            "secondHalfExpectedGoals": {
                "home": round(max(0.05, adjusted_home - first_home), 4),
                "away": round(max(0.05, adjusted_away - first_away), 4),
            },
            "opponentAdjustmentBasis": "pre_match_expected_goals_residual",
        }
        seed["tournament_evidence"] = payload
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "longTermExpectedGoals": {"home": round(base_home, 4), "away": round(base_away, 4)},
            "tournamentEvidence": payload,
            "adjustedExpectedGoals": payload["adjustedExpectedGoals"],
            "formLayer": "current_tournament_evidence_v1",
        }
