from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup, Tag

from .config import SETTINGS, SPORTTERY_SNAPSHOT, SPORTTERY_URLS


@dataclass
class SportteryMatch:
    match_id: str
    lottery_code: str
    kickoff_text: str
    home_team: str
    away_team: str
    match_date: str = ""  # "2026-06-18" — preserved for date-based filtering
    league_name: str = ""  # "世界杯" — preserved for league filtering
    handicap: int | None = None
    win_draw_loss: dict[str, float | None] = field(default_factory=dict)
    handicap_win_draw_loss: dict[str, float | None] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    total_goals: dict[str, float] = field(default_factory=dict)
    half_full: dict[str, float] = field(default_factory=dict)
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


SPORTTERY_API_BASE = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry"


def _api_url(pool_codes: str) -> str:
    return f"{SPORTTERY_API_BASE}?channel=c&poolCode={pool_codes}"


def _api_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://m.sporttery.cn/",
    }


def _fetch_raw_payloads() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fetch raw JSON payloads from the 4 sporttery API pools.

    Returns (spf, score, ttg, hafu) — the hafu pool is separate because
    the API rejects ``poolCode=ttg,hafu`` with 403.
    """
    spf_r = requests.get(_api_url("hhad,had"), headers=_api_headers(), timeout=30)
    spf_r.raise_for_status()
    score_r = requests.get(_api_url("crs"), headers=_api_headers(), timeout=30)
    score_r.raise_for_status()
    ttg_r = requests.get(_api_url("ttg"), headers=_api_headers(), timeout=30)
    ttg_r.raise_for_status()
    hafu_r = requests.get(_api_url("hafu"), headers=_api_headers(), timeout=30)
    hafu_r.raise_for_status()
    return spf_r.json(), score_r.json(), ttg_r.json(), hafu_r.json()


def fetch_sporttery_api() -> dict[str, SportteryMatch]:
    """Fetch live odds from the sporttery.cn JSON API (no HTML scraping needed)."""
    spf, score, ttg, hafu = _fetch_raw_payloads()
    return parse_api_snapshots(spf, score, _merge_ttg_hafu(ttg, hafu))


def _api_payload_to_cache(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"endpoint": endpoint, "payload": payload}


def save_live_snapshot(
    spf_payload: dict[str, Any],
    score_payload: dict[str, Any],
    ttg_payload: dict[str, Any],
    hafu_payload: dict[str, Any],
    path: Path = SPORTTERY_SNAPSHOT,
) -> None:
    """Cache the raw API responses so the pipeline is reproducible offline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schemaVersion": 2,
        "fetchedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "spf": _api_payload_to_cache(_api_url("hhad,had"), spf_payload),
        "score": _api_payload_to_cache(_api_url("crs"), score_payload),
        "ttg": _api_payload_to_cache(_api_url("ttg"), ttg_payload),
        "hafu": _api_payload_to_cache(_api_url("hafu"), hafu_payload),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_sporttery() -> dict[str, SportteryMatch]:
    # Try cached snapshot first (fast, offline-safe)
    snapshot = load_live_snapshot()
    if snapshot is not None:
        mixed = snapshot.get("mixed", {}).get("payload")
        if mixed is None:
            # schema v2: ttg + hafu stored separately
            ttg_p = snapshot.get("ttg", {}).get("payload", {})
            hafu_p = snapshot.get("hafu", {}).get("payload", {})
            mixed = _merge_ttg_hafu(ttg_p, hafu_p)
        return parse_api_snapshots(snapshot["spf"]["payload"], snapshot["score"]["payload"], mixed)

    # Fresh fetch from sporttery JSON API
    try:
        spf, score, ttg, hafu = _fetch_raw_payloads()
        matches = parse_api_snapshots(spf, score, _merge_ttg_hafu(ttg, hafu))
        try:
            save_live_snapshot(spf, score, ttg, hafu)
        except OSError:
            pass
        return matches
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise ValueError(f"Sporttery API fetch failed: {exc}") from exc


def _merge_ttg_hafu(ttg_data: dict[str, Any], hafu_data: dict[str, Any]) -> dict[str, Any]:
    """Merge hafu pool data into ttg payload so parse_api_snapshots can read both."""
    import copy
    mixed = copy.deepcopy(ttg_data)
    hafu_val = hafu_data.get("value", {})
    if "value" not in mixed:
        mixed["value"] = {}
    hafu_by_id: dict[str, dict[str, Any]] = {}
    for group in hafu_val.get("matchInfoList", []):
        for m in group.get("subMatchList", []):
            hafu_by_id[str(m.get("matchId", ""))] = m
    for group in mixed["value"].get("matchInfoList", []):
        for m in group.get("subMatchList", []):
            mid = str(m.get("matchId", ""))
            if mid in hafu_by_id:
                m["hafu"] = hafu_by_id[mid].get("hafu", {})
                existing = {str(p.get("poolCode", "")) for p in m.get("poolList", [])}
                for p in hafu_by_id[mid].get("poolList", []):
                    if str(p.get("poolCode", "")) not in existing:
                        m.setdefault("poolList", []).append(p)
    return mixed


