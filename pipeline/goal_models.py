from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .model import score_matrix


@dataclass(frozen=True)
class ModelSpec:
    family: str
    parameters: dict[str, float]

    @property
    def key(self) -> str:
        suffix = ",".join(f"{key}={value:g}" for key, value in sorted(self.parameters.items()))
        return f"{self.family}[{suffix}]" if suffix else self.family


@dataclass
class FittedGoalModel:
    spec: ModelSpec
    global_home: float
    global_away: float
    attack: dict[str, float]
    defense: dict[str, float]

    def expected_goals(self, home_team: str, away_team: str, neutral: bool = True) -> tuple[float, float]:
        home_base = (self.global_home + self.global_away) / 2 if neutral else self.global_home
        away_base = (self.global_home + self.global_away) / 2 if neutral else self.global_away
        home = home_base * self.attack.get(home_team, 1.0) * self.defense.get(away_team, 1.0)
        away = away_base * self.attack.get(away_team, 1.0) * self.defense.get(home_team, 1.0)
        return max(0.08, home), max(0.08, away)

    def matrix(self, home_team: str, away_team: str, neutral: bool = True, max_goals: int = 10) -> list[list[float]]:
        home_xg, away_xg = self.expected_goals(home_team, away_team, neutral)
        if self.spec.family in {"legacy", "hierarchical_poisson"}:
            rho = self.spec.parameters.get("rho", 0.0)
            return score_matrix(home_xg, away_xg, max_goals=max_goals, rho=rho)
        if self.spec.family == "dixon_coles":
            return score_matrix(home_xg, away_xg, max_goals=max_goals, rho=self.spec.parameters["rho"])
        if self.spec.family == "bivariate_poisson":
            return bivariate_poisson_matrix(home_xg, away_xg, self.spec.parameters["shared_rate"], max_goals)
        if self.spec.family == "negative_binomial":
            return negative_binomial_matrix(home_xg, away_xg, self.spec.parameters["dispersion"], max_goals)
        raise ValueError(f"unknown goal model family: {self.spec.family}")


def _timestamp(record: dict[str, Any]) -> datetime:
    value = str(record["kickoff_utc"]).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("kickoff_utc must include a timezone")
    return parsed


def fit_goal_model(matches: Iterable[dict[str, Any]], spec: ModelSpec) -> FittedGoalModel:
    records = list(matches)
    if not records:
        return FittedGoalModel(spec, 1.35, 1.10, {}, {})
    reference = max(_timestamp(record) for record in records)
    half_life = spec.parameters.get("half_life_days")
    weighted_home = weighted_away = total_weight = 0.0
    scored: dict[str, float] = {}
    conceded: dict[str, float] = {}
    appearances: dict[str, float] = {}
    for record in records:
        home_goals = float(record["home_goals_90"])
        away_goals = float(record["away_goals_90"])
        age_days = max(0.0, (reference - _timestamp(record)).total_seconds() / 86400)
        weight = math.exp(-math.log(2) * age_days / half_life) if half_life else 1.0
        home = str(record["home_team_id"])
        away = str(record["away_team_id"])
        weighted_home += home_goals * weight
        weighted_away += away_goals * weight
        total_weight += weight
        scored[home] = scored.get(home, 0.0) + home_goals * weight
        scored[away] = scored.get(away, 0.0) + away_goals * weight
        conceded[home] = conceded.get(home, 0.0) + away_goals * weight
        conceded[away] = conceded.get(away, 0.0) + home_goals * weight
        appearances[home] = appearances.get(home, 0.0) + weight
        appearances[away] = appearances.get(away, 0.0) + weight

    global_home = max(0.2, weighted_home / total_weight)
    global_away = max(0.2, weighted_away / total_weight)
    global_team = (global_home + global_away) / 2
    shrinkage = spec.parameters.get("shrinkage", 8.0)
    if spec.family == "legacy":
        return FittedGoalModel(spec, global_home, global_away, {}, {})

    attack = {}
    defense = {}
    for team, count in appearances.items():
        attack_rate = (scored[team] + shrinkage * global_team) / (count + shrinkage)
        defense_rate = (conceded[team] + shrinkage * global_team) / (count + shrinkage)
        attack[team] = attack_rate / global_team
        defense[team] = defense_rate / global_team
    return FittedGoalModel(spec, global_home, global_away, attack, defense)


def _normalize(matrix: list[list[float]]) -> list[list[float]]:
    total = sum(sum(row) for row in matrix)
    return [[value / total for value in row] for row in matrix]


def bivariate_poisson_matrix(home_mean: float, away_mean: float, shared_rate: float, max_goals: int = 10) -> list[list[float]]:
    shared = min(shared_rate, home_mean * 0.45, away_mean * 0.45)
    home_only = max(0.001, home_mean - shared)
    away_only = max(0.001, away_mean - shared)
    matrix = []
    for home in range(max_goals + 1):
        row = []
        for away in range(max_goals + 1):
            probability = 0.0
            for common in range(min(home, away) + 1):
                probability += (
                    home_only ** (home - common) / math.factorial(home - common)
                    * away_only ** (away - common) / math.factorial(away - common)
                    * shared ** common / math.factorial(common)
                )
            row.append(math.exp(-(home_only + away_only + shared)) * probability)
        matrix.append(row)
    return _normalize(matrix)


