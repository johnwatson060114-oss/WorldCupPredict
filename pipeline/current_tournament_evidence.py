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
DEFAULT_COMMENTARY_EVIDENCE_PATH = ROOT / "pipeline" / "data" / "knockout-commentary-evidence.json"


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
    process_attack_residual_home: float | None = None
    process_attack_residual_away: float | None = None
    process_defense_residual_home: float | None = None
    process_defense_residual_away: float | None = None
    first_half_process_residual_home: float | None = None
    first_half_process_residual_away: float | None = None
    commentary_credibility_home: float = 0.0
    commentary_credibility_away: float = 0.0
    post90_load_home: float = 0.0
    post90_load_away: float = 0.0
    visible_fatigue_home: int = 0
    visible_fatigue_away: int = 0
    forced_injury_substitutions_home: int = 0
    forced_injury_substitutions_away: int = 0
    commentary_source_url: str | None = None
    pre_match_forecast_available: bool = True


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


def load_commentary_validation(
    path: Path = DEFAULT_COMMENTARY_EVIDENCE_PATH,
) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("validation", {})


def load_evidence_matches(
    history_dir: Path = DEFAULT_HISTORY_DIR,
    settlements_path: Path = DEFAULT_SETTLEMENTS_PATH,
    commentary_evidence_path: Path = DEFAULT_COMMENTARY_EVIDENCE_PATH,
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

    commentary_by_teams: dict[frozenset[str], dict[str, Any]] = {}
    commentary_rows: list[dict[str, Any]] = []
    if commentary_evidence_path.exists():
        commentary_payload = json.loads(commentary_evidence_path.read_text(encoding="utf-8"))
        commentary_rows = list(commentary_payload.get("matches", []))
        commentary_by_teams = {
            frozenset((str(row["homeTeam"]), str(row["awayTeam"]))): row
            for row in commentary_rows
        }

    result: list[EvidenceMatch] = []
    for match_id, (_generated_at, match) in forecasts.items():
        settlement = settlements[match_id]
        kickoff = _parse_datetime(match.get("kickoff") or match.get("kickoffBeijing"))
        xg = _forecast_xg(match)
        if kickoff is None or xg is None:
            continue
        raw = str(settlement.get("rawSettlementScore") or "").upper()
        home_team = str(match.get("homeTeam") or "")
        away_team = str(match.get("awayTeam") or "")
        commentary = commentary_by_teams.get(frozenset((home_team, away_team))) or {}
        signals = commentary.get("signals") or {}
        home_signal = signals.get(home_team) or {}
        away_signal = signals.get(away_team) or {}
        result.append(EvidenceMatch(
            match_id=match_id,
            kickoff=kickoff,
            home_team=home_team,
            away_team=away_team,
            home_xg=xg[0],
            away_xg=xg[1],
            home_goals=int(settlement["homeScore"]),
            away_goals=int(settlement["awayScore"]),
            half_home_goals=(int(settlement["halfTimeHomeScore"]) if settlement.get("halfTimeHomeScore") is not None else None),
            half_away_goals=(int(settlement["halfTimeAwayScore"]) if settlement.get("halfTimeAwayScore") is not None else None),
            extra_time_load=(
                "AET" in raw
                or "PEN" in raw
                or "PENALT" in raw
                or bool(home_signal.get("extraTimeLoad"))
                or bool(away_signal.get("extraTimeLoad"))
            ),
            process_attack_residual_home=(float(home_signal["attackShareResidual"]) if home_signal else None),
            process_attack_residual_away=(float(away_signal["attackShareResidual"]) if away_signal else None),
            process_defense_residual_home=(float(home_signal["defenseShareResidual"]) if home_signal else None),
            process_defense_residual_away=(float(away_signal["defenseShareResidual"]) if away_signal else None),
            first_half_process_residual_home=(float(home_signal["firstHalfShareResidual"]) if home_signal else None),
            first_half_process_residual_away=(float(away_signal["firstHalfShareResidual"]) if away_signal else None),
            commentary_credibility_home=float(home_signal.get("credibilityWeight", 0.0)),
            commentary_credibility_away=float(away_signal.get("credibilityWeight", 0.0)),
            post90_load_home=float(home_signal.get("post90LoadSeverity", 0.0)),
            post90_load_away=float(away_signal.get("post90LoadSeverity", 0.0)),
            visible_fatigue_home=int(home_signal.get("visibleFatigueEvents", 0)),
            visible_fatigue_away=int(away_signal.get("visibleFatigueEvents", 0)),
            forced_injury_substitutions_home=int(home_signal.get("forcedInjurySubstitutions", 0)),
            forced_injury_substitutions_away=int(away_signal.get("forcedInjurySubstitutions", 0)),
            commentary_source_url=str(commentary.get("sourceUrl") or "") or None,
        ))

    # Commentary coverage is intentionally wider than the archived forecast
    # ledger.  Preserve every reviewed knockout match even when a legacy
    # pre-match forecast row is missing; score residuals remain diagnostic and
    # the process signal already carries its own neutral-baseline fallback.
    existing_commentary_keys = {
        frozenset((row.home_team, row.away_team))
        for row in result
        if row.process_attack_residual_home is not None
    }
    for commentary in commentary_rows:
        home_team = str(commentary["homeTeam"])
        away_team = str(commentary["awayTeam"])
        key = frozenset((home_team, away_team))
        if key in existing_commentary_keys:
            continue
        signals = commentary.get("signals") or {}
        home_signal = signals.get(home_team) or {}
        away_signal = signals.get(away_team) or {}
        expected = commentary.get("preMatchExpectedGoals") or {"home": 1.0, "away": 1.0}
        score = commentary.get("regularTimeScore") or {"home": 0, "away": 0}
        kickoff = _parse_datetime(str(commentary.get("kickoff") or ""))
        if kickoff is None:
            continue
        result.append(EvidenceMatch(
            match_id=str(commentary.get("matchKey") or f"{home_team} vs {away_team}"),
            kickoff=kickoff,
            home_team=home_team,
            away_team=away_team,
            home_xg=float(expected["home"]),
            away_xg=float(expected["away"]),
            home_goals=int(score["home"]),
            away_goals=int(score["away"]),
            extra_time_load=bool(home_signal.get("extraTimeLoad") or away_signal.get("extraTimeLoad")),
            process_attack_residual_home=float(home_signal["attackShareResidual"]),
            process_attack_residual_away=float(away_signal["attackShareResidual"]),
            process_defense_residual_home=float(home_signal["defenseShareResidual"]),
            process_defense_residual_away=float(away_signal["defenseShareResidual"]),
            first_half_process_residual_home=float(home_signal["firstHalfShareResidual"]),
            first_half_process_residual_away=float(away_signal["firstHalfShareResidual"]),
            commentary_credibility_home=float(home_signal.get("credibilityWeight", 0.0)),
            commentary_credibility_away=float(away_signal.get("credibilityWeight", 0.0)),
            post90_load_home=float(home_signal.get("post90LoadSeverity", 0.0)),
            post90_load_away=float(away_signal.get("post90LoadSeverity", 0.0)),
            visible_fatigue_home=int(home_signal.get("visibleFatigueEvents", 0)),
            visible_fatigue_away=int(away_signal.get("visibleFatigueEvents", 0)),
            forced_injury_substitutions_home=int(home_signal.get("forcedInjurySubstitutions", 0)),
            forced_injury_substitutions_away=int(away_signal.get("forcedInjurySubstitutions", 0)),
            commentary_source_url=str(commentary.get("sourceUrl") or "") or None,
            pre_match_forecast_available=False,
        ))
    unique: dict[tuple[str, frozenset[str]], EvidenceMatch] = {}
    for row in sorted(result, key=lambda item: item.kickoff):
        key = (row.kickoff.date().isoformat(), frozenset((row.home_team, row.away_team)))
        unique.setdefault(key, row)
    return sorted(unique.values(), key=lambda row: row.kickoff)


def _team_evidence(
    team: str,
    cutoff: datetime,
    evidence: list[EvidenceMatch],
    half_life: float,
    shrinkage: float,
    process_scale: float,
    fatigue_attack_per_load: float,
    fatigue_defense_risk_per_load: float,
) -> dict[str, Any]:
    rows = [row for row in evidence if row.kickoff < cutoff and team in {row.home_team, row.away_team}]
    rows.sort(key=lambda row: row.kickoff, reverse=True)
    outcome_attack = outcome_defense = outcome_weight_total = 0.0
    weighted_attack = weighted_defense = weight_total = 0.0
    first_attack = first_weight_total = 0.0
    for index, row in enumerate(rows):
        is_home = row.home_team == team
        scored = row.home_goals if is_home else row.away_goals
        conceded = row.away_goals if is_home else row.home_goals
        expected_for = row.home_xg if is_home else row.away_xg
        expected_against = row.away_xg if is_home else row.home_xg
        recency_weight = math.exp(-math.log(2) * index / max(half_life, 0.1))
        outcome_attack += (scored - expected_for) * recency_weight
        outcome_defense += (conceded - expected_against) * recency_weight
        outcome_weight_total += recency_weight

        attack_residual = row.process_attack_residual_home if is_home else row.process_attack_residual_away
        defense_residual = row.process_defense_residual_home if is_home else row.process_defense_residual_away
        first_residual = row.first_half_process_residual_home if is_home else row.first_half_process_residual_away
        credibility = row.commentary_credibility_home if is_home else row.commentary_credibility_away
        if attack_residual is not None and defense_residual is not None and credibility > 0:
            weight = recency_weight * credibility
            weighted_attack += attack_residual * weight
            weighted_defense += defense_residual * weight
            weight_total += weight
            if first_residual is not None:
                first_attack += first_residual * weight
                first_weight_total += weight

    # The process scale and cap were selected in a strict next-round
    # walk-forward test.  Score residuals below remain diagnostics only.
    attack = weighted_attack / weight_total * process_scale if weight_total else 0.0
    defense = weighted_defense / weight_total * process_scale if weight_total else 0.0
    first_attack_residual = first_attack / first_weight_total * process_scale if first_weight_total else 0.0
    outcome_shrink = (
        outcome_weight_total / (outcome_weight_total + max(shrinkage, 0.0))
        if outcome_weight_total else 0.0
    )
    outcome_attack_diagnostic = (
        outcome_attack / outcome_weight_total * outcome_shrink if outcome_weight_total else 0.0
    )
    outcome_defense_diagnostic = (
        outcome_defense / outcome_weight_total * outcome_shrink if outcome_weight_total else 0.0
    )
    fatigue_attack = fatigue_defense_risk = 0.0
    rest_days: float | None = None
    extra_time_load = False
    post90_load_severity = 0.0
    visible_fatigue_events = 0
    forced_injury_substitutions = 0
    if rows:
        rest_days = (cutoff - rows[0].kickoff).total_seconds() / 86400
        latest_is_home = rows[0].home_team == team
        post90_load_severity = (
            rows[0].post90_load_home if latest_is_home else rows[0].post90_load_away
        )
        visible_fatigue_events = (
            rows[0].visible_fatigue_home if latest_is_home else rows[0].visible_fatigue_away
        )
        forced_injury_substitutions = (
            rows[0].forced_injury_substitutions_home
            if latest_is_home else rows[0].forced_injury_substitutions_away
        )
        extra_time_load = (rows[0].extra_time_load or post90_load_severity > 0) and rest_days <= 6.0
        if extra_time_load:
            if post90_load_severity > 0:
                fatigue_attack = fatigue_attack_per_load * post90_load_severity
                fatigue_defense_risk = fatigue_defense_risk_per_load * post90_load_severity
            else:
                # Backward-compatible fallback for legacy rows with an AET/PEN
                # marker but no archived extra-time commentary.
                fatigue_attack = -0.03
                fatigue_defense_risk = 0.02
    return {
        "team": team,
        "matchesUsed": len(rows),
        "commentaryMatchesUsed": sum(
            (row.process_attack_residual_home if row.home_team == team else row.process_attack_residual_away) is not None
            for row in rows
        ),
        "effectiveWeight": round(weight_total, 4),
        "attackResidual": round(attack, 4),
        "defenseResidual": round(defense, 4),
        "outcomeAttackResidualDiagnostic": round(outcome_attack_diagnostic, 4),
        "outcomeDefenseResidualDiagnostic": round(outcome_defense_diagnostic, 4),
        "scoreResidualsDirectlyAdjustStrength": False,
        "halfTimeMatchesUsed": sum(
            (row.first_half_process_residual_home if row.home_team == team else row.first_half_process_residual_away) is not None
            for row in rows
        ),
        "firstHalfAttackResidual": round(first_attack_residual, 4),
        "firstHalfDefenseResidual": round(-first_attack_residual, 4),
        "restDays": round(rest_days, 2) if rest_days is not None else None,
        "extraTimeLoad": extra_time_load,
        "post90LoadSeverity": round(post90_load_severity, 4),
        "visibleFatigueEvents": visible_fatigue_events,
        "forcedInjurySubstitutions": forced_injury_substitutions,
        "fatigueAttackDelta": round(fatigue_attack, 4),
        "fatigueDefenseRiskDelta": round(fatigue_defense_risk, 4),
        "commentarySourceUrls": sorted({
            str(row.commentary_source_url)
            for row in rows
            if row.commentary_source_url
        }),
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
    commentary_validation = load_commentary_validation()
    commentary_selected = commentary_validation.get("selected") or {}
    half_life = float(settings["halfLifeMatches"])
    shrinkage = float(settings["shrinkage"])
    process_scale = float(settings.get(
        "commentaryProcessScale",
        commentary_selected.get("commentaryProcessScale", 0.0),
    ))
    cap = float(settings.get(
        "commentaryMaxSideXgShift",
        commentary_selected.get("commentaryMaxSideXgShift", 0.0),
    ))
    fatigue_attack_per_load = float(settings.get(
        "fatigueAttackPerLoad",
        commentary_validation.get("fatigueAttackPerLoad", -0.05),
    ))
    fatigue_defense_risk_per_load = float(settings.get(
        "fatigueDefenseRiskPerLoad",
        commentary_validation.get("fatigueDefenseRiskPerLoad", 0.03),
    ))
    for seed in seeds:
        cutoff = _parse_datetime(str(seed.get("kickoff") or ""))
        if cutoff is None:
            continue
        base_home, base_away = map(float, seed["base_xg"])
        home = _team_evidence(
            seed["home_team"], cutoff, evidence, half_life, shrinkage, process_scale,
            fatigue_attack_per_load, fatigue_defense_risk_per_load,
        )
        away = _team_evidence(
            seed["away_team"], cutoff, evidence, half_life, shrinkage, process_scale,
            fatigue_attack_per_load, fatigue_defense_risk_per_load,
        )
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
            "policy": "current_tournament_commentary_evidence_v2",
            "predictionTarget": "90_minutes",
            "halfLifeMatches": half_life,
            "shrinkage": shrinkage,
            "commentaryProcessScale": process_scale,
            "maxSideXgShift": cap,
            "home": home,
            "away": away,
            "xgNet": {"home": round(adjusted_home - base_home, 4), "away": round(adjusted_away - base_away, 4)},
            "adjustedExpectedGoals": {"home": round(adjusted_home, 4), "away": round(adjusted_away, 4)},
            "applied": abs(adjusted_home - base_home) > 1e-12 or abs(adjusted_away - base_away) > 1e-12,
            "diagnosticOnly": cap <= 0,
            "selectionReason": "walk_forward_commentary_process_gate",
            "commentaryValidation": commentary_validation,
            "extraTimePolicy": "90_to_120_commentary_changes_next_match_load_only",
        }
        half_settings = settings.get("halfFullEvidence") or policy.get("halfFullEvidence") or {}
        half_cap = float(half_settings.get("maxFirstHalfXgShift", 0.18))
        half_life_split = float(half_settings.get("halfLifeMatches", half_life))
        half_shrinkage = float(half_settings.get("shrinkage", shrinkage))
        half_home = _team_evidence(
            seed["home_team"], cutoff, evidence, half_life_split, half_shrinkage,
            process_scale, fatigue_attack_per_load, fatigue_defense_risk_per_load,
        )
        half_away = _team_evidence(
            seed["away_team"], cutoff, evidence, half_life_split, half_shrinkage,
            process_scale, fatigue_attack_per_load, fatigue_defense_risk_per_load,
        )
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
            "formLayer": "current_tournament_commentary_evidence_v2",
        }
