from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.backtest import score_predictions
from pipeline.draw_risk import apply_draw_risk_layer
from pipeline.elo_ratings import allocate_total_goals_by_elo
from pipeline.football_data import localized_team_name
from pipeline.match_timeline import extract_timeline, match_tactical_summary, tactical_direction
from pipeline.market_guard import apply_market_strength_calibration
from pipeline.model import outcome_probabilities, score_matrix
from pipeline.settlement_store import deduplicate_settlements, normalize_team_name, normalized_match_label
from pipeline.squad_status import build_squad_status


BEIJING = ZoneInfo("Asia/Shanghai")
FOOTBALL_CACHE = ROOT / ".cache" / "pipeline" / "football-data" / "97a7f68839a6f94960f7d194.json"
ESPN_CACHE = ROOT / ".cache" / "pipeline" / "espn-world-cup"
ELO_NAMES_PATH = ROOT / ".cache" / "pipeline" / "elo-ratings" / "aba55e5bf5205a63dbcaec83.json"
ELO_WORLD_PATH = ROOT / ".cache" / "pipeline" / "elo-ratings" / "c07c64ce7cea930c8b40dd29.json"
PROFILE_PATH = ROOT / "pipeline" / "data" / "two-round-performance.json"
PUBLIC_TIMELINE_PATH = ROOT / "public" / "data" / "two-round-match-timelines.json"
PUBLIC_REVIEW_PATH = ROOT / "public" / "data" / "two-round-model-review.json"
ARTIFACT_REVIEW_PATH = ROOT / "artifacts" / "two-round-model-review.json"
AVAILABILITY_PATH = ROOT / "pipeline" / "data" / "tournament-availability.json"
FIFA_SCORES_URL = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
USER_AGENT = "WorldCupPredict/0.1 (research timeline importer)"
OBJECTIVE_MULTIPLIER = 1.5


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cached_football_matches() -> list[dict[str, Any]]:
    payload = json.loads(FOOTBALL_CACHE.read_text(encoding="utf-8"))
    value = payload.get("value", payload)
    return list(value.get("matches", []))


def cached_elo_ratings() -> dict[str, int]:
    names_payload = json.loads(ELO_NAMES_PATH.read_text(encoding="utf-8"))["value"]
    world_payload = json.loads(ELO_WORLD_PATH.read_text(encoding="utf-8"))["value"]
    names = {}
    for line in names_payload.splitlines():
        columns = line.split("\t")
        if len(columns) >= 2:
            names[columns[0]] = columns[1]
    ratings = {}
    for line in world_payload.splitlines():
        columns = line.split("\t")
        if len(columns) >= 4 and columns[3].isdigit():
            name = names.get(columns[2])
            if name:
                ratings[name] = int(columns[3])
    return ratings


def fetch_json(url: str, params: dict[str, Any], cache_path: Path, offline: bool) -> dict[str, Any]:
    if cache_path.exists() and offline:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=45)
    response.raise_for_status()
    payload = response.json()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def espn_event_index(offline: bool) -> dict[tuple[str, str], dict[str, Any]]:
    scoreboard = fetch_json(
        ESPN_SCOREBOARD_URL,
        {"dates": "20260611-20260624", "limit": 100},
        ESPN_CACHE / "scoreboard-20260611-20260624.json",
        offline,
    )
    result = {}
    for event in scoreboard.get("events", []):
        competition = event["competitions"][0]
        teams = {
            competitor["homeAway"]: competitor["team"]
            for competitor in competition.get("competitors", [])
        }
        home_tla = str(teams.get("home", {}).get("abbreviation") or "")
        away_tla = str(teams.get("away", {}).get("abbreviation") or "")
        if home_tla and away_tla:
            result[(home_tla, away_tla)] = event
    return result


def english_team_names(event: dict[str, Any]) -> tuple[str, str]:
    competitors = {
        competitor["homeAway"]: competitor["team"]["displayName"]
        for competitor in event["competitions"][0]["competitors"]
    }
    return str(competitors["home"]), str(competitors["away"])


def translate_event_teams(
    events: list[dict[str, Any]],
    english_names: tuple[str, str],
    chinese_names: tuple[str, str],
) -> list[dict[str, Any]]:
    translation = dict(zip(english_names, chinese_names, strict=True))
    return [
        {**event, "team": translation.get(event.get("team"), event.get("team"))}
        for event in events
    ]


