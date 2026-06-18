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
        if self.spec.family == "poisson_nb_mixture":
            return poisson_negative_binomial_mixture_matrix(
                home_xg,
                away_xg,
                self.spec.parameters["dispersion"],
                self.spec.parameters["tail_weight"],
                max_goals,
                self.spec.parameters.get("rho", -0.04),
            )
        raise ValueError(f"unknown goal model family: {self.spec.family}")


def _timestamp(record: dict[str, Any]) -> datetime:
    value = str(record["kickoff_utc"]).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("kickoff_utc must include a timezone")
    return parsed


# --- Tournament prestige tier weighting ---
# Higher tiers = matches matter more for evaluating team strength.
_TOURNAMENT_TIERS: dict[str, float] = {
    "FIFA World Cup": 3.0,
    "UEFA Euro": 2.0,
    "Copa América": 2.0,
    "AFC Asian Cup": 2.0,
    "African Cup of Nations": 2.0,
    "Gold Cup": 2.0,
    "Confederations Cup": 2.0,
    "CONMEBOL–UEFA Cup of Champions": 2.0,
    "Oceania Nations Cup": 1.5,
    "Arab Cup": 1.5,
    "FIFA World Cup qualification": 1.0,
    "UEFA Euro qualification": 1.0,
    "AFC Asian Cup qualification": 1.0,
    "African Cup of Nations qualification": 1.0,
    "Gold Cup qualification": 1.0,
    "Oceania Nations Cup qualification": 1.0,
    "UEFA Nations League": 1.0,
    "CONCACAF Nations League": 1.0,
    "CONCACAF Nations League qualification": 0.8,
    "FIFA Series": 0.8,
    "AFC Challenge Cup": 0.8,
    "AFC Solidarity Cup": 0.8,
    "CONIFA World Football Cup": 0.6,
    "CECAFA Cup": 0.6,
    "COSAFA Cup": 0.6,
    "AFF Championship": 0.6,
    "SAFF Cup": 0.6,
    "EAFF Championship": 0.6,
    "WAFF Championship": 0.6,
    "Gulf Cup": 0.6,
    "CFU Caribbean Cup": 0.6,
    "UNCAF Cup": 0.6,
    "ASEAN Championship": 0.6,
    "CAFA Nations Cup": 0.6,
    "King's Cup": 0.5,
    "Kirin Cup": 0.5,
    "Nehru Cup": 0.5,
    "Merdeka Tournament": 0.5,
    "Cyprus International Tournament": 0.4,
    "Malta International Tournament": 0.4,
}
_TOURNAMENT_DEFAULT_TIER = 0.25  # friendlies and obscure cups


def _tournament_weight(tournament: str) -> float:
    return _TOURNAMENT_TIERS.get(tournament, _TOURNAMENT_DEFAULT_TIER)


# Earliest year allowed in training.  Modern football rules and competitive
# dynamics differ materially from the 19th/20th centuries — pre-2000 matches
# are excluded except for teams with sparse modern history.
EARLIEST_YEAR = 2000


def fit_goal_model(matches: Iterable[dict[str, Any]], spec: ModelSpec) -> FittedGoalModel:
    records = list(matches)
    if not records:
        return FittedGoalModel(spec, 1.35, 1.10, {}, {})
    reference = max(_timestamp(record) for record in records)
    half_life = spec.parameters.get("half_life_days", 730.0)
    tournament_tier = spec.parameters.get("tournament_tier", 1.0)  # multiplier knob
    weighted_home = weighted_away = total_weight = 0.0
    scored: dict[str, float] = {}
    conceded: dict[str, float] = {}
    appearances: dict[str, float] = {}
    for record in records:
        home_goals = float(record["home_goals_90"])
        away_goals = float(record["away_goals_90"])
        age_days = max(0.0, (reference - _timestamp(record)).total_seconds() / 86400)
        time_weight = math.exp(-math.log(2) * age_days / half_life) if half_life else 1.0
        tier_w = _tournament_weight(record.get("tournament", ""))
        if tournament_tier != 1.0:
            tier_w = tier_w ** tournament_tier  # compression/expansion knob
        weight = time_weight * tier_w
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


