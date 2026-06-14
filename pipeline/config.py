from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "pipeline"
OUTPUT_DIR = ROOT / "public" / "data"
FIXTURE_DIR = ROOT / "tests" / "fixtures"
MANUAL_DIR = ROOT / "manual-data"


@dataclass(frozen=True)
class PipelineSettings:
    timezone: str = "Asia/Shanghai"
    api_daily_budget: int = 95
    odds_max_age_minutes: int = 45
    simulations: int = 100_000
    initial_bankroll: int = 200
    world_cup_league_id: int = 1
    world_cup_season: int = 2026


SETTINGS = PipelineSettings()

SPORTTERY_URLS = {
    "spf": "https://m.sporttery.cn/mjc/jsq/zqspf/",
    "score": "https://m.sporttery.cn/mjc/jsq/zqbf/",
    "mixed": "https://m.sporttery.cn/mjc/jsq/zqhhgg/",
}

VENUES = {
    "MetLife Stadium": {"lat": 40.8135, "lon": -74.0745, "altitude": 3},
    "SoFi Stadium": {"lat": 33.9535, "lon": -118.3392, "altitude": 31},
    "Estadio Azteca": {"lat": 19.3029, "lon": -99.1505, "altitude": 2240},
    "Estadio BBVA": {"lat": 25.6694, "lon": -100.2445, "altitude": 430},
    "Demo Stadium": {"lat": 40.0, "lon": -100.0, "altitude": 210},
}
