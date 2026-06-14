from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .cache import JsonCache
from .config import CACHE_DIR, SETTINGS


class RequestBudgetExceeded(RuntimeError):
    pass


class ApiFootballClient:
    base_url = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str | None = None, budget: int = SETTINGS.api_daily_budget):
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY")
        self.budget = budget
        self.cache = JsonCache(CACHE_DIR)
        self.counter_path = CACHE_DIR / "api-football-budget.json"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _counter(self) -> dict[str, Any]:
        from datetime import date

        today = date.today().isoformat()
        if self.counter_path.exists():
            value = json.loads(self.counter_path.read_text(encoding="utf-8"))
            if value.get("date") == today:
                return value
        return {"date": today, "count": 0}

    def _consume(self) -> None:
        counter = self._counter()
        if counter["count"] >= self.budget:
            raise RequestBudgetExceeded(f"API-Football daily budget {self.budget} exhausted")
        counter["count"] += 1
        self.counter_path.parent.mkdir(parents=True, exist_ok=True)
        self.counter_path.write_text(json.dumps(counter), encoding="utf-8")

    def get(self, endpoint: str, params: dict[str, Any], max_age: timedelta = timedelta(hours=6)) -> list[dict[str, Any]]:
        key = f"{endpoint}?{urlencode(sorted(params.items()))}"
        cached = self.cache.get("api-football", key, max_age)
        if cached is not None:
            return cached
        if not self.api_key:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        self._consume()
        response = requests.get(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers={"x-apisports-key": self.api_key},
            params=params,
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"API-Football error: {errors}")
        value = payload.get("response", [])
        self.cache.set("api-football", key, value)
        return value

    def world_cup_fixtures(self, target_date: str) -> list[dict[str, Any]]:
        return self.get("fixtures", {
            "date": target_date,
            "league": SETTINGS.world_cup_league_id,
            "season": SETTINGS.world_cup_season,
            "timezone": SETTINGS.timezone,
        }, timedelta(hours=2))

    def recent_team_fixtures(self, team_id: int, last: int = 20) -> list[dict[str, Any]]:
        return self.get("fixtures", {"team": team_id, "last": last, "timezone": SETTINGS.timezone}, timedelta(hours=12))

    def squad(self, team_id: int) -> list[dict[str, Any]]:
        return self.get("players/squads", {"team": team_id}, timedelta(days=1))

    def coach(self, team_id: int) -> list[dict[str, Any]]:
        return self.get("coachs", {"team": team_id}, timedelta(days=3))

    def fixture_injuries(self, fixture_id: int) -> list[dict[str, Any]]:
        return self.get("injuries", {"fixture": fixture_id}, timedelta(hours=2))


def read_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
