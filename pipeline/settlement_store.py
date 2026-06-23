from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable


_SPACE_RE = re.compile(r"\s+")


def normalize_team_name(value: str) -> str:
    aliases = {
        "阿尔及利亚": "阿尔及利",
        "刚果民主共和国": "民主刚果",
        "刚果（金）": "民主刚果",
        "韩国队": "韩国",
    }
    compact = _SPACE_RE.sub("", str(value or "")).lower()
    return aliases.get(compact, compact)


def normalized_match_label(item: dict[str, Any]) -> str:
    label = str(item.get("matchLabel") or item.get("matchId") or "")
    if " vs " in label:
        home, away = label.split(" vs ", 1)
    elif "vs" in label.lower():
        home, away = re.split(r"(?i)vs", label, maxsplit=1)
    else:
        return normalize_team_name(label)
    return f"{normalize_team_name(home)}|{normalize_team_name(away)}"


def settlement_identity(item: dict[str, Any]) -> str:
    fixture_id = item.get("fixtureId") or item.get("apiFixtureId")
    if fixture_id not in (None, ""):
        return f"fixture:{fixture_id}"
    label = normalized_match_label(item)
    settled_at = str(item.get("settledAt") or "")
    kickoff_day = settled_at[:10]
    return f"label:{label}:{kickoff_day}"


def _richness(item: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(bool(item.get("closingOdds"))),
        sum(value not in (None, "") for value in item.values()),
        int(str(item.get("matchId") or "").isdigit()),
    )


def merge_settlement(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    preferred, fallback = (
        (candidate, existing) if _richness(candidate) > _richness(existing) else (existing, candidate)
    )
    merged = dict(fallback)
    merged.update({key: value for key, value in preferred.items() if value not in (None, "")})
    if existing.get("closingOdds") and not candidate.get("closingOdds"):
        for key in ("closingOdds", "closingOddsSource", "closingOddsIssue", "closingOddsCheckedAt"):
            if key in existing:
                merged[key] = existing[key]
    return merged


def deduplicate_settlements(
    records: Iterable[dict[str, Any]],
    fixture_index: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fixture_index = fixture_index or {}
    by_identity: dict[str, dict[str, Any]] = {}
    label_index = {
        normalized_match_label(value): value
        for value in fixture_index.values()
        if normalized_match_label(value)
    }
    for raw in records:
        item = dict(raw)
        fixture = fixture_index.get(str(item.get("fixtureId") or ""))
        if fixture is None:
            fixture = label_index.get(normalized_match_label(item))
        if fixture:
            item["fixtureId"] = fixture.get("fixtureId")
            item.setdefault("matchLabel", fixture.get("matchLabel"))
            item.setdefault("group", fixture.get("group"))
            item.setdefault("matchday", fixture.get("matchday"))
        identity = settlement_identity(item)
        if identity in by_identity:
            by_identity[identity] = merge_settlement(by_identity[identity], item)
        else:
            by_identity[identity] = item

    def sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
        raw = str(item.get("settledAt") or "9999-12-31T23:59:59+00:00").replace("Z", "+00:00")
        try:
            timestamp = datetime.fromisoformat(raw)
        except ValueError:
            timestamp = datetime.max
        return timestamp, settlement_identity(item)

    return sorted(by_identity.values(), key=sort_key)


def assert_unique_settlements(records: Iterable[dict[str, Any]]) -> None:
    identities: set[str] = set()
    duplicates: list[str] = []
    for item in records:
        identity = settlement_identity(item)
        if identity in identities:
            duplicates.append(identity)
        identities.add(identity)
    if duplicates:
        raise ValueError(f"duplicate settlements: {sorted(set(duplicates))}")
