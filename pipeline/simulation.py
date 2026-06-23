from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from .discipline import DisciplineEngine, PlayerDisciplineState
from .model import outcome_probabilities


@dataclass(frozen=True)
class MatchSimulationInput:
    match_id: str
    home_team: str
    away_team: str
    home_xg: float
    away_xg: float
    stage: str = "single"
    group: str | None = None
    stage_complete: bool = False
    parameter_samples: tuple[tuple[float, float], ...] = ()
    home_players: tuple[str, ...] = ()
    away_players: tuple[str, ...] = ()
    home_yellow_rate: float = 0.0
    away_yellow_rate: float = 0.0
    home_red_probability: float = 0.0
    away_red_probability: float = 0.0
    red_card_xg_penalty: float = 0.0
    segment_weights: tuple[float, float, float, float] = (0.23, 0.22, 0.27, 0.28)
    home_late_attack_multiplier: float = 1.0
    away_late_attack_multiplier: float = 1.0
    home_late_defensive_risk_multiplier: float = 1.0
    away_late_defensive_risk_multiplier: float = 1.0


@dataclass
class TournamentSimulation:
    paths: int
    seed: int
    scores_by_match: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    halftime_scores_by_match: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    group_rank_probabilities: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    parameter_uncertainty: str = "fixed"


def sample_poisson(randomizer: random.Random, expected: float) -> int:
    if expected <= 0:
        return 0
    threshold = math.exp(-expected)
    product = 1.0
    count = 0
    while product > threshold:
        product *= randomizer.random()
        count += 1
    return count - 1


def _sample_cards(
    randomizer: random.Random,
    team: str,
    players: tuple[str, ...],
    yellow_rate: float,
    red_probability: float,
) -> list[dict[str, str]]:
    if not players:
        return []
    events = []
    yellow_players: set[str] = set()
    for _ in range(sample_poisson(randomizer, yellow_rate)):
        player = randomizer.choice(players)
        if player in yellow_players:
            events.append({"player_id": player, "team_id": team, "event_type": "second_yellow"})
        else:
            yellow_players.add(player)
            events.append({"player_id": player, "team_id": team, "event_type": "yellow"})
    if randomizer.random() < red_probability:
        events.append({"player_id": randomizer.choice(players), "team_id": team, "event_type": "direct_red"})
    return events


def _segment_multiplier(red_minute: int | None, start: int, end: int, penalty: float) -> float:
    if red_minute is None or penalty <= 0 or red_minute >= end:
        return 1.0
    affected = end - max(start, red_minute)
    return max(0.1, 1 - penalty * affected / (end - start))


def _score_matrix(scores: list[tuple[int, int]], max_goals: int = 10) -> list[list[float]]:
    matrix = [[0.0 for _ in range(max_goals + 1)] for _ in range(max_goals + 1)]
    for home, away in scores:
        matrix[min(max_goals, home)][min(max_goals, away)] += 1
    total = len(scores)
    return [[value / total for value in row] for row in matrix]


def _half_full(scores: list[tuple[int, int]], halftime: list[tuple[int, int]]) -> dict[str, float]:
    labels = {"home": "胜", "draw": "平", "away": "负"}
    result = {f"{first}{full}": 0 for first in labels.values() for full in labels.values()}

    def outcome(home: int, away: int) -> str:
        return "home" if home > away else "draw" if home == away else "away"

    for (home, away), (half_home, half_away) in zip(scores, halftime, strict=True):
        result[f"{labels[outcome(half_home, half_away)]}{labels[outcome(home, away)]}"] += 1
    return {key: value / len(scores) for key, value in result.items()}