def build_match_records(offline: bool) -> list[dict[str, Any]]:
    official = cached_football_matches()[:48]
    espn = espn_event_index(offline)
    records = []
    for index, fixture in enumerate(official, start=1):
        home_zh = localized_team_name(fixture["homeTeam"])
        away_zh = localized_team_name(fixture["awayTeam"])
        home_tla = str(fixture["homeTeam"].get("tla") or "")
        away_tla = str(fixture["awayTeam"].get("tla") or "")
        event = espn.get((home_tla, away_tla))
        status = "completed" if fixture.get("status") == "FINISHED" else "pending"
        source_url = (
            f"https://www.espn.com/soccer/commentary/_/gameId/{event['id']}"
            if event else "https://www.espn.com/soccer/scoreboard/_/league/fifa.world"
        )
        events: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "coolingBreakMinutes": [],
            "teams": {},
            "coverage": {"classifiedEvents": 0, "attackingEvents": 0, "injuryEvents": 0, "cardEvents": 0},
        }
        if event and status == "completed":
            payload = fetch_json(
                ESPN_SUMMARY_URL,
                {"event": event["id"]},
                ESPN_CACHE / f"{event['id']}.json",
                offline,
            )
            home_en, away_en = english_team_names(event)
            raw_events = extract_timeline(payload.get("commentary", []), [home_en, away_en], source_url)
            raw_summary = match_tactical_summary(raw_events, [home_en, away_en])
            events = translate_event_teams(raw_events, (home_en, away_en), (home_zh, away_zh))
            summary = {
                **raw_summary,
                "teams": {
                    home_zh: raw_summary["teams"].get(home_en, {}),
                    away_zh: raw_summary["teams"].get(away_en, {}),
                },
            }
        records.append({
            "fixtureId": fixture.get("id"),
            "matchday": 1 if index <= 24 else 2,
            "group": fixture.get("group"),
            "utcDate": fixture.get("utcDate"),
            "status": status,
            "homeTeam": home_zh,
            "awayTeam": away_zh,
            "score": fixture.get("score", {}).get("fullTime", {}),
            "halfTimeScore": fixture.get("score", {}).get("halfTime", {}),
            "events": events,
            "tacticalSummary": summary,
            "sources": [
                {"type": "official_result", "url": FIFA_SCORES_URL},
                {
                    "type": "minute_by_minute",
                    "url": source_url,
                    "archived": bool(events),
                    "espnEventId": event.get("id") if event else None,
                },
            ],
        })
    return records


def team_match_profile(
    match: dict[str, Any],
    team: str,
    opponent: str,
    ratings: dict[str, int],
    home_side: bool,
) -> dict[str, Any]:
    home_goals = int(match["score"]["home"])
    away_goals = int(match["score"]["away"])
    home_rating = ratings.get(match["homeTeam"], 1500)
    away_rating = ratings.get(match["awayTeam"], 1500)
    expected_home, expected_away = allocate_total_goals_by_elo(2.55, home_rating, away_rating)
    goals_for, goals_against = (home_goals, away_goals) if home_side else (away_goals, home_goals)
    expected_for, expected_against = (
        (expected_home, expected_away) if home_side else (expected_away, expected_home)
    )
    red_card_count = sum(
        event.get("type") in {"red_card", "second_yellow"} for event in match["events"]
    )
    high_variance = goals_for + goals_against >= 6 or abs(goals_for - expected_for) >= 3
    reliability = 0.35 if red_card_count else 0.45 if high_variance else 0.62
    attack_delta = clamp((goals_for - expected_for) * 0.025 * reliability, -0.08, 0.08)
    defense_delta = clamp((expected_against - goals_against) * 0.025 * reliability, -0.08, 0.08)
    labels = list(match["tacticalSummary"].get("teams", {}).get(team, {}).get("labels", []))
    opponent_labels = list(match["tacticalSummary"].get("teams", {}).get(opponent, {}).get("labels", []))
    tactical_attack, _ = tactical_direction(labels)
    opponent_attack, _ = tactical_direction(opponent_labels)
    tactical_defense = clamp(-opponent_attack * 0.5, -0.05, 0.05)
    return {
        "fixtureId": match["fixtureId"],
        "observedMatchday": match["matchday"],
        "observedDate": datetime.fromisoformat(str(match["utcDate"]).replace("Z", "+00:00"))
        .astimezone(BEIJING).date().isoformat(),
        "opponent": opponent,
        "scoreFor": goals_for,
        "scoreAgainst": goals_against,
        "expectedGoalsReference": round(expected_for, 4),
        "expectedGoalsAgainstReference": round(expected_against, 4),
        "evidenceConfidence": reliability if match["events"] else min(0.45, reliability),
        "objectiveForm": {
            "attackDelta": round(attack_delta, 4),
            "defenseDelta": round(defense_delta, 4),
            "redCardAdjusted": bool(red_card_count),
            "finishingOutlierShrunk": high_variance,
            "opponentStrengthAdjusted": True,
            "admissionStatus": "enabled",
        },
        "tacticalCandidate": {
            "attackDelta": round(tactical_attack, 4),
            "defenseDelta": round(tactical_defense, 4),
            "labels": labels,
            "corroboration": "minute_coordinates_plus_event_count_shift" if labels else "insufficient",
            "admissionStatus": "observation_only",
        },
        "evidence": {
            "timelineArchived": bool(match["events"]),
            "eventCount": len(match["events"]),
            "coolingBreakMinutes": match["tacticalSummary"].get("coolingBreakMinutes", []),
            "sources": match["sources"],
        },
    }


