from __future__ import annotations

from datetime import timedelta

import requests

from .cache import JsonCache
from .config import CACHE_DIR
from .football_data import TEAM_NAMES_ZH
from .model import outcome_probabilities, score_matrix


class EloRatingsClient:
    base_url = "https://www.eloratings.net"

    def __init__(self):
        self.cache = JsonCache(CACHE_DIR)

    def _text(self, filename: str) -> str:
        cached = self.cache.get("elo-ratings", filename, timedelta(hours=6))
        if cached is not None:
            return str(cached)
        response = requests.get(f"{self.base_url}/{filename}", timeout=25)
        response.raise_for_status()
        response.encoding = "utf-8"
        self.cache.set("elo-ratings", filename, response.text)
        return response.text

    def ratings(self) -> dict[str, int]:
        names = {}
        for line in self._text("en.teams.tsv").splitlines():
            columns = line.split("\t")
            if len(columns) >= 2:
                names[columns[0]] = columns[1]
        ratings = {}
        for line in self._text("World.tsv").splitlines():
            columns = line.split("\t")
            if len(columns) < 4 or not columns[3].isdigit():
                continue
            english_name = names.get(columns[2])
            if english_name:
                ratings[TEAM_NAMES_ZH.get(english_name, english_name)] = int(columns[3])
        return ratings


def expected_goals_from_elo(home_rating: int, away_rating: int, total_goals: float = 2.55) -> tuple[float, float]:
    """Fit Poisson means to Elo expected points on a neutral field."""
    target_points = 1 / (1 + 10 ** (-(home_rating - away_rating) / 400))
    low, high = 0.15, total_goals - 0.15
    for _ in range(40):
        home_xg = (low + high) / 2
        away_xg = total_goals - home_xg
        outcomes = outcome_probabilities(score_matrix(home_xg, away_xg))
        expected_points = outcomes["home"] + 0.5 * outcomes["draw"]
        if expected_points < target_points:
            low = home_xg
        else:
            high = home_xg
    home_xg = (low + high) / 2
    return home_xg, max(0.15, total_goals - home_xg)


def allocate_total_goals_by_elo(
    total_goals: float,
    home_rating: int,
    away_rating: int,
) -> tuple[float, float]:
    """Allocate an independently estimated match total using Elo strength.

    The goal model owns the total scoring environment; Elo only decides how
    that total is split between the two teams. This avoids counting recent
    score information twice in both the total and the strength allocation.
    """

    return expected_goals_from_elo(home_rating, away_rating, total_goals=max(0.30, total_goals))
