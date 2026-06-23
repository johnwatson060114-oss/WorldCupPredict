from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from .config import ROOT
from .football_data import localized_team_name, parse_utc
from .simulation import rank_group
from .tournament_rules import ThirdPlaceRow, knockout_opponent_slots, rank_best_thirds


MOTIVATION_XG = {
    "secured_first": (-0.045, -0.030),
    "secured_top_two": (-0.035, -0.025),
    "draw_advances": (-0.015, 0.015),
    "competitive": (0.015, 0.000),
    "must_win": (0.045, -0.020),
    "goal_difference_chase": (0.055, -0.030),
    "eliminated": (-0.025, -0.020),
}
RESULT_FORM_MAX_XG = 0.06
TIMELINE_PATH = ROOT / "public" / "data" / "two-round-match-timelines.json"


@dataclass
class Standing:
    played: int = 0
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "played": self.played,
            "points": self.points,
            "goalsFor": self.goals_for,
            "goalsAgainst": self.goals_against,
            "goalDifference": self.goals_for - self.goals_against,
        }


def _fixture_group(seed: dict[str, Any], matches: list[dict[str, Any]]) -> str | None:
    kickoff = datetime.fromisoformat(str(seed["kickoff"]))
    for match in matches:
        home = localized_team_name(match.get("homeTeam", {}))
        away = localized_team_name(match.get("awayTeam", {}))
        if home != seed["home_team"] or away != seed["away_team"]:
            continue
        match_kickoff = parse_utc(match["utcDate"]).astimezone(kickoff.tzinfo)
        if match_kickoff.date() == kickoff.date():
            return match.get("group")
    return None


def standings_before(
    matches: list[dict[str, Any]],
    group: str,
    cutoff: datetime,
) -> dict[str, Standing]:
    table: dict[str, Standing] = {}
    cutoff_utc = cutoff.astimezone(UTC)
    for match in matches:
        if match.get("status") != "FINISHED" or match.get("group") != group:
            continue
        if parse_utc(match["utcDate"]) >= cutoff_utc:
            continue
        home = localized_team_name(match["homeTeam"])
        away = localized_team_name(match["awayTeam"])
        home_score = int(match["score"]["fullTime"]["home"])
        away_score = int(match["score"]["fullTime"]["away"])
        home_state = table.setdefault(home, Standing())
        away_state = table.setdefault(away, Standing())
        home_state.played += 1
        away_state.played += 1
        home_state.goals_for += home_score
        home_state.goals_against += away_score
        away_state.goals_for += away_score
        away_state.goals_against += home_score
        if home_score > away_score:
            home_state.points += 3
        elif home_score < away_score:
            away_state.points += 3
        else:
            home_state.points += 1
            away_state.points += 1
    return table


def motivation_state(standing: Standing) -> str:
    """Legacy points-only fallback used when the group fixture graph is incomplete."""
    if standing.played < 2:
        return "not_active"
    if standing.points >= 6:
        return "secured_top_two"
    if standing.points == 4:
        return "draw_advances"
    if standing.points == 0:
        return "must_win"
    return "competitive"


@lru_cache(maxsize=1)
def _timeline_conduct_index(path: str = str(TIMELINE_PATH)) -> dict[str, dict[str, int]]:
    source = Path(path)
    if not source.exists():
        return {}
    payload = json.loads(source.read_text(encoding="utf-8"))
    result: dict[str, dict[str, int]] = {}
    for match in payload.get("matches", []):
        conduct: dict[str, int] = {}
        by_player: dict[tuple[str, str], list[str]] = {}
        for event in match.get("events", []):
            team = str(event.get("team") or "")
            player = str(event.get("player") or "")
            if team and player and event.get("type") in {"yellow_card", "second_yellow", "red_card"}:
                by_player.setdefault((team, player), []).append(str(event["type"]))
        for (team, _player), event_types in by_player.items():
            if "red_card" in event_types:
                deduction = -5 if "yellow_card" in event_types else -4
            elif "second_yellow" in event_types or event_types.count("yellow_card") >= 2:
                deduction = -3
            else:
                deduction = -1
            conduct[team] = conduct.get(team, 0) + deduction
        result[str(match.get("fixtureId"))] = conduct
    return result


