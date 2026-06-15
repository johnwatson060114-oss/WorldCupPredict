from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from .cache import JsonCache
from .config import CACHE_DIR, SETTINGS


TEAM_NAMES_ZH = {
    "Algeria": "阿尔及利亚",
    "Argentina": "阿根廷",
    "Australia": "澳大利亚",
    "Austria": "奥地利",
    "Belgium": "比利时",
    "Bosnia-Herzegovina": "波黑",
    "Bosnia and Herzegovina": "波黑",
    "Brazil": "巴西",
    "Canada": "加拿大",
    "Cape Verde Islands": "佛得角",
    "Cape Verde": "佛得角",
    "Colombia": "哥伦比亚",
    "Congo DR": "民主刚果",
    "DR Congo": "民主刚果",
    "Croatia": "克罗地亚",
    "Curaçao": "库拉索",
    "Cura莽ao": "库拉索",
    "Czechia": "捷克",
    "Ecuador": "厄瓜多尔",
    "Egypt": "埃及",
    "England": "英格兰",
    "France": "法国",
    "Germany": "德国",
    "Ghana": "加纳",
    "Haiti": "海地",
    "Iran": "伊朗",
    "Iraq": "伊拉克",
    "Ivory Coast": "科特迪瓦",
    "Japan": "日本",
    "Jordan": "约旦",
    "Mexico": "墨西哥",
    "Morocco": "摩洛哥",
    "Netherlands": "荷兰",
    "New Zealand": "新西兰",
    "Norway": "挪威",
    "Panama": "巴拿马",
    "Paraguay": "巴拉圭",
    "Portugal": "葡萄牙",
    "Qatar": "卡塔尔",
    "Saudi Arabia": "沙特",
    "Scotland": "苏格兰",
    "Senegal": "塞内加尔",
    "South Africa": "南非",
    "South Korea": "韩国",
    "Spain": "西班牙",
    "Sweden": "瑞典",
    "Switzerland": "瑞士",
    "Tunisia": "突尼斯",
    "Turkey": "土耳其",
    "United States": "美国",
    "Uruguay": "乌拉圭",
    "Uzbekistan": "乌兹别克斯坦",
}

TEAM_FLAGS = {
    "ALG": "🇩🇿", "ARG": "🇦🇷", "AUS": "🇦🇺", "AUT": "🇦🇹", "BEL": "🇧🇪",
    "BIH": "🇧🇦", "BRA": "🇧🇷", "CAN": "🇨🇦", "CPV": "🇨🇻", "COL": "🇨🇴",
    "COD": "🇨🇩", "CRO": "🇭🇷", "CUW": "🇨🇼", "CZE": "🇨🇿", "ECU": "🇪🇨",
    "EGY": "🇪🇬", "ENG": "🏴", "FRA": "🇫🇷", "GER": "🇩🇪", "GHA": "🇬🇭",
    "HAI": "🇭🇹", "IRN": "🇮🇷", "IRQ": "🇮🇶", "CIV": "🇨🇮", "JPN": "🇯🇵",
    "JOR": "🇯🇴", "MEX": "🇲🇽", "MAR": "🇲🇦", "NED": "🇳🇱", "NZL": "🇳🇿",
    "NOR": "🇳🇴", "PAN": "🇵🇦", "PAR": "🇵🇾", "POR": "🇵🇹", "QAT": "🇶🇦",
    "KSA": "🇸🇦", "SCO": "🏴", "SEN": "🇸🇳", "RSA": "🇿🇦", "KOR": "🇰🇷",
    "ESP": "🇪🇸", "SWE": "🇸🇪", "SUI": "🇨🇭", "TUN": "🇹🇳", "TUR": "🇹🇷",
    "USA": "🇺🇸", "URY": "🇺🇾", "UZB": "🇺🇿",
}


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class FootballDataClient:
    base_url = "https://api.football-data.org/v4"

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("FOOTBALL_DATA_TOKEN")
        self.cache = JsonCache(CACHE_DIR)

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def get(self, endpoint: str, params: dict[str, Any] | None = None, max_age: timedelta = timedelta(hours=2)) -> dict[str, Any]:
        params = params or {}
        cache_key = f"{endpoint}?{sorted(params.items())}"
        cached = self.cache.get("football-data", cache_key, max_age)
        if cached is not None:
            return cached
        if not self.token:
            raise RuntimeError("FOOTBALL_DATA_TOKEN is not configured")
        response = requests.get(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers={"X-Auth-Token": self.token},
            params=params,
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errorCode"):
            raise RuntimeError(f"football-data.org error {payload['errorCode']}")
        self.cache.set("football-data", cache_key, payload)
        return payload

    def world_cup_matches(self) -> list[dict[str, Any]]:
        payload = self.get("competitions/WC/matches", max_age=timedelta(hours=2))
        return payload.get("matches", [])

    def matches_on_beijing_date(self, target_date: str, matches: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        from zoneinfo import ZoneInfo

        timezone = ZoneInfo(SETTINGS.timezone)
        source = matches if matches is not None else self.world_cup_matches()
        return [
            match for match in source
            if parse_utc(match["utcDate"]).astimezone(timezone).date().isoformat() == target_date
        ]


def localized_team_name(team: dict[str, Any]) -> str:
    return TEAM_NAMES_ZH.get(team.get("name", ""), team.get("shortName") or team.get("name") or "待定")


def team_flag(team: dict[str, Any]) -> str:
    return TEAM_FLAGS.get(team.get("tla", ""), "🏳")


def api_football_shape(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for match in sorted(matches, key=lambda item: item.get("utcDate", ""), reverse=True):
        full_time = match.get("score", {}).get("fullTime", {})
        converted.append({
            "goals": {"home": full_time.get("home"), "away": full_time.get("away")},
            "teams": {
                "home": {"id": match.get("homeTeam", {}).get("id")},
                "away": {"id": match.get("awayTeam", {}).get("id")},
            },
        })
    return converted