def negative_binomial_probability(goals: int, mean: float, dispersion: float) -> float:
    return (
        math.gamma(goals + dispersion)
        / (math.gamma(dispersion) * math.factorial(goals))
        * (dispersion / (dispersion + mean)) ** dispersion
        * (mean / (dispersion + mean)) ** goals
    )


def negative_binomial_matrix(home_mean: float, away_mean: float, dispersion: float, max_goals: int = 10) -> list[list[float]]:
    home = [negative_binomial_probability(goals, home_mean, dispersion) for goals in range(max_goals + 1)]
    away = [negative_binomial_probability(goals, away_mean, dispersion) for goals in range(max_goals + 1)]
    return _normalize([[home_goals * away_goals for away_goals in away] for home_goals in home])


def default_candidate_grid() -> list[ModelSpec]:
    return [
        *(ModelSpec("dixon_coles", {"half_life_days": half_life, "rho": rho, "shrinkage": 6.0})
          for half_life in (365.0, 730.0) for rho in (-0.12, -0.08, -0.04)),
        *(ModelSpec("bivariate_poisson", {"half_life_days": 730.0, "shared_rate": shared, "shrinkage": 8.0})
          for shared in (0.05, 0.10, 0.15)),
        *(ModelSpec("negative_binomial", {"half_life_days": 730.0, "dispersion": dispersion, "shrinkage": 8.0})
          for dispersion in (2.0, 4.0, 8.0)),
        *(ModelSpec("hierarchical_poisson", {"shrinkage": shrinkage, "rho": 0.0})
          for shrinkage in (4.0, 8.0, 16.0)),
    ]


# --- Production goal-model xG provider ---
# Grid search on 128 WC 2018+2022 matches selected hierarchical_poisson
# as the best total-goals model (30.5% exact vs 26.6% for Dixon-Coles).
# We use it to produce team-specific xG estimates from historical data.
PRODUCTION_GOAL_SPEC = ModelSpec("hierarchical_poisson", {"shrinkage": 16.0, "rho": 0.0})

# Fallback when goal-model data is unavailable.
DEFAULT_GLOBAL_HOME = 1.55
DEFAULT_GLOBAL_AWAY = 1.00

_INTERNATIONAL_CSV_PATH = None


def _get_csv_path() -> Path:
    global _INTERNATIONAL_CSV_PATH
    if _INTERNATIONAL_CSV_PATH is not None:
        return _INTERNATIONAL_CSV_PATH
    # Try the backtest artifact path first, then pipeline data
    candidates = [
        Path(__file__).resolve().parent.parent / "artifacts" / "total-goals-backtest" / "international_results.csv",
        Path(__file__).resolve().parent / "data" / "international_results.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            _INTERNATIONAL_CSV_PATH = candidate
            return candidate
    _INTERNATIONAL_CSV_PATH = Path("")  # sentinel: not found
    return _INTERNATIONAL_CSV_PATH


def _read_historical_matches() -> list[dict[str, Any]]:
    """Read all international matches from the CSV, keeping only finished ones."""
    path = _get_csv_path()
    if not path or not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("home_score") or not row.get("away_score"):
                continue
            if row["home_score"] in ("NA", "") or row["away_score"] in ("NA", ""):
                continue
            rows.append({
                "date": row["date"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home_team_id": row["home_team"],
                "away_team_id": row["away_team"],
                "home_goals_90": int(float(row["home_score"])),
                "away_goals_90": int(float(row["away_score"])),
                "tournament": row["tournament"],
                "neutral": row.get("neutral", "TRUE").upper() == "TRUE",
                "kickoff_utc": f"{row['date']}T12:00:00+00:00",
            })
    return rows


def goal_model_xg(
    home_team: str,
    away_team: str,
    target_date: str,
    spec: ModelSpec | None = None,
) -> tuple[float, float] | None:
    """Estimate expected goals using a goal model fit on historical data.

    Filters all international matches before *target_date*, fits the
    specified model (default: production spec), and returns the
    matchup-specific xG.

    Returns None when the historical data is unavailable.
    """
    spec = spec or PRODUCTION_GOAL_SPEC
    rows = _read_historical_matches()
    if not rows:
        return None
    # Keep only matches before the target date
    prior = [row for row in rows if row["date"] < target_date]
    if len(prior) < 50:
        return None  # not enough data for meaningful fit
    model = fit_goal_model(prior, spec)
    hxg, axg = model.expected_goals(home_team, away_team, neutral=True)
    # If the model can't differentiate the teams (both unknown → same xG),
    # return None to let the caller fall back to Elo.
    if abs(hxg - axg) < 0.01 * hxg:
        return None
    return (hxg, axg)
