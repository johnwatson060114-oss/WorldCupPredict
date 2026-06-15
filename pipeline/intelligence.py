from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .config import MANUAL_DIR
from .historical_store import normalize_timestamp


INTELLIGENCE_DIR = MANUAL_DIR / "intelligence"
ALLOWED_CONFIRMATIONS = {"official", "reliable_report", "unverified"}
REQUIRED_KEYS = {
    "event_id", "event_type", "subject", "teams", "target_date", "source_url", "published_at",
    "confirmation", "confidence", "claim", "conflicts", "conclusion",
}
FORBIDDEN_PROBABILITY_KEYS = {"xg_adjustment", "probability_delta", "home_probability", "away_probability"}


def _contains_forbidden_probability_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_PROBABILITY_KEYS.intersection(value)) or any(
            _contains_forbidden_probability_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_probability_key(item) for item in value)
    return False


def validate_intelligence_event(event: dict[str, Any], cutoff: str) -> dict[str, Any]:
    missing = REQUIRED_KEYS - set(event)
    unknown = set(event) - REQUIRED_KEYS
    if missing:
        raise ValueError(f"missing intelligence fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown intelligence fields: {sorted(unknown)}")
    if _contains_forbidden_probability_key(event):
        raise ValueError("intelligence cannot provide probability or xG adjustments")
    published_at = normalize_timestamp(str(event["published_at"]))
    if published_at > normalize_timestamp(cutoff):
        raise ValueError("intelligence was published after the prediction cutoff")
    if event["confirmation"] not in ALLOWED_CONFIRMATIONS:
        raise ValueError("invalid confirmation level")
    confidence = float(event["confidence"])
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if not str(event["source_url"]).startswith("https://"):
        raise ValueError("source_url must be an HTTPS URL")
    if not isinstance(event["teams"], list) or not event["teams"]:
        raise ValueError("teams must be a non-empty list")
    if not isinstance(event["conflicts"], list) or not isinstance(event["conclusion"], dict):
        raise ValueError("conflicts and conclusion must be structured")
    return {**event, "published_at": published_at, "confidence": confidence}


def _canonical_events(events: Iterable[dict[str, Any]]) -> bytes:
    return json.dumps(list(events), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def save_intelligence_snapshot(
    events: Iterable[dict[str, Any]],
    target_date: str,
    generated_at: str,
    directory: Path = INTELLIGENCE_DIR,
) -> Path:
    validated = [validate_intelligence_event(event, generated_at) for event in events]
    digest = hashlib.sha256(_canonical_events(validated)).hexdigest()
    timestamp = normalize_timestamp(generated_at)
    path = directory / target_date / f"{timestamp.replace(':', '').replace('-', '')}-{digest}.json"
    payload = {
        "schema_version": 1,
        "generated_at": timestamp,
        "target_date": target_date,
        "events_sha256": digest,
        "events": validated,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ValueError(f"immutable intelligence snapshot collision at {path}")
    if not path.exists():
        path.write_bytes(content)
    return path


def load_intelligence_snapshot(path: Path, cutoff: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if normalize_timestamp(str(payload["generated_at"])) > normalize_timestamp(cutoff):
        raise ValueError("intelligence snapshot was generated after the prediction cutoff")
    events = [validate_intelligence_event(event, cutoff) for event in payload.get("events", [])]
    digest = hashlib.sha256(_canonical_events(events)).hexdigest()
    if digest != payload.get("events_sha256"):
        raise ValueError("intelligence snapshot hash mismatch")
    return events


def load_daily_intelligence(target_date: str, cutoff: str, directory: Path = INTELLIGENCE_DIR) -> list[dict[str, Any]]:
    folder = directory / target_date
    if not folder.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if normalize_timestamp(str(payload["generated_at"])) > normalize_timestamp(cutoff):
            continue
        for event in load_intelligence_snapshot(path, cutoff):
            latest[event["event_id"]] = event
    return list(latest.values())


def apply_intelligence(seeds: list[dict[str, Any]], events: Iterable[dict[str, Any]]) -> None:
    event_list = list(events)
    for seed in seeds:
        teams = {seed["home_team"], seed["away_team"]}
        matched = [event for event in event_list if teams.intersection(map(str, event["teams"]))]
        if not matched:
            continue
        seed["intelligence"] = matched
        factors = seed.setdefault("factors", [])
        factors.append({
            "label": "赛前结构化情报",
            "direction": "neutral",
            "value": 0.0,
            "note": f"读取 {len(matched)} 条带来源情报；影响系数仅由回测准入",
            "active": False,
            "admissionStatus": "observation_only",
        })
        official_absences = []
        for event in matched:
            conclusion = event["conclusion"]
            if (
                event["confirmation"] == "official"
                and event["event_type"] == "suspension"
                and conclusion.get("availability") == "out"
            ):
                official_absences.append({
                    "team": str(event["teams"][0]),
                    "player": str(event["subject"]["name"]),
                    "status": "suspended",
                    "availability_probability": 0.0,
                    "confidence": 1.0,
                    "source_url": event["source_url"],
                    "observed_at": event["published_at"],
                    "note": event["claim"],
                })
        if official_absences:
            existing = seed.setdefault("confirmed_absences", [])
            known = {(item.get("team"), item.get("player")) for item in existing}
            existing.extend(item for item in official_absences if (item["team"], item["player"]) not in known)