def _result_row(match: dict[str, Any], home_goals: int, away_goals: int) -> dict[str, Any]:
    return {
        "home": localized_team_name(match["homeTeam"]),
        "away": localized_team_name(match["awayTeam"]),
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "conduct": match.get("conduct") or _timeline_conduct_index().get(str(match.get("id")), {}),
    }


def best_third_snapshot(
    matches: list[dict[str, Any]],
    cutoff: datetime,
) -> list[dict[str, Any]]:
    rows: list[ThirdPlaceRow] = []
    cutoff_utc = cutoff.astimezone(UTC)
    for group in sorted({str(match.get("group")) for match in matches if match.get("group")}):
        group_matches = [
            match for match in matches
            if match.get("group") == group
            and match.get("status") == "FINISHED"
            and parse_utc(match["utcDate"]) < cutoff_utc
        ]
        teams = sorted({
            localized_team_name(match[side])
            for match in matches if match.get("group") == group
            for side in ("homeTeam", "awayTeam")
        })
        if len(group_matches) < 4 or len(teams) != 4:
            continue
        results = [
            _result_row(
                match,
                int(match["score"]["fullTime"]["home"]),
                int(match["score"]["fullTime"]["away"]),
            )
            for match in group_matches
        ]
        ranking = rank_group(teams, results)
        third = ranking[2]
        standing = standings_before(matches, group, cutoff).get(third, Standing())
        conduct = sum(int(result.get("conduct", {}).get(third, 0)) for result in results)
        rows.append(ThirdPlaceRow(
            group=group.replace("GROUP_", ""),
            team=third,
            points=standing.points,
            goal_difference=standing.goals_for - standing.goals_against,
            goals_for=standing.goals_for,
            conduct=conduct,
        ))
    return [
        {
            "rank": index,
            "group": row.group,
            "team": row.team,
            "points": row.points,
            "goalDifference": row.goal_difference,
            "goalsFor": row.goals_for,
            "conduct": row.conduct,
            "currentlyQualifying": index <= 8,
        }
        for index, row in enumerate(rank_best_thirds(rows), start=1)
    ]


