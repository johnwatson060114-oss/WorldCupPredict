from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.elo_ratings import allocate_total_goals_by_elo
from pipeline.goal_models import PRODUCTION_GOAL_SPEC, _read_historical_matches, fit_goal_model


BEIJING = ZoneInfo("Asia/Shanghai")
BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
CACHE_DIR = ROOT / ".cache" / "pipeline" / "statsbomb-open-data"
PROFILE_PATH = ROOT / "pipeline" / "data" / "historical-group-stage-performance-statsbomb.json"
ARTIFACT_REVIEW_PATH = ROOT / "artifacts" / "historical-group-stage-statsbomb-review.json"
USER_AGENT = "WorldCupPredict/0.1 (historical statsbomb group-stage importer)"
SEASONS = {2018: 3, 2022: 106}
COMPETITION_ID = 43
OBJECTIVE_RELIABILITY = 0.055


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fetch_json(relative_path: str, offline: bool) -> Any:
    cache_path = CACHE_DIR / relative_path.replace("/", "__")
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    if offline:
        raise FileNotFoundError(f"missing cached StatsBomb payload: {relative_path}")
    last_error: requests.RequestException | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                f"{BASE_URL}/{relative_path}",
                headers={"User-Agent": USER_AGENT},
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"could not fetch {relative_path}") from last_error
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def event_name(value: dict[str, Any], path: Iterable[str]) -> str:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    if isinstance(current, dict):
        return str(current.get("name") or "")
    return str(current or "")


def match_sort_key(match: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(match.get("match_date") or ""),
        str(match.get("kick_off") or ""),
        int(match.get("match_id") or 0),
    )


def team_name(match: dict[str, Any], side: str) -> str:
    return str(match[f"{side}_team"][f"{side}_team_name"])


def derive_group_matchdays(matches: list[dict[str, Any]]) -> dict[int, int]:
    appearances: dict[str, int] = defaultdict(int)
    result: dict[int, int] = {}
    for match in sorted(matches, key=match_sort_key):
        home = team_name(match, "home")
        away = team_name(match, "away")
        matchday = max(appearances[home], appearances[away]) + 1
        result[int(match["match_id"])] = min(3, matchday)
        appearances[home] += 1
        appearances[away] += 1
    return result


def empty_team_stats() -> dict[str, Any]:
    return {
        "shots": 0,
        "goals": 0,
        "xg": 0.0,
        "nonPenaltyXg": 0.0,
        "penaltyXg": 0.0,
        "penaltyShots": 0,
        "penaltyGoals": 0,
        "woodwork": 0,
        "redCards": 0,
        "yellowCards": 0,
        "substitutions": 0,
        "keeperGoalsConceded": 0,
        "ownGoalsFor": 0,
        "ownGoalsAgainst": 0,
    }


def collect_team_stats(events: list[dict[str, Any]], teams: tuple[str, str]) -> dict[str, dict[str, Any]]:
    stats = {team: empty_team_stats() for team in teams}
    for event in events:
        team = event_name(event, ("team",))
        if team not in stats:
            continue
        event_type = event_name(event, ("type",))
        if event_type == "Shot":
            shot_type = event_name(event, ("shot", "type"))
            outcome = event_name(event, ("shot", "outcome"))
            xg = float(event.get("shot", {}).get("statsbomb_xg") or 0.0)
            stats[team]["shots"] += 1
            stats[team]["xg"] += xg
            if shot_type == "Penalty":
                stats[team]["penaltyShots"] += 1
                stats[team]["penaltyXg"] += xg
                if outcome == "Goal":
                    stats[team]["penaltyGoals"] += 1
            else:
                stats[team]["nonPenaltyXg"] += xg
            if outcome == "Goal":
                stats[team]["goals"] += 1
            if outcome in {"Post", "Saved to Post"}:
                stats[team]["woodwork"] += 1
        elif event_type == "Substitution":
            stats[team]["substitutions"] += 1
        elif event_type == "Goal Keeper" and event_name(event, ("goalkeeper", "type")) == "Goal Conceded":
            stats[team]["keeperGoalsConceded"] += 1
        elif event_type == "Own Goal For":
            stats[team]["ownGoalsFor"] += 1
        elif event_type == "Own Goal Against":
            stats[team]["ownGoalsAgainst"] += 1

        card = event_name(event, ("bad_behaviour", "card")) or event_name(event, ("foul_committed", "card"))
        if card:
            if card in {"Red Card", "Second Yellow"}:
                stats[team]["redCards"] += 1
            elif card == "Yellow Card":
                stats[team]["yellowCards"] += 1
    return stats