def _quality(scores: list[tuple[int, int]], checkpoints: Iterable[int]) -> dict[str, Any]:
    snapshots = []
    previous: dict[str, float] | None = None
    for count in sorted({min(len(scores), checkpoint) for checkpoint in checkpoints if checkpoint > 0}):
        matrix = _score_matrix(scores[:count])
        probabilities = outcome_probabilities(matrix)
        delta = max(abs(probabilities[key] - previous[key]) for key in probabilities) if previous else None
        snapshots.append({
            "paths": count,
            "outcomes": {key: round(value, 6) for key, value in probabilities.items()},
            "maxDeltaFromPrevious": round(delta, 6) if delta is not None else None,
        })
        previous = probabilities
    final = outcome_probabilities(_score_matrix(scores))
    errors = {key: math.sqrt(value * (1 - value) / len(scores)) for key, value in final.items()}
    intervals = {
        key: [max(0.0, final[key] - 1.96 * errors[key]), min(1.0, final[key] + 1.96 * errors[key])]
        for key in final
    }
    return {
        "actualPaths": len(scores),
        "monteCarloStandardError": {key: round(value, 6) for key, value in errors.items()},
        "confidence95": {key: [round(value, 6) for value in bounds] for key, bounds in intervals.items()},
        "convergence": snapshots,
    }


def rank_group(
    teams: Iterable[str],
    results: Iterable[dict[str, Any]],
    fifa_ranking_history: dict[str, tuple[int, ...]] | None = None,
) -> list[str]:
    team_list = list(teams)
    matches = list(results)
    rankings = fifa_ranking_history or {}
    overall = {team: {"points": 0, "gf": 0, "ga": 0, "conduct": 0} for team in team_list}
    for match in matches:
        home, away = match["home"], match["away"]
        home_goals, away_goals = int(match["home_goals"]), int(match["away_goals"])
        overall[home]["gf"] += home_goals
        overall[home]["ga"] += away_goals
        overall[away]["gf"] += away_goals
        overall[away]["ga"] += home_goals
        if home_goals > away_goals:
            overall[home]["points"] += 3
        elif home_goals < away_goals:
            overall[away]["points"] += 3
        else:
            overall[home]["points"] += 1
            overall[away]["points"] += 1
        for team, score in match.get("conduct", {}).items():
            overall[team]["conduct"] += int(score)

    def mini_table(tied: list[str]) -> dict[str, tuple[int, int, int]]:
        table = {team: [0, 0, 0] for team in tied}
        selected = set(tied)
        for match in matches:
            home, away = match["home"], match["away"]
            if home not in selected or away not in selected:
                continue
            home_goals, away_goals = int(match["home_goals"]), int(match["away_goals"])
            table[home][1] += home_goals - away_goals
            table[away][1] += away_goals - home_goals
            table[home][2] += home_goals
            table[away][2] += away_goals
            if home_goals > away_goals:
                table[home][0] += 3
            elif home_goals < away_goals:
                table[away][0] += 3
            else:
                table[home][0] += 1
                table[away][0] += 1
        return {team: tuple(values) for team, values in table.items()}

    def fallback_key(team: str) -> tuple[Any, ...]:
        row = overall[team]
        ranking_key = tuple(-rank for rank in rankings.get(team, (10_000,)))
        return (row["gf"] - row["ga"], row["gf"], row["conduct"], *ranking_key, team)

    def resolve(tied: list[str]) -> list[str]:
        if len(tied) <= 1:
            return tied
        mini = mini_table(tied)
        buckets: dict[tuple[int, int, int], list[str]] = {}
        for team in tied:
            buckets.setdefault(mini[team], []).append(team)
        if len(buckets) == 1:
            return sorted(tied, key=fallback_key, reverse=True)
        ordered = []
        for key in sorted(buckets, reverse=True):
            bucket = buckets[key]
            ordered.extend(resolve(bucket) if len(bucket) < len(tied) else sorted(bucket, key=fallback_key, reverse=True))
        return ordered

    by_points: dict[int, list[str]] = {}
    for team in team_list:
        by_points.setdefault(overall[team]["points"], []).append(team)
    ranking = []
    for points in sorted(by_points, reverse=True):
        ranking.extend(resolve(by_points[points]))
    return ranking


