from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .football_data import localized_team_name, parse_utc


MOTIVATION_XG = {
    "secured": (-0.035, -0.025),
    "strong_position": (-0.010, 0.000),
    "competitive": (0.015, 0.000),
    "high_risk": (0.030, -0.010),
    "must_win": (0.045, -0.020),
}
RESULT_FORM_MAX_XG = 0.06


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
    if standing.played < 2:
        return "not_active"
    if standing.points >= 6:
        return "secured"
    if standing.points == 4:
        return "strong_position"
    if standing.points == 0:
        return "must_win"
    if standing.points == 1:
        return "high_risk"
    return "competitive"


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
        home_state = motivation_state(home)
        away_state = motivation_state(away)
        goal_average = _tournament_goal_average(matches, kickoff)
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
            "tournamentGoalsPerTeamMatch": round(goal_average, 4),
            "homeResultForm": {
                "attackDelta": round(home_result_attack, 4),
                "defenseDelta": round(home_result_defense, 4),
            },
            "awayResultForm": {
                "attackDelta": round(away_result_attack, 4),
                "defenseDelta": round(away_result_defense, 4),
            },
            "policy": "matchday_three_bounded_v1",
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