def group_scenarios(
    matches: list[dict[str, Any]],
    group: str,
    cutoff: datetime,
    team: str,
    max_goals: int = 4,
) -> dict[str, Any] | None:
    completed = [
        match for match in matches
        if match.get("group") == group
        and match.get("status") == "FINISHED"
        and parse_utc(match["utcDate"]) < cutoff.astimezone(UTC)
    ]
    remaining = [
        match for match in matches
        if match.get("group") == group
        and match.get("status") != "FINISHED"
        and parse_utc(match["utcDate"]) >= cutoff.astimezone(UTC)
    ]
    teams = sorted({
        localized_team_name(match[side])
        for match in matches if match.get("group") == group
        for side in ("homeTeam", "awayTeam")
    })
    if len(teams) != 4 or team not in teams or not 1 <= len(remaining) <= 2:
        return None
    base_results = [
        _result_row(
            match,
            int(match["score"]["fullTime"]["home"]),
            int(match["score"]["fullTime"]["away"]),
        )
        for match in completed
    ]
    current = next((
        match for match in remaining
        if team in {localized_team_name(match["homeTeam"]), localized_team_name(match["awayTeam"])}
    ), None)
    if current is None:
        return None
    ranks: list[int] = []
    by_current_outcome: dict[str, list[int]] = {"win": [], "draw": [], "loss": []}
    margins_for_top_two: list[int] = []
    score_values = range(max_goals + 1)
    if len(remaining) == 1:
        score_pairs = [((home, away),) for home in score_values for away in score_values]
    else:
        score_pairs = [
            ((home_a, away_a), (home_b, away_b))
            for home_a in score_values for away_a in score_values
            for home_b in score_values for away_b in score_values
        ]
    for scores in score_pairs:
        simulated = list(base_results)
        current_result: tuple[int, int] | None = None
        for match, (home_goals, away_goals) in zip(remaining, scores, strict=True):
            simulated.append(_result_row(match, home_goals, away_goals))
            if match is current:
                current_result = (home_goals, away_goals)
        ranking = rank_group(teams, simulated)
        rank = ranking.index(team) + 1
        ranks.append(rank)
        if current_result is None:
            continue
        home_name = localized_team_name(current["homeTeam"])
        own_goals, opponent_goals = (
            current_result if home_name == team else (current_result[1], current_result[0])
        )
        outcome = "win" if own_goals > opponent_goals else "draw" if own_goals == opponent_goals else "loss"
        by_current_outcome[outcome].append(rank)
        if rank <= 2:
            margins_for_top_two.append(own_goals - opponent_goals)
    if not ranks:
        return None
    draw_ranks = by_current_outcome["draw"]
    win_ranks = by_current_outcome["win"]
    loss_ranks = by_current_outcome["loss"]
    top_two_share = sum(rank <= 2 for rank in ranks) / len(ranks)
    third_share = sum(rank == 3 for rank in ranks) / len(ranks)
    if max(ranks) == 1:
        state = "secured_first"
    elif max(ranks) <= 2:
        state = "secured_top_two"
    elif min(ranks) == 4:
        state = "eliminated"
    elif draw_ranks and all(rank <= 3 for rank in draw_ranks):
        state = "draw_advances"
    elif win_ranks and not any(rank <= 3 for rank in draw_ranks + loss_ranks):
        state = "must_win"
    elif win_ranks and any(rank > 2 for rank in win_ranks):
        state = "goal_difference_chase"
    else:
        state = "competitive"
    return {
        "state": state,
        "positionRange": [min(ranks), max(ranks)],
        "topTwoScenarioShare": round(top_two_share, 4),
        "thirdScenarioShare": round(third_share, 4),
        "minimumTopTwoGoalMargin": min(margins_for_top_two) if margins_for_top_two else None,
        "scenarioCount": len(ranks),
        "rotationCandidate": state in {"secured_first", "secured_top_two"},
        "firstPlacePathIncentive": min(ranks) == 1 and max(ranks) > 1,
    }


def late_scoreboard_pressure(
    motivation: str,
    own_margin: int,
    parallel_result_helps: bool,
) -> dict[str, float]:
    if motivation == "goal_difference_chase" and own_margin <= 1:
        return {"attackMultiplier": 1.15, "defensiveRiskMultiplier": 1.10}
    if motivation == "must_win" and own_margin <= 0:
        return {"attackMultiplier": 1.12, "defensiveRiskMultiplier": 1.08}
    if motivation == "draw_advances" and own_margin == 0 and parallel_result_helps:
        return {"attackMultiplier": 0.92, "defensiveRiskMultiplier": 0.95}
    if motivation in {"secured_first", "secured_top_two"}:
        return {"attackMultiplier": 0.94, "defensiveRiskMultiplier": 0.96}
    return {"attackMultiplier": 1.0, "defensiveRiskMultiplier": 1.0}


def _tournament_goal_average(matches: list[dict[str, Any]], cutoff: datetime) -> float:
    finished = [
        match for match in matches
        if match.get("status") == "FINISHED" and parse_utc(match["utcDate"]) < cutoff.astimezone(UTC)
    ]
    if not finished:
        return 1.40
    total_goals = sum(
        int(match["score"]["fullTime"]["home"]) + int(match["score"]["fullTime"]["away"])
        for match in finished
    )
    return total_goals / (2 * len(finished))


def result_form_adjustment(standing: Standing, goal_average: float) -> tuple[float, float]:
    if standing.played < 2:
        return 0.0, 0.0
    reliability = standing.played / (standing.played + 2)
    goals_for_per_match = standing.goals_for / standing.played
    goals_against_per_match = standing.goals_against / standing.played
    attack = (goals_for_per_match - goal_average) * 0.08 * reliability
    defense = (goal_average - goals_against_per_match) * 0.08 * reliability
    return (
        max(-RESULT_FORM_MAX_XG, min(RESULT_FORM_MAX_XG, attack)),
        max(-RESULT_FORM_MAX_XG, min(RESULT_FORM_MAX_XG, defense)),
    )