def _flatten(payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups = payload.get("value", {}).get("matchInfoList", [])
    return [match for group in groups for match in group.get("subMatchList", [])]


def _pool_selling(match: dict[str, Any], pool_code: str) -> bool:
    return any(
        str(pool.get("poolCode", "")).lower() == pool_code
        and str(pool.get("poolStatus", "")).lower() == "selling"
        for pool in match.get("poolList", [])
    )


def _api_odds(match: dict[str, Any], pool_code: str) -> dict[str, float | None]:
    if not _pool_selling(match, pool_code):
        return {"胜": None, "平": None, "负": None}
    values = match.get(pool_code, {})
    return {"胜": _number(str(values.get("h", ""))), "平": _number(str(values.get("d", ""))), "负": _number(str(values.get("a", "")))}


def _score_odds(match: dict[str, Any]) -> dict[str, float]:
    if not _pool_selling(match, "crs"):
        return {}
    result: dict[str, float] = {}
    for key, raw_value in match.get("crs", {}).items():
        value = _number(str(raw_value))
        if value is None:
            continue
        score = re.fullmatch(r"s(\d{2})s(\d{2})", key)
        if score:
            result[f"{int(score.group(1))}:{int(score.group(2))}"] = value
        elif key == "s1sh":
            result["胜其它"] = value
        elif key == "s1sd":
            result["平其它"] = value
        elif key == "s1sa":
            result["负其它"] = value
    return result


def _total_goals_odds(match: dict[str, Any]) -> dict[str, float]:
    if not _pool_selling(match, "ttg"):
        return {}
    result: dict[str, float] = {}
    for goals in range(8):
        value = _number(str(match.get("ttg", {}).get(f"s{goals}", "")))
        if value is not None:
            result["7+" if goals == 7 else str(goals)] = value
    return result


def _half_full_odds(match: dict[str, Any]) -> dict[str, float]:
    if not _pool_selling(match, "hafu"):
        return {}
    labels = {
        "hh": "胜胜", "hd": "胜平", "ha": "胜负",
        "dh": "平胜", "dd": "平平", "da": "平负",
        "ah": "负胜", "ad": "负平", "aa": "负负",
    }
    result: dict[str, float] = {}
    for key, label in labels.items():
        value = _number(str(match.get("hafu", {}).get(key, "")))
        if value is not None:
            result[label] = value
    return result


def _single_markets(match: dict[str, Any]) -> set[str]:
    names = {
        "had": "胜平负", "hhad": "让球胜平负", "crs": "比分",
        "ttg": "总进球数", "hafu": "半全场",
    }
    return {
        names[code]
        for pool in match.get("poolList", [])
        if (code := str(pool.get("poolCode", "")).lower()) in names
        and str(pool.get("single", "0")).lower() in {"1", "true"}
    }


def parse_api_snapshots(
    spf_payload: dict[str, Any],
    score_payload: dict[str, Any],
    mixed_payload: dict[str, Any] | None = None,
) -> dict[str, SportteryMatch]:
    matches: dict[str, SportteryMatch] = {}
    for item in _flatten(spf_payload):
        match_id = str(item.get("matchId", ""))
        if not match_id:
            continue
        match_date = str(item.get("matchDate", ""))
        kickoff = f"{match_date[5:]} {str(item.get('matchTime', ''))[:5]}" if len(match_date) >= 10 else ""
        handicap_text = str(item.get("hhad", {}).get("goalLine", ""))
        handicap_match = re.search(r"([+-]?\d+)", handicap_text)
        matches[match_id] = SportteryMatch(
            match_id=match_id,
            lottery_code=str(item.get("matchNumStr", "")),
            kickoff_text=kickoff,
            home_team=str(item.get("homeTeamAbbName") or item.get("homeTeamAllName") or ""),
            away_team=str(item.get("awayTeamAbbName") or item.get("awayTeamAllName") or ""),
            match_date=match_date,
            league_name=str(item.get("leagueAllName") or item.get("leagueAbbName") or ""),
            handicap=int(handicap_match.group(1)) if handicap_match else None,
            win_draw_loss=_api_odds(item, "had"),
            handicap_win_draw_loss=_api_odds(item, "hhad"),
            single_markets=_single_markets(item),
        )
    for item in _flatten(score_payload):
        match_id = str(item.get("matchId", ""))
        if match_id in matches:
            matches[match_id].scores = _score_odds(item)
            matches[match_id].single_markets.update(_single_markets(item))
    for item in _flatten(mixed_payload or {}):
        match_id = str(item.get("matchId", ""))
        if match_id in matches:
            matches[match_id].total_goals = _total_goals_odds(item)
            matches[match_id].half_full = _half_full_odds(item)
            matches[match_id].single_markets.update(_single_markets(item))
    if not matches:
        raise ValueError("Sporttery API snapshot structure changed: no matches found")
    return matches


def load_live_snapshot(path: Path = SPORTTERY_SNAPSHOT) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    fetched_at = datetime.fromisoformat(payload["fetchedAt"].replace("Z", "+00:00")).astimezone(UTC)
    if datetime.now(UTC) - fetched_at > timedelta(minutes=SETTINGS.odds_max_age_minutes):
        return None
    if not payload.get("spf", {}).get("payload") or not payload.get("score", {}).get("payload"):
        raise ValueError("Sporttery browser snapshot is incomplete")
    return payload


def load_fixture(spf_path: Path, score_path: Path | None = None) -> dict[str, SportteryMatch]:
    matches = parse_spf_html(spf_path.read_text(encoding="utf-8"))
    if score_path and score_path.exists():
        parse_score_html(score_path.read_text(encoding="utf-8"), matches)
    return matches


def filter_by_beijing_date(matches: Iterable[SportteryMatch], target_date: str) -> list[SportteryMatch]:
    prefix = datetime.fromisoformat(target_date).strftime("%m-%d")
    return [match for match in matches if match.kickoff_text.startswith(prefix)]