def historical_reference_xg() -> dict[tuple[str, str, str], tuple[float, float]]:
    ordered = sorted(_read_historical_matches(), key=lambda item: item["kickoff_utc"])
    ratings: dict[str, float] = {}
    result: dict[tuple[str, str, str], tuple[float, float]] = {}
    for index, match in enumerate(ordered):
        home = str(match["home_team_id"])
        away = str(match["away_team_id"])
        home_rating = ratings.get(home, 1500.0)
        away_rating = ratings.get(away, 1500.0)
        year = str(match["date"])[:4]
        is_world_cup = match.get("tournament") == "FIFA World Cup" and year in {"2018", "2022"}
        if is_world_cup:
            prior = [row for row in ordered[:index] if int(str(row["date"])[:4]) >= 2000]
            model = fit_goal_model(prior, PRODUCTION_GOAL_SPEC)
            base_home, base_away = model.expected_goals(home, away, bool(match.get("neutral", True)))
            total = base_home + base_away
            result[(str(match["date"]), str(match["home_team"]), str(match["away_team"]))] = (
                *allocate_total_goals_by_elo(total, round(home_rating), round(away_rating)),
            )

        expected = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
        home_goals = int(match["home_goals_90"])
        away_goals = int(match["away_goals_90"])
        actual_points = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        change = 20.0 * (actual_points - expected)
        ratings[home] = home_rating + change
        ratings[away] = away_rating - change
    return result


def lookup_reference_xg(
    reference: dict[tuple[str, str, str], tuple[float, float]],
    match_date: str,
    home: str,
    away: str,
) -> tuple[float, float]:
    direct_key = (match_date, home, away)
    if direct_key in reference:
        return reference[direct_key]
    reversed_key = (match_date, away, home)
    if reversed_key in reference:
        away_xg, home_xg = reference[reversed_key]
        return home_xg, away_xg
    raise KeyError(f"historical xG reference missing for {direct_key}")


def credibility_gate(
    matchday: int,
    goals_for: int,
    goals_against: int,
    expected_for: float,
    stats_for: dict[str, Any],
    stats_against: dict[str, Any],
) -> tuple[float, list[str]]:
    weight = 0.92
    labels: list[str] = []
    xg_for = float(stats_for["nonPenaltyXg"])
    xg_against = float(stats_against["nonPenaltyXg"])
    red_cards = int(stats_for["redCards"]) + int(stats_against["redCards"])
    penalties = int(stats_for["penaltyShots"]) + int(stats_against["penaltyShots"])
    own_goals = int(stats_for["ownGoalsFor"]) + int(stats_for["ownGoalsAgainst"])
    own_goals += int(stats_against["ownGoalsFor"]) + int(stats_against["ownGoalsAgainst"])

    if red_cards:
        weight *= 0.42
        labels.append("red_card_distorted")
    if penalties:
        weight *= 0.68
        labels.append("penalty_distorted")
    if own_goals:
        weight *= 0.62
        labels.append("own_goal_distorted")
    if goals_for + goals_against >= 6 and abs(goals_for - float(stats_for["xg"])) >= 2.0:
        weight *= 0.70
        labels.append("finishing_variance")
    if goals_for > expected_for + 0.75 and xg_for <= xg_against + 0.05:
        weight *= 0.62
        labels.append("score_outpaced_event_quality")
    if goals_for > goals_against and xg_for + 0.25 < xg_against:
        weight *= 0.62
        labels.append("result_against_event_quality")
    if xg_for - xg_against >= 0.45:
        labels.append("xg_quality_edge")
    if xg_for >= expected_for + 0.35:
        labels.append("non_penalty_xg_above_reference")
    if int(stats_for["shots"]) >= int(stats_against["shots"]) + 5 and xg_for > xg_against:
        labels.append("sustained_shot_pressure")
    if matchday == 3:
        weight *= 0.85
        labels.append("third_round_context_reviewed")
    if not labels:
        labels.append("event_quality_supported")
    return round(clamp(weight, 0.0, 1.0), 4), labels