def simulate_tournament(
    matches: Iterable[MatchSimulationInput],
    paths: int = 100_000,
    seed: int = 20_260_615,
    checkpoints: tuple[int, ...] = (25_000, 50_000, 100_000),
) -> TournamentSimulation:
    inputs = list(matches)
    if paths <= 0:
        raise ValueError("paths must be positive")
    randomizer = random.Random(seed)
    scores = {match.match_id: [] for match in inputs}
    halftime_scores = {match.match_id: [] for match in inputs}
    group_rank_counts: dict[str, dict[str, list[int]]] = {}
    has_parameter_samples = any(match.parameter_samples for match in inputs)
    discipline = DisciplineEngine()

    for _ in range(paths):
        states: dict[str, PlayerDisciplineState] = {}
        path_group_results: dict[str, list[dict[str, Any]]] = {}
        for match in inputs:
            discipline.start_team_match(match.home_team, states)
            discipline.start_team_match(match.away_team, states)
            if match.parameter_samples:
                home_xg, away_xg = randomizer.choice(match.parameter_samples)
            else:
                home_xg, away_xg = match.home_xg, match.away_xg

            home_red_minute = randomizer.randrange(1, 91) if randomizer.random() < match.home_red_probability else None
            away_red_minute = randomizer.randrange(1, 91) if randomizer.random() < match.away_red_probability else None
            if len(match.segment_weights) != 4 or not math.isclose(sum(match.segment_weights), 1.0, abs_tol=1e-9):
                raise ValueError("segment_weights must contain four values summing to 1")
            boundaries = ((0, 25), (25, 45), (45, 70), (70, 90))
            home_segments = []
            away_segments = []
            for index, ((start, end), weight) in enumerate(zip(boundaries, match.segment_weights, strict=True)):
                home_mean = home_xg * weight * _segment_multiplier(
                    home_red_minute, start, end, match.red_card_xg_penalty
                )
                away_mean = away_xg * weight * _segment_multiplier(
                    away_red_minute, start, end, match.red_card_xg_penalty
                )
                if index == 3:
                    home_mean *= match.home_late_attack_multiplier * match.away_late_defensive_risk_multiplier
                    away_mean *= match.away_late_attack_multiplier * match.home_late_defensive_risk_multiplier
                home_segments.append(sample_poisson(randomizer, home_mean))
                away_segments.append(sample_poisson(randomizer, away_mean))
            half_home = home_segments[0] + home_segments[1]
            half_away = away_segments[0] + away_segments[1]
            full_home = sum(home_segments)
            full_away = sum(away_segments)
            scores[match.match_id].append((full_home, full_away))
            halftime_scores[match.match_id].append((half_home, half_away))

            events = [
                *_sample_cards(randomizer, match.home_team, match.home_players, match.home_yellow_rate, 0.0),
                *_sample_cards(randomizer, match.away_team, match.away_players, match.away_yellow_rate, 0.0),
            ]
            if home_red_minute is not None and match.home_players:
                events.append({"player_id": randomizer.choice(match.home_players), "team_id": match.home_team, "event_type": "direct_red"})
            if away_red_minute is not None and match.away_players:
                events.append({"player_id": randomizer.choice(match.away_players), "team_id": match.away_team, "event_type": "direct_red"})
            discipline_result = discipline.process_match(
                match.match_id, match.stage, events, states, stage_complete=match.stage_complete
            )
            if match.group:
                path_group_results.setdefault(match.group, []).append({
                    "home": match.home_team,
                    "away": match.away_team,
                    "home_goals": full_home,
                    "away_goals": full_away,
                    "conduct": discipline_result.team_conduct_scores,
                })

        for group, group_results in path_group_results.items():
            teams = sorted({result[side] for result in group_results for side in ("home", "away")})
            ranking = rank_group(teams, group_results)
            group_counts = group_rank_counts.setdefault(group, {team: [0] * len(teams) for team in teams})
            for position, team in enumerate(ranking):
                group_counts[team][position] += 1

    summaries = {}
    for match in inputs:
        matrix = _score_matrix(scores[match.match_id])
        summaries[match.match_id] = {
            "matrix": matrix,
            "outcomes": outcome_probabilities(matrix),
            "halfFull": _half_full(scores[match.match_id], halftime_scores[match.match_id]),
            "quality": _quality(scores[match.match_id], checkpoints),
        }
    return TournamentSimulation(
        paths=paths,
        seed=seed,
        scores_by_match=scores,
        halftime_scores_by_match=halftime_scores,
        summaries=summaries,
        group_rank_probabilities={
            group: {team: [count / paths for count in positions] for team, positions in teams.items()}
            for group, teams in group_rank_counts.items()
        },
        parameter_uncertainty="posterior_or_bootstrap_samples" if has_parameter_samples else "fixed",
    )
