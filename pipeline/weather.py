from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests

from .cache import JsonCache
from .config import CACHE_DIR


class OpenMeteoClient:
    url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self):
        self.cache = JsonCache(CACHE_DIR)

    def forecast_at(self, lat: float, lon: float, kickoff: datetime) -> dict[str, Any]:
        key = f"{lat:.4f},{lon:.4f},{kickoff.date().isoformat()}"
        cached = self.cache.get("open-meteo", key, timedelta(hours=2))
        if cached is None:
            params = {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": 16,
            }
            response = requests.get(self.url, params=params, timeout=20)
            response.raise_for_status()
            cached = response.json()
            self.cache.set("open-meteo", key, cached)
        hourly = cached.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return {"status": "missing"}
        index = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i]).replace(tzinfo=kickoff.tzinfo) - kickoff))
        return {
            "status": "fresh",
            "temperature": hourly["temperature_2m"][index],
            "humidity": hourly["relative_humidity_2m"][index],
            "apparent_temperature": hourly["apparent_temperature"][index],
            "precipitation_probability": hourly["precipitation_probability"][index],
            "wind_speed": hourly["wind_speed_10m"][index],
        }