def team_match_profile(
    year: int,
    match: dict[str, Any],
    matchday: int,
    team: str,
    opponent: str,
    stats: dict[str, dict[str, Any]],
    reference_xg: tuple[float, float],
    home_side: bool,
) -> dict[str, Any]:
    goals_for = int(match["home_score"] if home_side else match["away_score"])
    goals_against = int(match["away_score"] if home_side else match["home_score"])
    expected_for, expected_against = reference_xg if home_side else (reference_xg[1], reference_xg[0])
    stats_for = stats[team]
    stats_against = stats[opponent]
    credibility_weight, credibility_labels = credibility_gate(
        matchday,
        goals_for,
        goals_against,
        expected_for,
        stats_for,
        stats_against,
    )
    objective_enabled = credibility_weight >= 0.25 and (
        "xg_quality_edge" in credibility_labels
        or "non_penalty_xg_above_reference" in credibility_labels
        or abs(float(stats_for["nonPenaltyXg"]) - expected_for) >= 0.35
        or abs(float(stats_against["nonPenaltyXg"]) - expected_against) >= 0.35
    )
    reliability = OBJECTIVE_RELIABILITY * credibility_weight
    attack_delta = clamp((float(stats_for["nonPenaltyXg"]) - expected_for) * reliability, -0.08, 0.08)
    defense_delta = clamp((expected_against - float(stats_against["nonPenaltyXg"])) * reliability, -0.08, 0.08)
    return {
        "sourceYear": year,
        "fixtureId": int(match["match_id"]),
        "observedMatchday": matchday,
        "observedDate": str(match["match_date"]),
        "opponent": opponent,
        "scoreFor": goals_for,
        "scoreAgainst": goals_against,
        "expectedGoalsReference": round(expected_for, 4),
        "expectedGoalsAgainstReference": round(expected_against, 4),
        "statsbombXgFor": round(float(stats_for["xg"]), 4),
        "statsbombXgAgainst": round(float(stats_against["xg"]), 4),
        "nonPenaltyXgFor": round(float(stats_for["nonPenaltyXg"]), 4),
        "nonPenaltyXgAgainst": round(float(stats_against["nonPenaltyXg"]), 4),
        "nonPenaltyXgEdge": round(float(stats_for["nonPenaltyXg"]) - float(stats_against["nonPenaltyXg"]), 4),
        "shotCountFor": int(stats_for["shots"]),
        "shotCountAgainst": int(stats_against["shots"]),
        "credibilityWeight": credibility_weight,
        "credibilityLabels": credibility_labels,
        "evidenceConfidence": min(1.0, credibility_weight + 0.06),
        "objectiveForm": {
            "attackDelta": round(attack_delta, 4),
            "defenseDelta": round(defense_delta, 4),
            "redCardAdjusted": "red_card_distorted" in credibility_labels,
            "finishingOutlierShrunk": "finishing_variance" in credibility_labels,
            "opponentStrengthAdjusted": True,
            "admissionStatus": "enabled" if objective_enabled else "observation_only",
            "admissionReason": (
                "statsbomb_non_penalty_xg_supports_direction"
                if objective_enabled else "event_xg_does_not_support_strength_change"
            ),
        },
        "tacticalCandidate": {
            "attackDelta": 0.0,
            "defenseDelta": 0.0,
            "labels": [],
            "corroboration": "statsbomb_event_xg_only",
            "admissionStatus": "observation_only",
        },
        "evidence": {
            "mode": "statsbomb_open_data_events",
            "timelineArchived": True,
            "eventCount": int(match.get("eventCount", 0)),
            "source": "StatsBomb Open Data",
            "license": "https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf",
            "shotSummary": {
                "for": stats_for,
                "against": stats_against,
            },
        },
    }


