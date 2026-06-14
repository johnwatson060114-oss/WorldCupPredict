from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup, Tag

from .config import SPORTTERY_URLS


@dataclass
class SportteryMatch:
    match_id: str
    lottery_code: str
    kickoff_text: str
    home_team: str
    away_team: str
    handicap: int | None
    win_draw_loss: dict[str, float | None] = field(default_factory=dict)
    handicap_win_draw_loss: dict[str, float | None] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    single_markets: set[str] = field(default_factory=set)


def _number(text: str) -> float | None:
    value = text.strip()
    if value in {"--", "", "未"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _odds(container: Tag | None) -> dict[str, float | None]:
    if container is None:
        return {"胜": None, "平": None, "负": None}
    result: dict[str, float | None] = {}
    for item in container.select(".oddsItem"):
        label = item.find("b")
        value = item.find("label")
        if label:
            result[label.get_text(strip=True)] = _number(value.get_text(strip=True) if value else "")
    return {key: result.get(key) for key in ("胜", "平", "负")}


def parse_spf_html(html: str) -> dict[str, SportteryMatch]:
    soup = BeautifulSoup(html, "html.parser")
    matches: dict[str, SportteryMatch] = {}
    for row in soup.select("tr.listTr[id^='list_']"):
        match_id = row.get("id", "").replace("list_", "")
        teams = row.select(".teams")
        if len(teams) < 3:
            continue
        home = teams[0].get("title") or teams[0].get_text(strip=True)
        away = teams[2].get("title") or teams[2].get_text(strip=True)
        code = row.select_one(".matchTime span")
        kickoff = row.select_one(".b_time")
        handicap_node = row.select_one(".hhadGL")
        handicap_match = re.search(r"([+-]?\d+)", handicap_node.get_text(" ", strip=True) if handicap_node else "")
        single_markets = {
            node.get("title", "")
            for node in row.select("[style*='single.gif']")
            if node.get("title")
        }
        matches[match_id] = SportteryMatch(
            match_id=match_id,
            lottery_code=code.get_text(strip=True) if code else "",
            kickoff_text=kickoff.get_text(strip=True) if kickoff else "",
            home_team=home,
            away_team=away,
            handicap=int(handicap_match.group(1)) if handicap_match else None,
            win_draw_loss=_odds(row.select_one(".hadOdds")),
            handicap_win_draw_loss=_odds(row.select_one(".hhadOdds")),
            single_markets=single_markets,
        )
    if not matches:
        raise ValueError("Sporttery SPF page structure changed: no match rows found")
    return matches


def parse_score_html(html: str, matches: dict[str, SportteryMatch]) -> None:
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("tr[id]"):
        match_id = row.get("id", "").replace("list_", "")
        if match_id not in matches:
            continue
        sibling = row.find_next_sibling("tr")
        if sibling is None:
            continue
        text = sibling.get_text(" ", strip=True)
        pairs = re.findall(r"(\d+:\d+|胜其它|平其它|负其它)\s+(\d+(?:\.\d+)?)", text)
        matches[match_id].scores.update({score: float(odds) for score, odds in pairs})


def fetch_page(url: str) -> str:
    response = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def fetch_sporttery() -> dict[str, SportteryMatch]:
    matches = parse_spf_html(fetch_page(SPORTTERY_URLS["spf"]))
    parse_score_html(fetch_page(SPORTTERY_URLS["score"]), matches)
    return matches


def load_fixture(spf_path: Path, score_path: Path | None = None) -> dict[str, SportteryMatch]:
    matches = parse_spf_html(spf_path.read_text(encoding="utf-8"))
    if score_path and score_path.exists():
        parse_score_html(score_path.read_text(encoding="utf-8"), matches)
    return matches


def filter_by_beijing_date(matches: Iterable[SportteryMatch], target_date: str) -> list[SportteryMatch]:
    prefix = datetime.fromisoformat(target_date).strftime("%m-%d")
    return [match for match in matches if match.kickoff_text.startswith(prefix)]
