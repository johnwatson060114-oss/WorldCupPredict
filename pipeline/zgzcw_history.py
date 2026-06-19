from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://cp.zgzcw.com/lottery"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

SCORE_SELECTIONS = (
    "1:0", "2:0", "2:1", "3:0", "3:1", "3:2",
    "4:0", "4:1", "4:2", "5:0", "5:1", "5:2", "胜其他",
    "0:0", "1:1", "2:2", "3:3", "平其他",
    "0:1", "0:2", "1:2", "0:3", "1:3", "2:3",
    "0:4", "1:4", "2:4", "0:5", "1:5", "2:5", "负其他",
)
TOTAL_GOALS_SELECTIONS = ("0", "1", "2", "3", "4", "5", "6", "7+")
HALF_FULL_SELECTIONS = ("胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负")
OUTCOME_SELECTIONS = ("胜", "平", "负")


def sales_issue(kickoff_beijing: str) -> str:
    kickoff = datetime.fromisoformat(kickoff_beijing)
    issue_date = kickoff.date()
    if kickoff.timetz().replace(tzinfo=None) < time(11, 30):
        issue_date -= timedelta(days=1)
    return issue_date.isoformat()


def _values(node: Tag | None) -> list[float]:
    if node is None:
        return []
    values: list[float] = []
    for raw in node.get("value", "").replace("|", " ").split():
        try:
            values.append(abs(float(raw)))
        except ValueError:
            return []
    return values


def _selection_map(values: list[float], selections: tuple[str, ...]) -> dict[str, float]:
    if len(values) != len(selections):
        return {}
    return dict(zip(selections, values, strict=True))


def parse_score_page(html: str) -> dict[str, dict[str, dict[str, float]]]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, dict[str, dict[str, float]]] = {}
    for row in soup.select("tr[id^='tr_']:not([id$='_bf'])"):
        match_id = row.get("id", "").removeprefix("tr_")
        odds = _selection_map(_values(row.select_one(f"input#ht_{match_id}")), SCORE_SELECTIONS)
        if odds:
            result[match_id] = {"比分": odds}
    return result


def parse_compact_page(
    html: str,
    market: str,
    selections: tuple[str, ...],
) -> dict[str, dict[str, dict[str, float]]]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, dict[str, dict[str, float]]] = {}
    for row in soup.select("tr[id^='tr_']"):
        match_id = row.get("id", "").removeprefix("tr_")
        odds = _selection_map(_values(row.select_one(f"input#ht_{match_id}")), selections)
        if odds:
            result[match_id] = {market: odds}
    return result


def parse_spf_page(html: str) -> dict[str, dict[str, dict[str, float]]]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, dict[str, dict[str, float]]] = {}
    for row in soup.select("tr[id^='tr_']"):
        match_id = row.get("id", "").removeprefix("tr_")
        markets: dict[str, dict[str, float]] = {}
        normal = row.select_one(f"#ch_{match_id}_49")
        normal_odds = _selection_map(
            [abs(float(node.get_text(strip=True))) for node in normal.select("a[id^='td_']")] if normal else [],
            OUTCOME_SELECTIONS,
        )
        if normal_odds:
            markets["胜平负"] = normal_odds

        handicap = row.select_one(f"#ch_{match_id}_22")
        handicap_odds = _selection_map(
            [abs(float(node.get_text(strip=True))) for node in handicap.select("a[id^='td_']")] if handicap else [],
            OUTCOME_SELECTIONS,
        )
        handicap_node = handicap.select_one(".rq") if handicap else None
        if handicap_odds and handicap_node:
            line = handicap_node.get_text(strip=True)
            markets["让球胜平负"] = {f"{line} {selection}": odds for selection, odds in handicap_odds.items()}
        if markets:
            result[match_id] = markets
    return result


def _fetch(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def fetch_closing_odds(issue: str) -> dict[str, dict[str, dict[str, float]]]:
    pages = (
        (
            f"{BASE_URL}/jchtplayvsForJsp.action?lotteryId=47&type=jcmini&issue={issue}",
            parse_spf_page,
        ),
        (f"{BASE_URL}/jcplayvsForJsp.action?lotteryId=23&issue={issue}", parse_score_page),
        (
            f"{BASE_URL}/jcplayvsForJsp.action?lotteryId=24&issue={issue}",
            lambda html: parse_compact_page(html, "总进球数", TOTAL_GOALS_SELECTIONS),
        ),
        (
            f"{BASE_URL}/jcplayvsForJsp.action?lotteryId=25&issue={issue}",
            lambda html: parse_compact_page(html, "半全场", HALF_FULL_SELECTIONS),
        ),
    )
    merged: dict[str, dict[str, dict[str, float]]] = {}
    for url, parser in pages:
        for match_id, markets in parser(_fetch(url)).items():
            merged.setdefault(match_id, {}).update(markets)
    return merged


def closing_odds_metadata(issue: str, odds: dict[str, dict[str, float]], checked_at: str) -> dict[str, Any]:
    return {
        "closingOdds": odds,
        "closingOddsSource": "zgzcw.com",
        "closingOddsIssue": issue,
        "closingOddsCheckedAt": checked_at,
    }