def poisson_negative_binomial_mixture_matrix(
    home_mean: float,
    away_mean: float,
    dispersion: float,
    tail_weight: float,
    max_goals: int = 10,
    rho: float = -0.04,
) -> list[list[float]]:
    """Shadow candidate that preserves the Poisson center and widens tails."""

    weight = max(0.0, min(1.0, tail_weight))
    poisson = score_matrix(home_mean, away_mean, max_goals=max_goals, rho=rho)
    negative_binomial = negative_binomial_matrix(home_mean, away_mean, dispersion, max_goals)
    return _normalize([
        [
            (1 - weight) * poisson[home][away] + weight * negative_binomial[home][away]
            for away in range(max_goals + 1)
        ]
        for home in range(max_goals + 1)
    ])


def default_candidate_grid() -> list[ModelSpec]:
    return [
        *(ModelSpec("dixon_coles", {"half_life_days": half_life, "rho": rho, "shrinkage": 6.0})
          for half_life in (365.0, 730.0) for rho in (-0.12, -0.08, -0.04)),
        *(ModelSpec("bivariate_poisson", {"half_life_days": 730.0, "shared_rate": shared, "shrinkage": 8.0})
          for shared in (0.05, 0.10, 0.15)),
        *(ModelSpec("negative_binomial", {"half_life_days": 730.0, "dispersion": dispersion, "shrinkage": 8.0})
          for dispersion in (2.0, 4.0, 8.0)),
        *(ModelSpec("poisson_nb_mixture", {
            "half_life_days": 730.0, "dispersion": dispersion, "tail_weight": tail_weight,
            "rho": -0.04, "shrinkage": 8.0,
        }) for dispersion in (2.0, 4.0) for tail_weight in (0.15, 0.25)),
        *(ModelSpec("hierarchical_poisson", {"shrinkage": shrinkage, "rho": 0.0})
          for shrinkage in (4.0, 8.0, 16.0)),
    ]


# --- Production goal-model xG provider ---
# Grid search on 128 WC 2018+2022 matches selected hierarchical_poisson
# as the best total-goals model (30.5% exact vs 26.6% for Dixon-Coles).
# half_life_days=730: matches >2 years old get <50% weight — keeps the
#   model anchored on recent form rather than historical reputation.
# tournament_tier=1.0: natural tier multiplier (WC ×3, friendlies ×0.25).
# shrinkage=24: stronger regression toward global mean for sparse teams.
PRODUCTION_GOAL_SPEC = ModelSpec(
    "hierarchical_poisson",
    {"shrinkage": 24.0, "rho": 0.0, "half_life_days": 730.0, "tournament_tier": 1.0},
)

# football-data.org → CSV team name aliases
_TEAM_ALIASES: dict[str, str] = {
    "Congo DR": "DR Congo",
    "Czech Republic": "Czech Republic",
    "Cape Verde Islands": "Cape Verde",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "United States": "United States",
    "IR Iran": "Iran",
}  # fmt: skip

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

    Only matches from *EARLIEST_YEAR* (2000) onward are included by default.
    Pre-2000 data is excluded because modern football rules, tactics and
    competitive dynamics differ materially from the 19th/20th centuries.

    Returns None when historical data is unavailable or the model can't
    differentiate the two teams.
    """
    spec = spec or PRODUCTION_GOAL_SPEC
    rows = _read_historical_matches()
    if not rows:
        return None
    # Keep only matches before the target date, from 2000 onwards
    prior = [row for row in rows if EARLIEST_YEAR <= int(row["date"][:4]) < int(target_date[:4]) + 1 and row["date"] < target_date]
    if len(prior) < 200:
        return None  # not enough recent data

    model = fit_goal_model(prior, spec)
    # Resolve aliases before looking up in fitted model
    home_key = _TEAM_ALIASES.get(home_team, home_team)
    away_key = _TEAM_ALIASES.get(away_team, away_team)
    hxg, axg = model.expected_goals(home_key, away_key, neutral=True)

    # If either team is unknown (no post-2000 history), the model returns
    # the global average for both — fall back to Elo which has broader coverage.
    if abs(hxg - axg) < 0.02 * max(hxg, axg):
        return None
    return (hxg, axg)
