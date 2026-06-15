from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PlayerValue:
    player_id: str
    name: str
    team: str
    position: str
    attack_value: float
    defense_value: float
    sample_size: int
    model_version: str
    source_url: str
    observed_at: str


def shrink_value(raw: float, sample_size: int, position_prior: float, team_prior: float, prior_strength: int = 12) -> float:
    prior = (position_prior + team_prior) / 2
    weight = max(0, sample_size) / (max(0, sample_size) + prior_strength)
    return weight * raw + (1 - weight) * prior


def shrink_player(
    player: PlayerValue,
    position_priors: dict[str, dict[str, float]],
    team_priors: dict[str, dict[str, float]],
    prior_strength: int = 12,
) -> PlayerValue:
    position = position_priors.get(player.position, {"attack": 0.0, "defense": 0.0})
    team = team_priors.get(player.team, {"attack": 0.0, "defense": 0.0})
    return PlayerValue(
        **{
            **player.__dict__,
            "attack_value": shrink_value(player.attack_value, player.sample_size, position["attack"], team["attack"], prior_strength),
            "defense_value": shrink_value(player.defense_value, player.sample_size, position["defense"], team["defense"], prior_strength),
        }
    )


def _replacement_for(starter: PlayerValue, bench: list[PlayerValue], used: set[str]) -> PlayerValue | None:
    candidates = [player for player in bench if player.player_id not in used and player.position == starter.position]
    if not candidates:
        return None
    return max(candidates, key=lambda player: player.attack_value + player.defense_value)


def calculate_absence_impact(
    home_xg: float,
    away_xg: float,
    home_starters: Iterable[PlayerValue],
    away_starters: Iterable[PlayerValue],
    home_bench: Iterable[PlayerValue],
    away_bench: Iterable[PlayerValue],
    unavailable_player_ids: set[str],
) -> tuple[float, float, list[dict[str, Any]]]:
    adjusted_home, adjusted_away = home_xg, away_xg
    plans: list[dict[str, Any]] = []
    for side, starters, bench in (
        ("home", list(home_starters), list(home_bench)),
        ("away", list(away_starters), list(away_bench)),
    ):
        used: set[str] = set()
        for starter in starters:
            if starter.player_id not in unavailable_player_ids:
                continue
            replacement = _replacement_for(starter, bench, used)
            if replacement is None:
                plans.append({
                    "side": side,
                    "starterId": starter.player_id,
                    "starter": starter.name,
                    "position": starter.position,
                    "status": "missing_replacement_value",
                    "modelVersion": starter.model_version,
                    "sourceUrl": starter.source_url,
                })
                continue
            used.add(replacement.player_id)
            attack_delta = starter.attack_value - replacement.attack_value
            defense_delta = starter.defense_value - replacement.defense_value
            if side == "home":
                adjusted_home -= attack_delta
                adjusted_away += defense_delta
            else:
                adjusted_away -= attack_delta
                adjusted_home += defense_delta
            plans.append({
                "side": side,
                "starterId": starter.player_id,
                "starter": starter.name,
                "replacementId": replacement.player_id,
                "replacement": replacement.name,
                "position": starter.position,
                "attackDelta": round(attack_delta, 4),
                "defenseDelta": round(defense_delta, 4),
                "status": "applied",
                "modelVersion": starter.model_version,
                "sourceUrl": starter.source_url,
                "observedAt": starter.observed_at,
            })
    return max(0.08, adjusted_home), max(0.08, adjusted_away), plans


def _players(records: Iterable[dict[str, Any]], team: str, role: str) -> list[PlayerValue]:
    return [
        PlayerValue(
            player_id=str(record["player_id"]),
            name=str(record["name"]),
            team=str(record["team"]),
            position=str(record["position"]),
            attack_value=float(record["attack_value"]),
            defense_value=float(record["defense_value"]),
            sample_size=int(record["sample_size"]),
            model_version=str(record["model_version"]),
            source_url=str(record["source_url"]),
            observed_at=str(record["observed_at"]),
        )
        for record in records
        if record.get("team") == team and record.get("role") == role
    ]


def apply_lineup_impacts(seeds: list[dict[str, Any]]) -> None:
    for seed in seeds:
        records = seed.get("player_values", [])
        absences = seed.get("confirmed_absences", [])
        if not records or not absences:
            continue
        unavailable_names = {str(item["player"]) for item in absences}
        unavailable_ids = {
            str(record["player_id"]) for record in records if str(record.get("name")) in unavailable_names
        }
        if not unavailable_ids:
            continue
        home, away, plans = calculate_absence_impact(
            float(seed["base_xg"][0]),
            float(seed["base_xg"][1]),
            _players(records, seed["home_team"], "starter"),
            _players(records, seed["away_team"], "starter"),
            _players(records, seed["home_team"], "bench"),
            _players(records, seed["away_team"], "bench"),
            unavailable_ids,
        )
        seed["base_xg"] = [home, away]
        seed["lineup_impact"] = plans
