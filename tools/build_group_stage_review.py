from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.elo_ratings import allocate_total_goals_by_elo
from pipeline.football_data import localized_team_name
from pipeline.match_timeline import (
    ATTACKING_EVENT_TYPES,
    DISTORTION_EVENT_TYPES,
    extract_timeline,
    match_tactical_summary,
    tactical_direction,
)


BEIJING = ZoneInfo("Asia/Shanghai")
FOOTBALL_CACHE = ROOT / ".cache" / "pipeline" / "football-data" / "97a7f68839a6f94960f7d194.json"
ESPN_CACHE = ROOT / ".cache" / "pipeline" / "espn-world-cup"
ELO_NAMES_PATH = ROOT / ".cache" / "pipeline" / "elo-ratings" / "aba55e5bf5205a63dbcaec83.json"
ELO_WORLD_PATH = ROOT / ".cache" / "pipeline" / "elo-ratings" / "c07c64ce7cea930c8b40dd29.json"
PROFILE_PATH = ROOT / "pipeline" / "data" / "group-stage-performance.json"
PUBLIC_TIMELINE_PATH = ROOT / "public" / "data" / "group-stage-match-timelines.json"
PUBLIC_REVIEW_PATH = ROOT / "public" / "data" / "group-stage-model-review.json"
ARTIFACT_REVIEW_PATH = ROOT / "artifacts" / "group-stage-model-review.json"
FIFA_SCORES_URL = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
USER_AGENT = "WorldCupPredict/0.1 (group-stage event-gated importer)"
OBJECTIVE_MULTIPLIER = 1.5
PRESSURE_EVENT_TYPES = ATTACKING_EVENT_TYPES - DISTORTION_EVENT_TYPES
PSEUDO_XG_WEIGHTS = {
    "goal": 0.10,
    "chance_saved": 0.11,
    "chance_missed": 0.06,
    "chance_blocked": 0.04,
    "woodwork": 0.18,
    # These events explain the score but should not be treated as proof of
    # open-play attacking strength.
    "penalty_goal": 0.0,
    "penalty_event": 0.0,
    "own_goal": 0.0,
    "keeper_error": 0.0,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cached_football_matches() -> list[dict[str, Any]]:
    payload = json.loads(FOOTBALL_CACHE.read_text(encoding="utf-8"))
    value = payload.get("value", payload)
    return list(value.get("matches", []))


def cached_elo_ratings() -> dict[str, int]:
    if not ELO_NAMES_PATH.exists() or not ELO_WORLD_PATH.exists():
        return {}
    names_payload = json.loads(ELO_NAMES_PATH.read_text(encoding="utf-8"))["value"]
    world_payload = json.loads(ELO_WORLD_PATH.read_text(encoding="utf-8"))["value"]
    names: dict[str, str] = {}
    for line in names_payload.splitlines():
        columns = line.split("\t")
        if len(columns) >= 2:
            names[columns[0]] = columns[1]
    ratings: dict[str, int] = {}
    for line in world_payload.splitlines():
        columns = line.split("\t")
        if len(columns) >= 4 and columns[3].isdigit():
            name = names.get(columns[2])
            if name:
                ratings[name] = int(columns[3])
    return ratings


def fetch_json(url: str, params: dict[str, Any], cache_path: Path, offline: bool) -> dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    if offline:
        return {}
    try:
        response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return {}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def group_matchday_map(fixtures: list[dict[str, Any]]) -> dict[Any, int]:
    result: dict[Any, int] = {}
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fixture in fixtures:
        group = fixture.get("group")
        if group:
            by_group[str(group)].append(fixture)
    for group_fixtures in by_group.values():
        ordered = sorted(group_fixtures, key=lambda item: str(item.get("utcDate") or ""))
        for index, fixture in enumerate(ordered):
            result[fixture.get("id")] = min(3, index // 2 + 1)
    return result


def espn_event_index(offline: bool) -> dict[tuple[str, str], dict[str, Any]]:
    scoreboard = fetch_json(
        ESPN_SCOREBOARD_URL,
        {"dates": "20260611-20260628", "limit": 100},
        ESPN_CACHE / "scoreboard-20260611-20260628.json",
        offline,
    )
    result: dict[tuple[str, str], dict[str, Any]] = {}
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
    localized_names: tuple[str, str],
) -> list[dict[str, Any]]:
    translation = dict(zip(english_names, localized_names, strict=True))
    return [
        {**event, "team": translation.get(event.get("team"), event.get("team"))}
        for event in events
    ]


def build_match_records(offline: bool) -> list[dict[str, Any]]:
    official = [match for match in cached_football_matches() if match.get("group")]
    official.sort(key=lambda item: str(item.get("utcDate") or ""))
    matchdays = group_matchday_map(official)
    espn = espn_event_index(offline)
    records: list[dict[str, Any]] = []
    for fixture in official:
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
            "coverage": {
                "classifiedEvents": 0,
                "attackingEvents": 0,
                "injuryEvents": 0,
                "cardEvents": 0,
                "distortionEvents": 0,
            },
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
                "coverage": {
                    **raw_summary.get("coverage", {}),
                    "distortionEvents": sum(event.get("type") in DISTORTION_EVENT_TYPES for event in raw_events),
                },
                "teams": {
                    home_zh: raw_summary["teams"].get(home_en, {}),
                    away_zh: raw_summary["teams"].get(away_en, {}),
                },
            }
        records.append({
            "fixtureId": fixture.get("id"),
            "matchday": matchdays.get(fixture.get("id"), 0),
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


def _team_event_count(match: dict[str, Any], team: str, event_types: set[str]) -> int:
    return sum(
        event.get("team") == team and event.get("type") in event_types
        for event in match.get("events", [])
    )


def _team_pseudo_xg(match: dict[str, Any], team: str) -> float:
    return sum(
        PSEUDO_XG_WEIGHTS.get(str(event.get("type")), 0.0)
        for event in match.get("events", [])
        if event.get("team") == team
    )


def credibility_gate(
    match: dict[str, Any],
    team: str,
    opponent: str,
    goals_for: int,
    goals_against: int,
    expected_for: float,
    pseudo_xg_for: float,
    pseudo_xg_against: float,
) -> tuple[float, list[str]]:
    events = match.get("events", [])
    if not events:
        return 0.0, ["missing_commentary"]
    weight = 0.78
    labels: list[str] = []
    team_pressure = _team_event_count(match, team, PRESSURE_EVENT_TYPES)
    opponent_pressure = _team_event_count(match, opponent, PRESSURE_EVENT_TYPES)
    red_cards = sum(event.get("type") in {"red_card", "second_yellow"} for event in events)
    distortions = sum(event.get("type") in DISTORTION_EVENT_TYPES for event in events)

    if red_cards:
        weight *= 0.35
        labels.append("red_card_distorted")
    if distortions:
        weight *= 0.55
        labels.append("penalty_own_goal_or_keeper_error_distorted")
    if goals_for + goals_against >= 6 or abs(goals_for - expected_for) >= 3:
        weight *= 0.55
        labels.append("finishing_variance")
    if goals_for > expected_for + 0.75 and team_pressure <= opponent_pressure:
        weight *= 0.55
        labels.append("score_outpaced_event_pressure")
    if goals_for > goals_against and pseudo_xg_for + 0.10 < pseudo_xg_against:
        weight *= 0.60
        labels.append("result_against_event_quality")
    if pseudo_xg_for - pseudo_xg_against >= 0.25:
        labels.append("pseudo_xg_pressure_edge")
    if match.get("matchday") == 3:
        weight *= 0.75
        labels.append("third_round_context_reviewed")
    if team_pressure >= opponent_pressure + 3 and team_pressure >= 5:
        labels.append("sustained_pressure")
    if team_pressure <= 1 and goals_for >= 2:
        labels.append("low_event_conversion")
    if not labels:
        labels.append("commentary_supported")
    return round(clamp(weight, 0.0, 1.0), 4), labels


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
    pseudo_xg_for = _team_pseudo_xg(match, team)
    pseudo_xg_against = _team_pseudo_xg(match, opponent)
    credibility_weight, credibility_labels = credibility_gate(
        match,
        team,
        opponent,
        goals_for,
        goals_against,
        expected_for,
        pseudo_xg_for,
        pseudo_xg_against,
    )
    objective_enabled = credibility_weight >= 0.25 and (
        "pseudo_xg_pressure_edge" in credibility_labels
        or pseudo_xg_for >= expected_for + 0.15
        or pseudo_xg_against <= expected_against - 0.15
    )
    objective_reliability = 0.055 * credibility_weight
    attack_delta = clamp((pseudo_xg_for - expected_for) * objective_reliability, -0.08, 0.08)
    defense_delta = clamp((expected_against - pseudo_xg_against) * objective_reliability, -0.08, 0.08)
    labels = list(match["tacticalSummary"].get("teams", {}).get(team, {}).get("labels", []))
    opponent_labels = list(match["tacticalSummary"].get("teams", {}).get(opponent, {}).get("labels", []))
    tactical_attack, _ = tactical_direction(labels)
    opponent_attack, _ = tactical_direction(opponent_labels)
    tactical_defense = clamp(-opponent_attack * 0.5, -0.05, 0.05)
    tactical_enabled = credibility_weight >= 0.25 and bool(labels)
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
        "pseudoXgFor": round(pseudo_xg_for, 4),
        "pseudoXgAgainst": round(pseudo_xg_against, 4),
        "pseudoXgEdge": round(pseudo_xg_for - pseudo_xg_against, 4),
        "credibilityWeight": credibility_weight,
        "credibilityLabels": credibility_labels,
        "evidenceConfidence": min(1.0, credibility_weight + 0.10 if match["events"] else 0.0),
        "objectiveForm": {
            "attackDelta": round(attack_delta, 4),
            "defenseDelta": round(defense_delta, 4),
            "redCardAdjusted": "red_card_distorted" in credibility_labels,
            "finishingOutlierShrunk": "finishing_variance" in credibility_labels,
            "opponentStrengthAdjusted": True,
            "admissionStatus": "enabled" if objective_enabled else "observation_only",
            "admissionReason": (
                "pseudo_xg_event_quality_supports_direction"
                if objective_enabled else "score_result_not_sufficient_without_event_support"
            ),
        },
        "tacticalCandidate": {
            "attackDelta": round(tactical_attack, 4),
            "defenseDelta": round(tactical_defense, 4),
            "labels": labels,
            "corroboration": "minute_coordinates_plus_event_count_shift" if labels else "insufficient",
            "admissionStatus": "enabled" if tactical_enabled else "observation_only",
        },
        "evidence": {
            "timelineArchived": bool(match["events"]),
            "eventCount": len(match["events"]),
            "teamPressureEvents": _team_event_count(match, team, PRESSURE_EVENT_TYPES),
            "opponentPressureEvents": _team_event_count(match, opponent, PRESSURE_EVENT_TYPES),
            "pseudoXgWeights": PSEUDO_XG_WEIGHTS,
            "coolingBreakMinutes": match["tacticalSummary"].get("coolingBreakMinutes", []),
            "sources": match["sources"],
        },
    }


def build_team_profiles(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ratings_en = cached_elo_ratings()
    ratings = {
        localized_team_name(team): ratings_en.get(str(team.get("name")), 1500)
        for fixture in cached_football_matches()
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
        credibility_labels = [
            label for match in team_matches for label in match.get("credibilityLabels", [])
        ]
        tactical_labels = [
            label for match in team_matches for label in match["tacticalCandidate"].get("labels", [])
        ]
        profiles.append({
            "team": team,
            "summary": f"{team} group-stage profile is admitted only when commentary events support the signal.",
            "matches": team_matches,
            "evidence": {
                "mode": "minute_by_minute_events",
                "archivedMatches": sum(match["evidence"]["timelineArchived"] for match in team_matches),
                "credibilityLabels": sorted(set(credibility_labels)),
                "tacticalLabels": tactical_labels,
                "objectiveAndTacticalSeparated": True,
                "scoreResidualsDoNotDirectlyChangeXg": True,
            },
        })
    return profiles


def review_payload(matches: list[dict[str, Any]], profiles: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    completed = sum(match["status"] == "completed" for match in matches)
    archived = sum(bool(match["events"]) for match in matches)
    match_profiles = [item for profile in profiles for item in profile["matches"]]
    credibility_counts = Counter(
        label for item in match_profiles for label in item.get("credibilityLabels", [])
    )
    objective_enabled = sum(item["objectiveForm"]["admissionStatus"] == "enabled" for item in match_profiles)
    tactical_enabled = sum(item["tacticalCandidate"]["admissionStatus"] == "enabled" for item in match_profiles)
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {
            "scheduledGroupMatches": len(matches),
            "completedGroupMatches": completed,
            "archivedMinuteByMinuteMatches": archived,
            "teams": len(profiles),
        },
        "method": {
            "policy": "group_stage_commentary_gated_v1",
            "predictionTarget": "90_minutes",
            "scoreResidualsDirectlyAdjustStrength": False,
            "objectiveAdmissionRule": "event-quality pseudo-xG must support the direction; the score alone is never sufficient",
            "pseudoXgPolicy": "shot-like commentary events are converted to conservative pseudo-xG; penalties, own goals and keeper errors are distortion evidence only",
            "distortionLabels": [
                "red_card_distorted",
                "penalty_own_goal_or_keeper_error_distorted",
                "finishing_variance",
                "score_outpaced_event_pressure",
                "result_against_event_quality",
                "third_round_context_reviewed",
            ],
            "matchdayWeights": {"1": 0.25, "2": 0.35, "3": 0.40},
            "objectiveMultiplier": OBJECTIVE_MULTIPLIER,
            "tacticalDirectionCap": 0.05,
            "combinedTeamDirectionCap": 0.18,
        },
        "admissionSummary": {
            "teamMatchProfiles": len(match_profiles),
            "objectiveEnabled": objective_enabled,
            "tacticalEnabled": tactical_enabled,
            "coverage": archived / max(1, completed),
            "credibilityLabelCounts": dict(sorted(credibility_counts.items())),
        },
        "sources": {
            "officialResults": FIFA_SCORES_URL,
            "minuteByMinuteProvider": "ESPN match commentary",
            "copyrightPolicy": "structured event coordinates and short factual summaries only",
        },
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
    review = review_payload(matches, profiles, generated_at)
    profile_payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "round": {
            "name": "group_stage_matchdays_1_2_3",
            "scheduledMatches": len(matches),
            "completedMatches": review["scope"]["completedGroupMatches"],
            "teams": len(profiles),
            "matchdayWeights": {"1": 0.25, "2": 0.35, "3": 0.40},
        },
        "method": review["method"],
        "teams": profiles,
    }
    timeline_payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": review["scope"],
        "sources": review["sources"],
        "matches": matches,
    }
    write_json(PROFILE_PATH, profile_payload)
    write_json(PUBLIC_TIMELINE_PATH, timeline_payload)
    write_json(PUBLIC_REVIEW_PATH, review)
    write_json(ARTIFACT_REVIEW_PATH, review)
    print(
        "Wrote group-stage review: "
        f"{review['scope']['completedGroupMatches']}/{review['scope']['scheduledGroupMatches']} completed, "
        f"{review['scope']['archivedMinuteByMinuteMatches']} timelines, "
        f"objective enabled {review['admissionSummary']['objectiveEnabled']} profiles"
    )


if __name__ == "__main__":
    main()
