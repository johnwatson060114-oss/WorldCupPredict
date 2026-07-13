from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "pipeline"
OUTPUT_DIR = ROOT / "public" / "data"
FIXTURE_DIR = ROOT / "tests" / "fixtures"
MANUAL_DIR = ROOT / "manual-data"
SPORTTERY_SNAPSHOT = CACHE_DIR / "sporttery-live.json"

PIPELINE_VERSION = "2.1.0"
LEGACY_MODEL_VERSION = "legacy-dixon-coles-v1"
OUTCOME_RECOMMENDATION_THRESHOLD = 0.60


@dataclass(frozen=True)
class PipelineSettings:
    timezone: str = "Asia/Shanghai"
    api_daily_budget: int = 95
    odds_max_age_minutes: int = 45
    simulations: int = 100_000
    random_seed: int = 20_260_615
    initial_bankroll: int = 200
    parlay_lookahead_days: int = 3
    world_cup_league_id: int = 1
    world_cup_season: int = 2026


SETTINGS = PipelineSettings()

SPORTTERY_URLS = {
    "spf": "https://m.sporttery.cn/mjc/jsq/zqspf/",
    "score": "https://m.sporttery.cn/mjc/jsq/zqbf/",
    "mixed": "https://m.sporttery.cn/mjc/jsq/zqhhgg/",
}

VENUES = {
    # 2026 FIFA World Cup stadiums (USA / Canada / Mexico)
    "MetLife Stadium": {"lat": 40.8135, "lon": -74.0745, "altitude": 3},
    "SoFi Stadium": {"lat": 33.9535, "lon": -118.3392, "altitude": 31},
    "AT&T Stadium": {"lat": 32.7473, "lon": -97.0945, "altitude": 180},
    "Arrowhead Stadium": {"lat": 39.0489, "lon": -94.4839, "altitude": 274},
    "Mercedes-Benz Stadium": {"lat": 33.7555, "lon": -84.4010, "altitude": 300},
    "Gillette Stadium": {"lat": 42.0909, "lon": -71.2643, "altitude": 60},
    "Levi's Stadium": {"lat": 37.4030, "lon": -121.9702, "altitude": 3},
    "NRG Stadium": {"lat": 29.6847, "lon": -95.4107, "altitude": 14},
    "Lincoln Financial Field": {"lat": 39.9008, "lon": -75.1675, "altitude": 3},
    "Lumen Field": {"lat": 47.5952, "lon": -122.3316, "altitude": 3},
    "Hard Rock Stadium": {"lat": 25.9580, "lon": -80.2389, "altitude": 3},
    "BC Place": {"lat": 49.2767, "lon": -123.1120, "altitude": 3},
    "BMO Field": {"lat": 43.6329, "lon": -79.4186, "altitude": 78},
    "Estadio Azteca": {"lat": 19.3029, "lon": -99.1505, "altitude": 2240},
    "Estadio BBVA": {"lat": 25.6694, "lon": -100.2445, "altitude": 430},
    "Estadio Akron": {"lat": 20.6817, "lon": -103.4628, "altitude": 1570},
    "Demo Stadium": {"lat": 40.0, "lon": -100.0, "altitude": 210},
}

# Map (home_TLA, away_TLA) → venue name for the group stage.
# football-data.org free tier does not return venue, so we hardcode the
# official 2026 World Cup schedule mapping.
FIXTURE_VENUES: dict[tuple[str, str], str] = {
    # Group I (France, Senegal, Iraq, Norway)
    ("FRA", "SEN"): "MetLife Stadium",
    ("IRQ", "NOR"): "Gillette Stadium",
    ("NOR", "SEN"): "MetLife Stadium",
    ("FRA", "IRQ"): "Lincoln Financial Field",
    ("NOR", "FRA"): "Gillette Stadium",
    ("SEN", "IRQ"): "BMO Field",
    # Group J (Argentina, Algeria, Austria, Jordan)
    ("ARG", "ALG"): "Arrowhead Stadium",
    ("AUT", "JOR"): "Levi's Stadium",
    ("ARG", "AUT"): "AT&T Stadium",
    ("JOR", "ALG"): "Levi's Stadium",
    ("ALG", "AUT"): "Arrowhead Stadium",
    ("JOR", "ARG"): "AT&T Stadium",
}