def build_profiles(offline: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reference = historical_reference_xg()
    match_records: list[dict[str, Any]] = []
    by_team: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for year, season_id in SEASONS.items():
        matches = fetch_json(f"matches/{COMPETITION_ID}/{season_id}.json", offline)
        group_matches = [
            match for match in matches
            if event_name(match, ("competition_stage",)) == "Group Stage"
        ]
        matchdays = derive_group_matchdays(group_matches)
        for match in sorted(group_matches, key=match_sort_key):
            home = team_name(match, "home")
            away = team_name(match, "away")
            reference_xg = lookup_reference_xg(reference, str(match["match_date"]), home, away)
            events = fetch_json(f"events/{match['match_id']}.json", offline)
            match["eventCount"] = len(events)
            stats = collect_team_stats(events, (home, away))
            matchday = matchdays[int(match["match_id"])]
            match_records.append({
                "year": year,
                "fixtureId": int(match["match_id"]),
                "matchday": matchday,
                "matchDate": str(match["match_date"]),
                "homeTeam": home,
                "awayTeam": away,
                "score": {"home": int(match["home_score"]), "away": int(match["away_score"])},
                "eventCount": len(events),
                "sources": [
                    {
                        "type": "event_data",
                        "provider": "StatsBomb Open Data",
                        "url": f"{BASE_URL}/events/{match['match_id']}.json",
                    },
                ],
            })
            home_profile = team_match_profile(year, match, matchday, home, away, stats, reference_xg, True)
            away_profile = team_match_profile(year, match, matchday, away, home, stats, reference_xg, False)
            by_team[(year, home)].append(home_profile)
            by_team[(year, away)].append(away_profile)

    profiles: list[dict[str, Any]] = []
    for (year, team), team_matches in sorted(by_team.items()):
        team_matches.sort(key=lambda item: (item["observedDate"], item["fixtureId"]))
        labels = [label for item in team_matches for label in item.get("credibilityLabels", [])]
        profiles.append({
            "year": year,
            "team": team,
            "summary": f"{team} {year} group-stage profile uses StatsBomb event xG only when evidence supports the signal.",
            "matches": team_matches,
            "evidence": {
                "mode": "statsbomb_open_data_events",
                "archivedMatches": len(team_matches),
                "credibilityLabels": sorted(set(labels)),
                "objectiveAndTacticalSeparated": True,
                "scoreResidualsDoNotDirectlyChangeXg": True,
            },
        })
    return profiles, match_records


def review_payload(profiles: list[dict[str, Any]], matches: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    team_matches = [item for profile in profiles for item in profile["matches"]]
    label_counts = Counter(label for item in team_matches for label in item.get("credibilityLabels", []))
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scope": {
            "competition": "FIFA World Cup",
            "years": sorted(SEASONS),
            "groupStageMatches": len(matches),
            "teamProfiles": len(profiles),
            "teamMatchProfiles": len(team_matches),
            "archivedEventMatches": sum(1 for match in matches if match.get("eventCount", 0) > 0),
        },
        "method": {
            "policy": "historical_statsbomb_group_stage_xg_v1",
            "predictionTarget": "90_minutes",
            "objectiveAdmissionRule": "non-penalty StatsBomb xG must support the direction; score residuals alone never enter",
            "distortionLabels": [
                "red_card_distorted",
                "penalty_distorted",
                "own_goal_distorted",
                "finishing_variance",
                "score_outpaced_event_quality",
                "result_against_event_quality",
                "third_round_context_reviewed",
            ],
            "objectiveReliability": OBJECTIVE_RELIABILITY,
        },
        "admissionSummary": {
            "objectiveEnabled": sum(item["objectiveForm"]["admissionStatus"] == "enabled" for item in team_matches),
            "tacticalEnabled": 0,
            "credibilityLabelCounts": dict(sorted(label_counts.items())),
        },
        "sources": {
            "eventProvider": "StatsBomb Open Data",
            "eventRepository": "https://github.com/statsbomb/open-data",
            "license": "https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf",
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
    profiles, matches = build_profiles(args.offline)
    review = review_payload(profiles, matches, generated_at)
    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "round": {
            "name": "historical_group_stage_matchdays_1_2_3",
            "competition": "FIFA World Cup",
            "years": sorted(SEASONS),
            "scheduledMatches": len(matches),
            "completedMatches": len(matches),
            "teams": len(profiles),
            "matchdayWeights": {"1": 0.25, "2": 0.35, "3": 0.40},
        },
        "method": review["method"],
        "sources": review["sources"],
        "teams": profiles,
    }
    write_json(PROFILE_PATH, payload)
    write_json(ARTIFACT_REVIEW_PATH, review)
    print(
        "Wrote historical group-stage StatsBomb review: "
        f"{review['scope']['groupStageMatches']} group matches, "
        f"{review['scope']['teamProfiles']} team profiles, "
        f"objective enabled {review['admissionSummary']['objectiveEnabled']}"
    )


if __name__ == "__main__":
    main()
