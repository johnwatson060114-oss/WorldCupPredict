from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.current_tournament_evidence import load_evidence_matches
from pipeline.football_data import TEAM_NAMES_ZH
from pipeline.match_timeline import (
    ATTACKING_EVENT_TYPES,
    CARD_EVENT_TYPES,
    DISTORTION_EVENT_TYPES,
    extract_timeline,
    match_tactical_summary,
)


BEIJING = ZoneInfo("Asia/Shanghai")
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary"
ESPN_CACHE = ROOT / ".cache" / "pipeline" / "espn-commentary-review"
CURRENT_TIMELINE_PATH = ROOT / "public" / "data" / "knockout-match-timelines.json"
HISTORICAL_CORPUS_PATH = ROOT / "public" / "data" / "final-four-commentary-corpus.json"
PUBLIC_REVIEW_PATH = ROOT / "public" / "data" / "knockout-commentary-review.json"
ARTIFACT_REVIEW_PATH = ROOT / "artifacts" / "knockout-commentary-review.json"
EVIDENCE_PATH = ROOT / "pipeline" / "data" / "knockout-commentary-evidence.json"
POLICY_PATH = ROOT / "pipeline" / "data" / "final-four-policy.json"
USER_AGENT = "WorldCupPredict/0.2 (commentary-first knockout review)"

CURRENT_CONFIG = {
    "tournament": "2026 FIFA World Cup",
    "league": "fifa.world",
    "dates": "20260628-20260712",
    "expectedMatches": 28,
}

HISTORICAL_CONFIGS = (
    {"tournament": "2018 FIFA World Cup", "league": "fifa.world", "dates": "20180710-20180715", "hasThirdPlace": True},
    {"tournament": "2022 FIFA World Cup", "league": "fifa.world", "dates": "20221213-20221218", "hasThirdPlace": True},
    {"tournament": "UEFA Euro 2020", "league": "uefa.euro", "dates": "20210706-20210711", "hasThirdPlace": False},
    {"tournament": "UEFA Euro 2024", "league": "uefa.euro", "dates": "20240709-20240714", "hasThirdPlace": False},
    {"tournament": "2021 Copa America", "league": "conmebol.america", "dates": "20210705-20210711", "hasThirdPlace": True},
    {"tournament": "2024 Copa America", "league": "conmebol.america", "dates": "20240709-20240714", "hasThirdPlace": True},
)

PSEUDO_XG_WEIGHTS = {
    "goal": 0.10,
    "chance_saved": 0.11,
    "chance_missed": 0.06,
    "chance_blocked": 0.04,
    "woodwork": 0.18,
}
PRESSURE_TYPES = set(PSEUDO_XG_WEIGHTS)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_json(url: str, params: dict[str, Any], cache_path: Path, offline: bool) -> dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    if offline:
        return {}
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=45)
    response.raise_for_status()
    payload = response.json()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _competition(event: dict[str, Any]) -> dict[str, Any]:
    return event["competitions"][0]