def apply_current_tournament_context(
    seeds: list[dict[str, Any]],
    matches: list[dict[str, Any]] | None,
) -> None:
    """Apply a bounded motivation adjustment only from group matchday three."""

    if not matches:
        return
    for seed in seeds:
        group = seed.get("group") or _fixture_group(seed, matches)
        if not group:
            continue
        kickoff = datetime.fromisoformat(str(seed["kickoff"]))
        table = standings_before(matches, group, kickoff)
        home = table.get(str(seed["home_team"]), Standing())
        away = table.get(str(seed["away_team"]), Standing())
        home_scenarios = group_scenarios(matches, group, kickoff, str(seed["home_team"]))
        away_scenarios = group_scenarios(matches, group, kickoff, str(seed["away_team"]))
        home_state = home_scenarios["state"] if home_scenarios else motivation_state(home)
        away_state = away_scenarios["state"] if away_scenarios else motivation_state(away)
        goal_average = _tournament_goal_average(matches, kickoff)
        third_snapshot = best_third_snapshot(matches, kickoff)
        home_result_attack, home_result_defense = result_form_adjustment(home, goal_average)
        away_result_attack, away_result_defense = result_form_adjustment(away, goal_average)
        motivation_active = home_state in MOTIVATION_XG or away_state in MOTIVATION_XG
        result_form_active = any(
            abs(value) > 1e-12
            for value in (
                home_result_attack,
                home_result_defense,
                away_result_attack,
                away_result_defense,
            )
        )
        applied = motivation_active or result_form_active
        seed["group"] = group
        seed["current_tournament"] = {
            "group": group,
            "homeStanding": home.to_dict(),
            "awayStanding": away.to_dict(),
            "homeMotivation": home_state,
            "awayMotivation": away_state,
            "homeScenarios": home_scenarios,
            "awayScenarios": away_scenarios,
            "bestThirdSnapshot": third_snapshot,
            "homeKnockoutPaths": {
                str(position): knockout_opponent_slots(group, position)
                for position in range(1, 4)
            },
            "awayKnockoutPaths": {
                str(position): knockout_opponent_slots(group, position)
                for position in range(1, 4)
            },
            "homeLatePressure": late_scoreboard_pressure(home_state, 0, True),
            "awayLatePressure": late_scoreboard_pressure(away_state, 0, True),
            "tournamentGoalsPerTeamMatch": round(goal_average, 4),
            "homeResultForm": {
                "attackDelta": round(home_result_attack, 4),
                "defenseDelta": round(home_result_defense, 4),
            },
            "awayResultForm": {
                "attackDelta": round(away_result_attack, 4),
                "defenseDelta": round(away_result_defense, 4),
            },
            "policy": "matchday_three_scenarios_annex_c_v2",
            "applied": applied,
        }
        if not applied:
            continue

        home_motivation_attack, home_motivation_defense = MOTIVATION_XG.get(home_state, (0.0, 0.0))
        away_motivation_attack, away_motivation_defense = MOTIVATION_XG.get(away_state, (0.0, 0.0))
        home_attack = home_motivation_attack + home_result_attack
        home_defense = home_motivation_defense + home_result_defense
        away_attack = away_motivation_attack + away_result_attack
        away_defense = away_motivation_defense + away_result_defense
        base_home, base_away = map(float, seed["base_xg"])
        home_net = home_attack - away_defense
        away_net = away_attack - home_defense
        adjusted_home = max(0.15, base_home + home_net)
        adjusted_away = max(0.15, base_away + away_net)
        seed["base_xg"] = [adjusted_home, adjusted_away]
        seed["coverage"] = max(0.0, float(seed.get("coverage", 0.70)) - 0.02)
        seed["model_decomposition"] = {
            **seed.get("model_decomposition", {}),
            "preMotivationExpectedGoals": {
                "home": round(base_home, 4),
                "away": round(base_away, 4),
            },
            "motivationNet": {"home": round(home_net, 4), "away": round(away_net, 4)},
            "adjustedExpectedGoals": {
                "home": round(adjusted_home, 4),
                "away": round(adjusted_away, 4),
            },
            "motivationLayer": "matchday_three_bounded_v1",
        }