def build_team_profiles(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ratings_en = cached_elo_ratings()
    ratings = {
        localized_team_name(team): ratings_en.get(str(team.get("name")), 1500)
        for fixture in cached_football_matches()[:48]
        for team in (fixture.get("homeTeam", {}), fixture.get("awayTeam", {}))
    }
    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        if match["status"] != "completed":
            continue
        home, away = match["homeTeam"], match["awayTeam"]
        by_team[home].append(team_match_profile(match, home, away, ratings, True))
        by_team[away].append(team_match_profile(match, away, home, ratings, False))
    profiles = []
    for team, team_matches in sorted(by_team.items()):
        team_matches.sort(key=lambda item: item["observedMatchday"])
        labels = [
            label for match in team_matches
            for label in match["tacticalCandidate"].get("labels", [])
        ]
        profiles.append({
            "team": team,
            "summary": f"{team} 本届前两轮的客观赛果、事件时间轴与补水节点状态",
            "matches": team_matches,
            "evidence": {
                "mode": "minute_by_minute_events",
                "archivedMatches": sum(match["evidence"]["timelineArchived"] for match in team_matches),
                "tacticalLabels": labels,
                "objectiveAndTacticalSeparated": True,
            },
        })
    return profiles


def actual_outcome(home: int, away: int) -> str:
    return "home" if home > away else "draw" if home == away else "away"


def settlement_lookup(matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records = []
    for match in matches:
        if match["status"] != "completed":
            continue
        records.append({
            "fixtureId": match["fixtureId"],
            "matchId": str(match["fixtureId"]),
            "matchLabel": f"{match['homeTeam']} vs {match['awayTeam']}",
            "homeScore": match["score"]["home"],
            "awayScore": match["score"]["away"],
            "settledAt": match["utcDate"],
            "group": match["group"],
            "matchday": match["matchday"],
        })
    return {normalized_match_label(item): item for item in deduplicate_settlements(records)}


def first_match_adjustment(profile: dict[str, Any]) -> dict[str, float]:
    match = next(item for item in profile["matches"] if item["observedMatchday"] == 1)
    return {
        "attack": float(match["objectiveForm"]["attackDelta"]) * OBJECTIVE_MULTIPLIER,
        "defense": float(match["objectiveForm"]["defenseDelta"]) * OBJECTIVE_MULTIPLIER,
        "tacticalAttack": float(match["tacticalCandidate"]["attackDelta"]),
        "tacticalDefense": float(match["tacticalCandidate"]["defenseDelta"]),
    }


def market_odds(forecast: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for quote in forecast.get("quotes", []):
        if quote.get("market") != "胜平负":
            continue
        selection = str(quote.get("selection"))
        if selection in {"胜", "平", "负"}:
            result[selection] = quote.get("odds")
    return result


def review_backtest(
    matches: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    by_team = {normalize_team_name(profile["team"]): profile for profile in profiles}
    settlements = settlement_lookup(matches)
    rows: list[dict[str, Any]] = []
    for archive_path in sorted((ROOT / "public" / "data" / "history").glob("2026-06-*.json")):
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
        for forecast in payload.get("matches", []):
            key = normalized_match_label({
                "matchLabel": f"{forecast['homeTeam']} vs {forecast['awayTeam']}"
            })
            settlement = settlements.get(key)
            if not settlement or settlement.get("matchday") != 2:
                continue
            home_profile = by_team.get(normalize_team_name(forecast["homeTeam"]))
            away_profile = by_team.get(normalize_team_name(forecast["awayTeam"]))
            if not home_profile or not away_profile:
                continue
            home_first = first_match_adjustment(home_profile)
            away_first = first_match_adjustment(away_profile)
            decomposition = forecast.get("modelDecomposition", {})
            long_term = decomposition.get("longTermExpectedGoals") or forecast["expectedGoals"]
            base_home = float(long_term["home"])
            base_away = float(long_term["away"])
            objective_home = max(0.15, base_home + home_first["attack"] - away_first["defense"])
            objective_away = max(0.15, base_away + away_first["attack"] - home_first["defense"])
            tactical_home = max(
                0.15,
                objective_home + home_first["tacticalAttack"] - away_first["tacticalDefense"],
            )
            tactical_away = max(
                0.15,
                objective_away + away_first["tacticalAttack"] - home_first["tacticalDefense"],
            )
            objective_seed = {"base_xg": [objective_home, objective_away], "model_decomposition": {}}
            tactical_seed = {"base_xg": [tactical_home, tactical_away], "model_decomposition": {}}
            odds = market_odds(forecast)
            apply_market_strength_calibration(objective_seed, odds)
            apply_market_strength_calibration(tactical_seed, odds)
            objective_home, objective_away = map(float, objective_seed["base_xg"])
            tactical_home, tactical_away = map(float, tactical_seed["base_xg"])
            tactical_probabilities = outcome_probabilities(score_matrix(tactical_home, tactical_away))
            draw_risk = apply_draw_risk_layer(
                tactical_probabilities,
                {
                    "home_team": forecast["homeTeam"],
                    "away_team": forecast["awayTeam"],
                    "base_xg": [tactical_home, tactical_away],
                },
            )
            actual = actual_outcome(int(settlement["homeScore"]), int(settlement["awayScore"]))
            rows.append({
                "targetDate": payload["targetDate"],
                "match": f"{forecast['homeTeam']} vs {forecast['awayTeam']}",
                "actual": actual,
                "score": f"{settlement['homeScore']}-{settlement['awayScore']}",
                "original": {key: float(value) for key, value in forecast["outcomeProbabilities"].items()},
                "objective": outcome_probabilities(score_matrix(objective_home, objective_away)),
                "tactical": tactical_probabilities,
                "drawRisk": draw_risk.probabilities,
                "drawRiskLayer": draw_risk.metadata,
                "totalGoals": {
                    "actual": int(settlement["homeScore"]) + int(settlement["awayScore"]),
                    "originalExpected": float(forecast["expectedGoals"]["home"]) + float(forecast["expectedGoals"]["away"]),
                    "objectiveExpected": objective_home + objective_away,
                    "tacticalExpected": tactical_home + tactical_away,
                    "drawRiskExpected": tactical_home + tactical_away,
                },
            })
    metrics = {
        model: score_predictions((row[model], row["actual"]) for row in rows)
        for model in ("original", "objective", "tactical", "drawRisk")
    }
    for model in ("original", "objective", "tactical", "drawRisk"):
        metrics[model]["accuracy"] = (
            sum(max(row[model], key=row[model].get) == row["actual"] for row in rows) / len(rows)
            if rows else 0.0
        )
        metrics[model]["drawRecall"] = (
            sum(
                row["actual"] == "draw" and max(row[model], key=row[model].get) == "draw"
                for row in rows
            )
            / max(1, sum(row["actual"] == "draw" for row in rows))
        )
        metrics[model]["totalGoalsMae"] = (
            sum(abs(row["totalGoals"][f"{model}Expected"] - row["totalGoals"]["actual"]) for row in rows)
            / len(rows) if rows else math.inf
        )
    tactical_delta = {
        metric: metrics["tactical"][metric] - metrics["objective"][metric]
        for metric in ("log_loss", "rps", "calibration_error")
    }
    draw_risk_delta = {
        metric: metrics["drawRisk"][metric] - metrics["tactical"][metric]
        for metric in ("log_loss", "rps", "calibration_error")
    }
    enabled = (
        rows
        and tactical_delta["log_loss"] < 0
        and tactical_delta["rps"] < 0
        and tactical_delta["calibration_error"] <= 0.005
    )
    status = "enabled" if enabled else "observation_only"
    objective_enabled = (
        rows
        and metrics["objective"]["log_loss"] < metrics["original"]["log_loss"]
        and metrics["objective"]["rps"] < metrics["original"]["rps"]
        and metrics["objective"]["calibration_error"] <= metrics["original"]["calibration_error"] + 0.005
    )
    draw_risk_enabled = (
        rows
        and draw_risk_delta["log_loss"] < 0
        and draw_risk_delta["rps"] < 0
        and draw_risk_delta["calibration_error"] <= 0.005
    )
    return {
        "sample": {
            "completedSecondRoundMatches": len(rows),
            "plannedSecondRoundMatches": 24,
            "complete": len(rows) == 24,
            "informationCutoffPolicy": "only matchday-one evidence is used to replay matchday two",
        },
        "metrics": metrics,
        "objectiveAdmissionDecision": {
            "status": "enabled" if objective_enabled else "observation_only",
            "enabled": objective_enabled,
            "rule": "Log Loss and RPS must improve versus archived production; calibration may worsen by at most 0.005",
        },
        "tacticalDeltaVsObjective": tactical_delta,
        "admissionDecision": {
            "status": status,
            "enabled": enabled,
            "rule": "Log Loss and RPS must both improve; calibration error may worsen by at most 0.005",
        },
        "drawRiskDeltaVsTactical": draw_risk_delta,
        "drawRiskAdmissionDecision": {
            "status": "enabled" if draw_risk_enabled else "observation_only",
            "enabled": draw_risk_enabled,
            "rule": "Draw-risk layer must improve Log Loss and RPS versus tactical layer; calibration may worsen by at most 0.005",
        },
        "matches": rows,
    }, status


def apply_tactical_status(profiles: list[dict[str, Any]], status: str) -> None:
    for profile in profiles:
        for match in profile["matches"]:
            tactical = match["tacticalCandidate"]
            tactical["admissionStatus"] = status if tactical.get("labels") else "observation_only"


def build_tournament_availability(
    matches: list[dict[str, Any]],
    squad_status: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    next_fixture: dict[str, dict[str, Any]] = {}
    for fixture in sorted(cached_football_matches(), key=lambda item: str(item.get("utcDate") or "")):
        if fixture.get("status") == "FINISHED":
            continue
        home = localized_team_name(fixture.get("homeTeam", {}))
        away = localized_team_name(fixture.get("awayTeam", {}))
        if home == "待定" or away == "待定":
            continue
        normalized = {
            "fixtureId": fixture.get("id"),
            "utcDate": fixture.get("utcDate"),
            "homeTeam": home,
            "awayTeam": away,
        }
        next_fixture.setdefault(home, normalized)
        next_fixture.setdefault(away, normalized)
    event_sources = {
        (str(event.get("team")), str(event.get("player"))): str(event.get("sourceUrl"))
        for match in matches for event in match.get("events", [])
        if event.get("team") and event.get("player") and event.get("sourceUrl")
    }
    records = []
    for player in squad_status.get("players", []):
        if int(player.get("pendingSuspensions", 0)) <= 0:
            continue
        fixture = next_fixture.get(str(player["team"]))
        if not fixture:
            continue
        records.append({
            "team": player["team"],
            "player": player["player"],
            "target_date": datetime.fromisoformat(str(fixture["utcDate"]).replace("Z", "+00:00"))
            .astimezone(BEIJING).date().isoformat(),
            "target_fixture_id": fixture["fixtureId"],
            "status": "suspended",
            "availability_probability": 0.0,
            "confidence": 1.0,
            "source_url": event_sources.get(
                (str(player["team"]), str(player["player"])),
                FIFA_SCORES_URL,
            ),
            "observed_at": generated_at,
            "note": "本届赛事累计黄牌或红牌规则触发下一场自动停赛",
        })
    for injury in squad_status.get("injuries", []):
        if injury.get("status") != "doubtful":
            continue
        fixture = next_fixture.get(str(injury["team"]))
        if not fixture:
            continue
        records.append({
            "team": injury["team"],
            "player": injury["player"],
            "target_date": datetime.fromisoformat(str(fixture["utcDate"]).replace("Z", "+00:00"))
            .astimezone(BEIJING).date().isoformat(),
            "target_fixture_id": fixture["fixtureId"],
            "status": "doubtful",
            "availability_probability": injury["availabilityProbability"],
            "confidence": injury["confidence"],
            "source_url": injury["sourceUrl"],
            "observed_at": generated_at,
            "note": injury["note"],
        })
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "records": sorted(records, key=lambda item: (item["target_date"], item["team"], item["player"])),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    generated_at = datetime.now(BEIJING).isoformat(timespec="seconds")
    matches = build_match_records(args.offline)
    profiles = build_team_profiles(matches)
    backtest, tactical_status = review_backtest(matches, profiles)
    apply_tactical_status(profiles, tactical_status)
    squad_status = build_squad_status(match for match in matches if match["status"] == "completed")
    tournament_availability = build_tournament_availability(matches, squad_status, generated_at)
    completed = sum(match["status"] == "completed" for match in matches)
    archived = sum(bool(match["events"]) for match in matches)
    timeline_payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {
            "scheduledMatches": 48,
            "completedMatches": completed,
            "pendingMatches": 48 - completed,
            "archivedMinuteByMinuteMatches": archived,
        },
        "sources": {
            "officialResults": FIFA_SCORES_URL,
            "minuteByMinuteProvider": "ESPN match commentary",
            "copyrightPolicy": "structured event coordinates and short factual descriptions; full commentary text is not republished",
        },
        "matches": matches,
    }
    profile_payload = {
        "schemaVersion": 2,
        "generatedAt": generated_at,
        "round": {
            "name": "group_matchdays_1_2",
            "scheduledMatches": 48,
            "completedMatches": completed,
            "teams": len(profiles),
            "matchdayWeights": {"1": 0.45, "2": 0.55},
        },
        "method": {
            "objectiveAndTacticalSeparated": True,
            "objectiveDirectionCap": 0.08,
            "objectiveMultiplier": OBJECTIVE_MULTIPLIER,
            "tacticalDirectionCap": 0.05,
            "combinedTeamDirectionCap": 0.18,
            "tacticalAdmissionStatus": tactical_status,
            "drawRiskLayer": "probability-only redistribution; no xG or score-matrix change",
        },
        "teams": profiles,
    }
    review_payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": timeline_payload["scope"],
        "modelChanges": [
            "matchday two receives 55% and matchday one 45% when both are available",
            "objective result form and tactical event-timeline evidence are separated",
            "cooling-break segments are explicit and tactical deltas are capped at 0.05 xG",
            "injury and cumulative discipline states are auditable",
            "FIFA Article 13 and Annex C knockout paths are implemented",
            "draw-risk layer redistributes at most 0.045 probability into draws when low-tempo or misallocated-upset blind spots trigger",
        ],
        "backtest": backtest,
        "squadStatus": squad_status,
        "dataQuality": {
            "settlementIdentity": "official fixture id; normalized teams and kickoff date fallback",
            "timelineCoverage": archived / max(1, completed),
            "pendingReason": (
                "Group K/L matchday-two fixtures have not finished at generation time"
                if completed < 48 else None
            ),
        },
    }
    write_json(PUBLIC_TIMELINE_PATH, timeline_payload)
    write_json(PROFILE_PATH, profile_payload)
    write_json(AVAILABILITY_PATH, tournament_availability)
    write_json(PUBLIC_REVIEW_PATH, review_payload)
    write_json(ARTIFACT_REVIEW_PATH, review_payload)
    print(
        f"Wrote two-round review: {completed}/48 completed, "
        f"{archived} timelines, tactical={tactical_status}"
    )


if __name__ == "__main__":
    main()