def _competitors(container: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = {row["homeAway"]: row for row in container["competitors"]}
    return rows["home"], rows["away"]


def _team_name(team: dict[str, Any]) -> str:
    english = str(team.get("displayName") or team.get("name") or "")
    return TEAM_NAMES_ZH.get(english, english)


def _score_value(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _score_details(summary: dict[str, Any]) -> dict[str, Any]:
    competition = summary["header"]["competitions"][0]
    home, away = _competitors(competition)

    def periods(competitor: dict[str, Any]) -> list[int]:
        return [_score_value(row.get("displayValue")) for row in competitor.get("linescores", [])]

    home_periods, away_periods = periods(home), periods(away)
    return {
        "halfTime": {
            "home": home_periods[0] if home_periods else 0,
            "away": away_periods[0] if away_periods else 0,
        },
        "regularTime": {
            "home": sum(home_periods[:2]) if home_periods else _score_value(home.get("score")),
            "away": sum(away_periods[:2]) if away_periods else _score_value(away.get("score")),
        },
        "afterExtraTime": {
            "home": _score_value(home.get("score")),
            "away": _score_value(away.get("score")),
        },
        "wentToExtraTime": len(home_periods) >= 3 or len(away_periods) >= 3,
        "wentToShootout": str(competition.get("status", {}).get("type", {}).get("detail") or "").upper() == "FT-PENS",
        "advancedTeamEnglish": str((home if home.get("winner") else away).get("team", {}).get("displayName") or "")
        if home.get("winner") or away.get("winner") else None,
    }


def _stage_for_index(index: int, count: int, has_third_place: bool = True) -> str:
    if count == 28:
        if index < 16:
            return "LAST_32"
        if index < 24:
            return "LAST_16"
        return "QUARTER_FINALS"
    if index < 2:
        return "SEMI_FINAL"
    if has_third_place and index == 2:
        return "THIRD_PLACE"
    return "FINAL"


def _translate_events(
    events: list[dict[str, Any]],
    english_names: tuple[str, str],
    localized_names: tuple[str, str],
) -> list[dict[str, Any]]:
    translation = dict(zip(english_names, localized_names, strict=True))
    return [{**event, "team": translation.get(event.get("team"), event.get("team"))} for event in events]


def _translate_summary(
    summary: dict[str, Any],
    english_names: tuple[str, str],
    localized_names: tuple[str, str],
) -> dict[str, Any]:
    translation = dict(zip(english_names, localized_names, strict=True))
    return {
        **summary,
        "teams": {
            translation.get(team, team): value
            for team, value in summary.get("teams", {}).items()
        },
    }


def _team_events(events: Iterable[dict[str, Any]], team: str, types: set[str]) -> list[dict[str, Any]]:
    return [
        event for event in events
        if event.get("regulationTime", True) and event.get("team") == team and event.get("type") in types
    ]


def _pseudo_xg(events: Iterable[dict[str, Any]], team: str, periods: set[int] | None = None) -> float:
    return sum(
        PSEUDO_XG_WEIGHTS.get(str(event.get("type")), 0.0)
        for event in events
        if event.get("regulationTime", True)
        and event.get("team") == team
        and (periods is None or event.get("period") in periods)
    )


def _result_mechanisms(
    events: list[dict[str, Any]],
    teams: tuple[str, str],
    score: dict[str, Any],
) -> list[str]:
    home, away = teams
    regulation = score["regularTime"]
    half = score["halfTime"]
    mechanisms: list[str] = []
    if half["home"] == half["away"] == 0:
        mechanisms.append("goalless_first_half")
    if half["home"] == half["away"] and regulation["home"] != regulation["away"]:
        mechanisms.append("second_half_breakthrough")

    goals = [
        event for event in events
        if event.get("regulationTime", True)
        and event.get("type") in {"goal", "penalty_goal", "own_goal"}
        and event.get("team") in teams
    ]
    running = {home: 0, away: 0}
    final_winner = home if regulation["home"] > regulation["away"] else away if regulation["away"] > regulation["home"] else None
    trailed = False
    for goal in goals:
        scorer = str(goal["team"])
        running[scorer] += 1
        if final_winner and running[final_winner] < running[away if final_winner == home else home]:
            trailed = True
    if final_winner and trailed:
        mechanisms.append("comeback_win")
    if final_winner:
        winner_goals = [goal for goal in goals if goal.get("team") == final_winner]
        if winner_goals and float(winner_goals[-1].get("minute", 0)) >= 75:
            mechanisms.append("late_decider")
        if winner_goals and bool(winner_goals[-1].get("setPiece")):
            mechanisms.append("set_piece_decider")

    all_types = Counter(str(event.get("type")) for event in events)
    if all_types["red_card"] or all_types["second_yellow"]:
        mechanisms.append("red_card_distorted")
    if all_types["penalty_goal"] or all_types["penalty_event"]:
        mechanisms.append("penalty_distorted")
    if all_types["own_goal"]:
        mechanisms.append("own_goal_distorted")
    if any(bool(event.get("forcedInjurySubstitution")) for event in events):
        mechanisms.append("forced_injury_substitution")
    if score["wentToExtraTime"]:
        mechanisms.append("extra_time_load")
    if score["wentToShootout"]:
        mechanisms.append("penalty_shootout_load")

    home_pxg, away_pxg = _pseudo_xg(events, home), _pseudo_xg(events, away)
    if final_winner:
        winner_pxg = home_pxg if final_winner == home else away_pxg
        loser_pxg = away_pxg if final_winner == home else home_pxg
        mechanisms.append("pressure_supported_result" if winner_pxg >= loser_pxg else "result_outpaced_pressure")
    return mechanisms


def _process_summary(
    events: list[dict[str, Any]],
    teams: tuple[str, str],
    score: dict[str, Any],
) -> dict[str, Any]:
    home, away = teams
    goals = [
        {
            "minute": event.get("displayMinute"),
            "period": event.get("period"),
            "team": event.get("team"),
            "player": event.get("player"),
            "type": event.get("type"),
            "setPiece": bool(event.get("setPiece")),
        }
        for event in events
        if event.get("regulationTime", True)
        and event.get("type") in {"goal", "penalty_goal", "own_goal"}
    ]
    team_payload: dict[str, Any] = {}
    total_pxg = _pseudo_xg(events, home) + _pseudo_xg(events, away)
    first_total = _pseudo_xg(events, home, {1}) + _pseudo_xg(events, away, {1})
    for team in teams:
        pressure = _team_events(events, team, PRESSURE_TYPES)
        late_pressure = [event for event in pressure if event.get("period") == 2 and float(event.get("minute", 0)) >= 70]
        extra_time_pressure = [
            event for event in events
            if event.get("extraTime") and event.get("team") == team and event.get("type") in PRESSURE_TYPES
        ]
        extra_time_injuries = [
            event for event in events
            if event.get("extraTime")
            and event.get("team") == team
            and (event.get("type") in {"injury", "fatigue"} or bool(event.get("forcedInjurySubstitution")))
        ]
        pxg = _pseudo_xg(events, team)
        late_rate = len(late_pressure) / 20 * 15
        extra_time_rate = len(extra_time_pressure) / 30 * 15
        intensity_ratio = extra_time_rate / late_rate if late_rate >= 0.25 else None
        visible_fatigue = sum(
            event.get("team") == team and event.get("type") == "fatigue"
            for event in events
        )
        post90_load = 0.0
        if score["wentToExtraTime"]:
            post90_load += 0.35
            post90_load += min(0.25, 0.10 * len(extra_time_injuries))
            post90_load += min(0.15, 0.05 * visible_fatigue)
            if intensity_ratio is not None and intensity_ratio < 0.60:
                post90_load += 0.10
        if score["wentToShootout"]:
            post90_load += 0.15
        team_payload[team] = {
            "pressureEvents90": len(pressure),
            "pseudoXg90": round(pxg, 3),
            "pseudoXgShare90": round(pxg / total_pxg, 4) if total_pxg else 0.5,
            "firstHalfPseudoXg": round(_pseudo_xg(events, team, {1}), 3),
            "latePressureEvents": len(late_pressure),
            "setPiecePressureEvents": sum(bool(event.get("setPiece")) for event in pressure),
            "cards": sum(event.get("team") == team and event.get("type") in CARD_EVENT_TYPES for event in events),
            "injuryInterruptions": sum(event.get("team") == team and event.get("type") == "injury" for event in events),
            "forcedInjurySubstitutions": sum(event.get("team") == team and bool(event.get("forcedInjurySubstitution")) for event in events),
            "visibleFatigueEvents": visible_fatigue,
            "extraTimeProcess": {
                "pressureEvents": len(extra_time_pressure),
                "pseudoXg": round(sum(PSEUDO_XG_WEIGHTS.get(str(event.get("type")), 0.0) for event in extra_time_pressure), 3),
                "attackRatePer15": round(extra_time_rate, 3),
                "lateRegulationAttackRatePer15": round(late_rate, 3),
                "intensityRatioProxy": round(intensity_ratio, 3) if intensity_ratio is not None else None,
                "injuryOrFatigueEvents": len(extra_time_injuries),
                "proxyOnly": True,
            },
            "post90LoadSeverity": round(clamp(post90_load, 0.0, 1.0), 3),
        }

    mechanisms = _result_mechanisms(events, teams, score)
    half = score["halfTime"]
    regular = score["regularTime"]
    goal_text = "；".join(
        f"{goal['minute']} {goal['team']} {goal['player'] or goal['type']}"
        for goal in goals
    ) or "90分钟内无进球"
    narrative = (
        f"半场 {home} {half['home']}-{half['away']} {away}，"
        f"90分钟 {regular['home']}-{regular['away']}；{goal_text}。"
        f"解说事件显示进攻过程权重 {home} {team_payload[home]['pseudoXg90']:.2f}、"
        f"{away} {team_payload[away]['pseudoXg90']:.2f}。"
    )
    if score["wentToExtraTime"]:
        advanced = TEAM_NAMES_ZH.get(str(score.get("advancedTeamEnglish") or ""), str(score.get("advancedTeamEnglish") or ""))
        home_extra = team_payload[home]["extraTimeProcess"]
        away_extra = team_payload[away]["extraTimeProcess"]
        narrative += (
            f"常规时间未分胜负，{advanced or '胜方'}经加时或点球晋级。"
            f"加时解说记录的进攻事件为 {home} {home_extra['pressureEvents']} 次、"
            f"{away} {away_extra['pressureEvents']} 次，伤情/疲劳事件为 "
            f"{home} {home_extra['injuryOrFatigueEvents']} 次、{away} {away_extra['injuryOrFatigueEvents']} 次；"
            "这些过程进入下一场负荷，不混入本场90分钟进球标签。"
        )
    return {
        "narrative": narrative,
        "goalChronology90": goals,
        "resultMechanisms": mechanisms,
        "teamProcess": team_payload,
        "totalPseudoXg90": round(total_pxg, 3),
        "firstHalfPseudoXgShare": round(first_total / total_pxg, 4) if total_pxg else 0.45,
        "classifiedEventCount": len(events),
        "regulationEventCount": sum(event.get("regulationTime", True) for event in events),
        "post90EventCount": sum(not event.get("regulationTime", True) for event in events),
    }


def build_tournament(config: dict[str, Any], offline: bool, historical: bool) -> list[dict[str, Any]]:
    league, dates = str(config["league"]), str(config["dates"])
    scoreboard = fetch_json(
        ESPN_SCOREBOARD.format(league=league),
        {"dates": dates, "limit": 100},
        ESPN_CACHE / league / f"scoreboard-{dates}.json",
        offline,
    )
    raw_events = sorted(scoreboard.get("events", []), key=lambda event: str(event.get("date") or ""))
    records: list[dict[str, Any]] = []
    for index, event in enumerate(raw_events):
        competition = _competition(event)
        home_row, away_row = _competitors(competition)
        home_en = str(home_row["team"]["displayName"])
        away_en = str(away_row["team"]["displayName"])
        home_zh = _team_name(home_row["team"])
        away_zh = _team_name(away_row["team"])
        source_url = f"https://www.espn.com/soccer/commentary/_/gameId/{event['id']}"
        summary_payload = fetch_json(
            ESPN_SUMMARY.format(league=league),
            {"event": event["id"]},
            ESPN_CACHE / league / f"{event['id']}.json",
            offline,
        )
        if not summary_payload.get("commentary"):
            continue
        score = _score_details(summary_payload)
        raw_timeline = extract_timeline(summary_payload["commentary"], (home_en, away_en), source_url)
        timeline = _translate_events(raw_timeline, (home_en, away_en), (home_zh, away_zh))
        tactical = _translate_summary(
            match_tactical_summary(raw_timeline, (home_en, away_en)),
            (home_en, away_en),
            (home_zh, away_zh),
        )
        stage = _stage_for_index(index, len(raw_events), bool(config.get("hasThirdPlace", True)))
        records.append({
            "espnEventId": str(event["id"]),
            "tournament": config["tournament"],
            "stage": stage,
            "utcDate": event.get("date"),
            "homeTeam": home_zh,
            "awayTeam": away_zh,
            "score": score,
            "events": timeline,
            "tacticalSummary": tactical,
            "processSummary": _process_summary(timeline, (home_zh, away_zh), score),
            "source": {
                "type": "minute_by_minute",
                "provider": "ESPN match commentary",
                "url": source_url,
                "commentaryLinesRead": len(summary_payload["commentary"]),
            },
            "historicalStageTraining": historical,
        })
    return records


def _forecast_index() -> dict[frozenset[str], Any]:
    index: dict[frozenset[str], Any] = {}
    for row in load_evidence_matches():
        if not row.pre_match_forecast_available:
            continue
        index[frozenset((row.home_team, row.away_team))] = row
    return index


def _credibility(match: dict[str, Any]) -> tuple[float, list[str]]:
    events = match["events"]
    labels: list[str] = []
    weight = 0.90 if len(events) >= 20 else 0.65
    types = Counter(str(event.get("type")) for event in events)
    if types["red_card"] or types["second_yellow"]:
        weight *= 0.40
        labels.append("red_card_changed_process")
    if types["penalty_goal"] or types["penalty_event"] or types["own_goal"]:
        weight *= 0.70
        labels.append("penalty_or_own_goal_distorted")
    if match["score"]["wentToExtraTime"]:
        labels.append("extra_time_load_after_90")
    if any(event.get("forcedInjurySubstitution") for event in events):
        labels.append("forced_injury_substitution")
    if not labels:
        labels.append("commentary_process_supported")
    return round(weight, 4), labels


def build_current_evidence(matches: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    forecast = _forecast_index()
    rows: list[dict[str, Any]] = []
    for match in matches:
        home, away = match["homeTeam"], match["awayTeam"]
        prior = forecast.get(frozenset((home, away)))
        if prior:
            expected = {
                home: prior.home_xg if prior.home_team == home else prior.away_xg,
                away: prior.home_xg if prior.home_team == away else prior.away_xg,
            }
            expected_share = expected[home] / max(0.01, expected[home] + expected[away])
            expected_source = "latest_pre_match_forecast_xg_share"
        else:
            expected_share = 0.5
            expected_source = "neutral_share_fallback"
        process = match["processSummary"]["teamProcess"]
        home_share = float(process[home]["pseudoXgShare90"])
        credibility_weight, credibility_labels = _credibility(match)
        signals: dict[str, Any] = {}
        for team, observed_share, baseline_share in (
            (home, home_share, expected_share),
            (away, 1.0 - home_share, 1.0 - expected_share),
        ):
            first_home = float(process[home]["firstHalfPseudoXg"])
            first_away = float(process[away]["firstHalfPseudoXg"])
            first_total = first_home + first_away
            first_observed = (first_home / first_total if team == home else first_away / first_total) if first_total else 0.5
            signals[team] = {
                "attackShareResidual": round(observed_share - baseline_share, 4),
                # Positive defense residual means the opponent generated more
                # pressure than expected (defensive risk), matching the sign
                # convention used by current_tournament_evidence.
                "defenseShareResidual": round(baseline_share - observed_share, 4),
                "firstHalfShareResidual": round(first_observed - baseline_share, 4),
                "credibilityWeight": credibility_weight,
                "credibilityLabels": credibility_labels,
                "extraTimeLoad": bool(match["score"]["wentToExtraTime"]),
                "shootoutLoad": bool(match["score"]["wentToShootout"]),
                "injuryInterruptions": process[team]["injuryInterruptions"],
                "forcedInjurySubstitutions": process[team]["forcedInjurySubstitutions"],
                "visibleFatigueEvents": process[team]["visibleFatigueEvents"],
                "extraTimeProcess": process[team]["extraTimeProcess"],
                "post90LoadSeverity": process[team]["post90LoadSeverity"],
                "scoreResidualDiagnosticOnly": True,
            }
        rows.append({
            "matchKey": f"{home} vs {away}",
            "espnEventId": match["espnEventId"],
            "kickoff": match["utcDate"],
            "stage": match["stage"],
            "homeTeam": home,
            "awayTeam": away,
            "expectedShareSource": expected_source,
            "preMatchExpectedGoals": (
                {
                    "home": round(prior.home_xg if prior.home_team == home else prior.away_xg, 4),
                    "away": round(prior.home_xg if prior.home_team == away else prior.away_xg, 4),
                }
                if prior else None
            ),
            "regularTimeScore": match["score"]["regularTime"],
            "signals": signals,
            "sourceUrl": match["source"]["url"],
        })
    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "policy": "current_knockout_commentary_evidence_v1",
        "predictionTarget": "90_minutes",
        "scoreResidualsDirectlyAdjustStrength": False,
        "processSignal": "commentary_pseudo_xg_share_minus_pre_match_expected_xg_share",
        "matches": rows,
    }
    payload["validation"] = _walk_forward_process_validation(rows)
    return payload


def _row_datetime(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(row["kickoff"]).replace("Z", "+00:00"))


def _prior_team_signal(
    rows: list[dict[str, Any]],
    team: str,
    cutoff: datetime,
    scale: float,
) -> tuple[float, float, float | None]:
    prior = [
        row for row in rows
        if _row_datetime(row) < cutoff and team in row["signals"]
    ]
    prior.sort(key=_row_datetime, reverse=True)
    weighted_attack = weighted_defense = weight_total = 0.0
    for index, row in enumerate(prior):
        signal = row["signals"][team]
        weight = math.exp(-math.log(2) * index / 2.0) * float(signal["credibilityWeight"])
        weighted_attack += float(signal["attackShareResidual"]) * weight
        weighted_defense += float(signal["defenseShareResidual"]) * weight
        weight_total += weight
    attack = weighted_attack / weight_total * scale if weight_total else 0.0
    defense = weighted_defense / weight_total * scale if weight_total else 0.0
    load: float | None = None
    if prior:
        rest_days = (cutoff - _row_datetime(prior[0])).total_seconds() / 86400
        if rest_days <= 6.0:
            load = float(prior[0]["signals"][team].get("post90LoadSeverity", 0.0))
    return attack, defense, load


def _walk_forward_process_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for scale in (0.0, 0.15, 0.30, 0.45):
        for cap in ((0.0,) if scale == 0.0 else (0.03, 0.05, 0.08, 0.12)):
            total_nll = 0.0
            evaluated = 0
            for row in rows:
                base = row.get("preMatchExpectedGoals")
                if not base:
                    continue
                cutoff = _row_datetime(row)
                home, away = row["homeTeam"], row["awayTeam"]
                home_attack, home_defense, home_load = _prior_team_signal(rows, home, cutoff, scale)
                away_attack, away_defense, away_load = _prior_team_signal(rows, away, cutoff, scale)
                if not any(
                    _row_datetime(previous) < cutoff and team in previous["signals"]
                    for previous in rows
                    for team in (home, away)
                ):
                    continue
                home_raw = 0.5 * (home_attack + away_defense)
                away_raw = 0.5 * (away_attack + home_defense)
                if home_load is not None:
                    home_raw -= 0.05 * home_load
                    away_raw += 0.03 * home_load
                if away_load is not None:
                    away_raw -= 0.05 * away_load
                    home_raw += 0.03 * away_load
                home_shift = clamp(home_raw, -cap, cap)
                away_shift = clamp(away_raw, -cap, cap)
                score = row["regularTimeScore"]
                total_nll += _poisson_nll(int(score["home"]), max(0.15, float(base["home"]) + home_shift))
                total_nll += _poisson_nll(int(score["away"]), max(0.15, float(base["away"]) + away_shift))
                evaluated += 1
            candidates.append({
                "commentaryProcessScale": scale,
                "commentaryMaxSideXgShift": cap,
                "matches": evaluated,
                "scorePoissonNll": round(total_nll / max(1, evaluated), 6),
            })
    baseline = next(row for row in candidates if row["commentaryProcessScale"] == 0.0)
    eligible = [row for row in candidates if row["matches"] >= 8]
    best = min(eligible, key=lambda row: row["scorePoissonNll"]) if eligible else baseline
    improvement = (
        (baseline["scorePoissonNll"] - best["scorePoissonNll"]) / baseline["scorePoissonNll"]
        if baseline["scorePoissonNll"] else 0.0
    )
    selected = best if improvement > 0 else baseline
    return {
        "protocol": "walk_forward_next_round_only",
        "predictionTarget": "90_minutes",
        "baseline": baseline,
        "selected": selected,
        "relativeImprovement": round(max(0.0, improvement), 6),
        "fatigueAttackPerLoad": -0.05,
        "fatigueDefenseRiskPerLoad": 0.03,
        "candidatesEvaluated": len(candidates),
        "safetyGatePassed": selected["commentaryProcessScale"] > 0,
    }


def _stage_profile(matches: list[dict[str, Any]], stage: str, prior_matches: float = 6.0) -> dict[str, float]:
    all_pace = sum(float(match["processSummary"]["totalPseudoXg90"]) for match in matches) / max(1, len(matches))
    all_first = sum(
        float(match["processSummary"]["totalPseudoXg90"]) * float(match["processSummary"]["firstHalfPseudoXgShare"])
        for match in matches
    ) / max(0.01, sum(float(match["processSummary"]["totalPseudoXg90"]) for match in matches))
    stage_matches = [match for match in matches if match["stage"] == stage]
    stage_pace = sum(float(match["processSummary"]["totalPseudoXg90"]) for match in stage_matches) / max(1, len(stage_matches))
    raw_multiplier = stage_pace / max(0.01, all_pace)
    multiplier = (len(stage_matches) * raw_multiplier + prior_matches) / (len(stage_matches) + prior_matches)
    stage_pxg = sum(float(match["processSummary"]["totalPseudoXg90"]) for match in stage_matches)
    stage_first = sum(
        float(match["processSummary"]["totalPseudoXg90"]) * float(match["processSummary"]["firstHalfPseudoXgShare"])
        for match in stage_matches
    ) / max(0.01, stage_pxg)
    first_share = (len(stage_matches) * stage_first + prior_matches * all_first) / (len(stage_matches) + prior_matches)
    return {
        "matches": len(stage_matches),
        "rawPaceMultiplier": round(raw_multiplier, 4),
        "candidateTotalXgMultiplier": round(multiplier, 4),
        "candidateFirstHalfShare": round(first_share, 4),
    }


def _poisson_nll(observed: int, expected: float) -> float:
    return expected - observed * math.log(max(expected, 1e-9)) + math.lgamma(observed + 1)


def _loo_validation(matches: list[dict[str, Any]], stage: str) -> dict[str, Any]:
    baseline_nll = candidate_nll = 0.0
    test_matches = 0
    tournaments = sorted({str(match["tournament"]) for match in matches})
    for held_out in tournaments:
        train = [match for match in matches if match["tournament"] != held_out]
        test = [match for match in matches if match["tournament"] == held_out and match["stage"] == stage]
        if not test or not any(match["stage"] == stage for match in train):
            continue
        baseline_lambda = sum(
            int(match["score"]["regularTime"]["home"]) + int(match["score"]["regularTime"]["away"])
            for match in train
        ) / max(1, len(train))
        multiplier = _stage_profile(train, stage)["candidateTotalXgMultiplier"]
        for match in test:
            goals = int(match["score"]["regularTime"]["home"]) + int(match["score"]["regularTime"]["away"])
            baseline_nll += _poisson_nll(goals, baseline_lambda)
            candidate_nll += _poisson_nll(goals, baseline_lambda * multiplier)
            test_matches += 1
    relative = (baseline_nll - candidate_nll) / baseline_nll if baseline_nll else 0.0
    return {
        "protocol": "leave_one_tournament_out",
        "testMatches": test_matches,
        "baselinePoissonNll": round(baseline_nll / max(1, test_matches), 5),
        "commentaryStageNll": round(candidate_nll / max(1, test_matches), 5),
        "relativeImprovement": round(relative, 5),
        "passed": test_matches >= 4 and relative > 0,
    }


def build_stage_policy(historical: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    previous = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    stages: dict[str, Any] = {}
    validations: dict[str, Any] = {}
    for stage in ("SEMI_FINAL", "FINAL", "THIRD_PLACE"):
        profile = _stage_profile(historical, stage)
        validation = _loo_validation(historical, stage)
        validations[stage] = validation
        old = previous["stageProfiles"][stage]
        # A commentary-derived stage curve is deliberately blended rather than
        # replacing the base strength model.  Failed or tiny-sample curves turn
        # themselves off.
        blend = 0.20 if validation["passed"] and profile["matches"] >= 6 else 0.10 if validation["passed"] else 0.0
        stages[stage] = {
            "candidateTotalXgMultiplier": profile["candidateTotalXgMultiplier"],
            "candidateFirstHalfShare": profile["candidateFirstHalfShare"],
            "activeMatrixBlend": blend,
            "coveragePenalty": old["coveragePenalty"],
            "uncertaintyMultiplier": old["uncertaintyMultiplier"],
            "valueProbabilityGap": old["valueProbabilityGap"],
            "trainingMatches": profile["matches"],
            "rawCommentaryPaceMultiplier": profile["rawPaceMultiplier"],
        }
    passed = [stage for stage, value in validations.items() if value["passed"]]
    return {
        "schemaVersion": 2,
        "generatedAt": generated_at,
        "policy": "world_cup_final_four_commentary_matrix_v2",
        "predictionTarget": "90_minutes",
        "scoreMatrix": previous["scoreMatrix"],
        "stageProfiles": stages,
        "validation": {
            "status": "commentary_trained_safety_gated",
            "reason": "stage pace is derived from archived minute-by-minute pressure events; only leave-one-tournament-out improvements are blended",
            "leakagePolicy": "held-out tournament commentary and results never enter its training fold; extra time and shootouts are load only",
            "historicalTournaments": len({match["tournament"] for match in historical}),
            "historicalMatches": len(historical),
            "passedStages": passed,
            "metrics": validations,
            "requiredMetrics": ["poisson_total_goal_negative_log_likelihood"],
            "comparators": ["stage_neutral_poisson"],
        },
    }


def review_payload(
    current: list[dict[str, Any]],
    historical: list[dict[str, Any]],
    policy: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {
            "currentKnockoutMatches": len(current),
            "currentCommentaryLinesRead": sum(match["source"]["commentaryLinesRead"] for match in current),
            "historicalFinalFourMatches": len(historical),
            "historicalCommentaryLinesRead": sum(match["source"]["commentaryLinesRead"] for match in historical),
            "historicalTournaments": len({match["tournament"] for match in historical}),
        },
        "method": {
            "policy": "commentary_first_knockout_review_v1",
            "predictionTarget": "90_minutes",
            "fullScoreOnlyModel": False,
            "scoreResidualsDirectlyAdjustStrength": False,
            "regularTimeProcessFeatures": [
                "shot_like_pressure_by_period",
                "late_pressure",
                "set_piece_creation",
                "cards",
                "injury_interruptions",
                "forced_injury_substitutions",
                "result_versus_pressure_support",
            ],
            "post90LoadFeatures": [
                "extra_time_pressure_rate",
                "extra_time_intensity_drop_proxy",
                "extra_time_injury_and_cramp_events",
                "forced_injury_substitutions",
                "penalty_shootout",
            ],
            "runningDistancePolicy": "commentary has no GPS distance; event-rate change is labeled as a proxy and never presented as measured running distance",
            "copyrightPolicy": "structured event coordinates and paraphrased factual summaries only",
        },
        "stagePolicy": policy,
        "sources": {
            "provider": "ESPN match commentary",
            "currentScoreboard": "https://www.espn.com/soccer/scoreboard/_/league/fifa.world",
            "matchSourceUrlsArchived": len(current) + len(historical),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    generated_at = datetime.now(BEIJING).isoformat(timespec="seconds")

    current = build_tournament(CURRENT_CONFIG, args.offline, historical=False)
    if len(current) != CURRENT_CONFIG["expectedMatches"]:
        raise RuntimeError(f"expected 28 completed current knockout matches, received {len(current)}")
    historical = [
        match
        for config in HISTORICAL_CONFIGS
        for match in build_tournament(config, args.offline, historical=True)
    ]
    if len(historical) != 22:
        raise RuntimeError(f"expected 22 historical final-four matches, received {len(historical)}")

    current_evidence = build_current_evidence(current, generated_at)
    policy = build_stage_policy(historical, generated_at)
    review = review_payload(current, historical, policy, generated_at)
    common_sources = {
        "provider": "ESPN match commentary",
        "copyrightPolicy": "structured event coordinates and paraphrased factual summaries only",
    }
    write_json(CURRENT_TIMELINE_PATH, {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {"matches": len(current), "rounds": ["LAST_32", "LAST_16", "QUARTER_FINALS"]},
        "sources": common_sources,
        "matches": current,
    })
    write_json(HISTORICAL_CORPUS_PATH, {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {"matches": len(historical), "tournaments": len(HISTORICAL_CONFIGS)},
        "sources": common_sources,
        "matches": historical,
    })
    write_json(EVIDENCE_PATH, current_evidence)
    write_json(POLICY_PATH, policy)
    write_json(PUBLIC_REVIEW_PATH, review)
    write_json(ARTIFACT_REVIEW_PATH, review)
    print(
        f"Archived {len(current)} current and {len(historical)} historical matches; "
        f"read {review['scope']['currentCommentaryLinesRead'] + review['scope']['historicalCommentaryLinesRead']} commentary lines; "
        f"stage gates {policy['validation']['passedStages']}"
    )


if __name__ == "__main__":
    main()
