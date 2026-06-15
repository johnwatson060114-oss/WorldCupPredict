from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


def normalize_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def save_immutable_snapshot(directory: Path, source: str, observed_at: str, payload: bytes) -> dict[str, Any]:
    timestamp = normalize_timestamp(observed_at)
    digest = hashlib.sha256(payload).hexdigest()
    safe_source = re.sub(r"[^a-zA-Z0-9._-]+", "-", source).strip("-") or "source"
    path = directory / safe_source / f"{timestamp.replace(':', '').replace('-', '')}-{digest}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise ValueError(f"snapshot collision at {path}")
    if not path.exists():
        path.write_bytes(payload)
    return {"path": path, "sha256": digest, "bytes": len(payload), "observed_at": timestamp}


class HistoricalStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "HistoricalStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS match_revisions (
                match_id TEXT NOT NULL,
                kickoff_utc TEXT NOT NULL,
                competition TEXT NOT NULL,
                stage TEXT NOT NULL,
                venue_attribute TEXT NOT NULL,
                host_team_id TEXT,
                neutral INTEGER NOT NULL,
                home_team_id TEXT NOT NULL,
                away_team_id TEXT NOT NULL,
                home_goals_90 INTEGER,
                away_goals_90 INTEGER,
                home_goals_extra_time INTEGER,
                away_goals_extra_time INTEGER,
                home_penalties INTEGER,
                away_penalties INTEGER,
                home_elo REAL,
                away_elo REAL,
                odds_json TEXT NOT NULL,
                rule_period TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                PRIMARY KEY (match_id, observed_at, source_hash)
            );
            CREATE TABLE IF NOT EXISTS player_revisions (
                player_id TEXT NOT NULL,
                team_id TEXT NOT NULL,
                name TEXT NOT NULL,
                position TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                PRIMARY KEY (player_id, observed_at, source_hash)
            );
            CREATE TABLE IF NOT EXISTS lineup_revisions (
                match_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                team_id TEXT NOT NULL,
                role TEXT NOT NULL,
                shirt_number INTEGER,
                available INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                PRIMARY KEY (match_id, player_id, observed_at, source_hash)
            );
            CREATE TABLE IF NOT EXISTS event_revisions (
                event_id TEXT NOT NULL,
                match_id TEXT NOT NULL,
                player_id TEXT,
                team_id TEXT NOT NULL,
                minute INTEGER,
                event_type TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                occurred_at TEXT,
                observed_at TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                PRIMARY KEY (event_id, observed_at, source_hash)
            );
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    @staticmethod
    def _provenance(record: dict[str, Any]) -> tuple[str, str, str]:
        observed_at = normalize_timestamp(str(record["observed_at"]))
        source_url = str(record.get("source_url") or "").strip()
        source_hash = str(record.get("source_hash") or "").lower()
        if not source_url:
            raise ValueError("source_url is required")
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError("source_hash must be a SHA-256 hex digest")
        return observed_at, source_url, source_hash

    def add_match(self, record: dict[str, Any]) -> None:
        observed_at, source_url, source_hash = self._provenance(record)
        values = {
            **record,
            "kickoff_utc": normalize_timestamp(str(record["kickoff_utc"])),
            "observed_at": observed_at,
            "source_url": source_url,
            "source_hash": source_hash,
            "neutral": int(bool(record.get("neutral", False))),
            "odds_json": json.dumps(record.get("odds", {}), ensure_ascii=False, sort_keys=True),
        }
        columns = (
            "match_id", "kickoff_utc", "competition", "stage", "venue_attribute", "host_team_id", "neutral",
            "home_team_id", "away_team_id", "home_goals_90", "away_goals_90", "home_goals_extra_time",
            "away_goals_extra_time", "home_penalties", "away_penalties", "home_elo", "away_elo", "odds_json",
            "rule_period", "observed_at", "source_url", "source_hash",
        )
        self._insert("match_revisions", columns, values)

    def add_player(self, record: dict[str, Any]) -> None:
        observed_at, source_url, source_hash = self._provenance(record)
        values = {
            **record,
            "valid_from": normalize_timestamp(str(record["valid_from"])),
            "observed_at": observed_at,
            "source_url": source_url,
            "source_hash": source_hash,
        }
        self._insert(
            "player_revisions",
            ("player_id", "team_id", "name", "position", "valid_from", "observed_at", "source_url", "source_hash"),
            values,
        )

    def add_lineup(self, record: dict[str, Any]) -> None:
        observed_at, source_url, source_hash = self._provenance(record)
        values = {
            **record,
            "available": int(bool(record.get("available", True))),
            "observed_at": observed_at,
            "source_url": source_url,
            "source_hash": source_hash,
        }
        self._insert(
            "lineup_revisions",
            ("match_id", "player_id", "team_id", "role", "shirt_number", "available", "observed_at", "source_url", "source_hash"),
            values,
        )

    def add_event(self, record: dict[str, Any]) -> None:
        observed_at, source_url, source_hash = self._provenance(record)
        occurred_at = record.get("occurred_at")
        normalized_occurrence = normalize_timestamp(str(occurred_at)) if occurred_at else None
        if normalized_occurrence and normalized_occurrence > observed_at:
            raise ValueError("an event cannot be observed before it occurs")
        values = {
            **record,
            "occurred_at": normalized_occurrence,
            "detail_json": json.dumps(record.get("detail", {}), ensure_ascii=False, sort_keys=True),
            "observed_at": observed_at,
            "source_url": source_url,
            "source_hash": source_hash,
        }
        self._insert(
            "event_revisions",
            ("event_id", "match_id", "player_id", "team_id", "minute", "event_type", "detail_json", "occurred_at", "observed_at", "source_url", "source_hash"),
            values,
        )

    def _insert(self, table: str, columns: Iterable[str], values: dict[str, Any]) -> None:
        column_list = tuple(columns)
        placeholders = ", ".join("?" for _ in column_list)
        self.connection.execute(
            f"INSERT OR IGNORE INTO {table} ({', '.join(column_list)}) VALUES ({placeholders})",
            tuple(values.get(column) for column in column_list),
        )
        self.connection.commit()

    def _latest_as_of(self, table: str, key_columns: tuple[str, ...], cutoff: str) -> list[dict[str, Any]]:
        normalized_cutoff = normalize_timestamp(cutoff)
        rows = self.connection.execute(
            f"SELECT * FROM {table} WHERE observed_at <= ? ORDER BY observed_at",
            (normalized_cutoff,),
        ).fetchall()
        latest: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            latest[tuple(item[column] for column in key_columns)] = item
        return list(latest.values())

    def matches_as_of(self, cutoff: str, completed_only: bool = False) -> list[dict[str, Any]]:
        normalized_cutoff = normalize_timestamp(cutoff)
        matches = self._latest_as_of("match_revisions", ("match_id",), normalized_cutoff)
        result = []
        for item in matches:
            if completed_only:
                if item["kickoff_utc"] >= normalized_cutoff:
                    continue
                if item["home_goals_90"] is None or item["away_goals_90"] is None:
                    continue
            item["neutral"] = bool(item["neutral"])
            item["odds"] = json.loads(item.pop("odds_json"))
            result.append(item)
        return sorted(result, key=lambda item: item["kickoff_utc"])

    def players_as_of(self, cutoff: str) -> list[dict[str, Any]]:
        return self._latest_as_of("player_revisions", ("player_id",), cutoff)

    def lineups_as_of(self, cutoff: str) -> list[dict[str, Any]]:
        rows = self._latest_as_of("lineup_revisions", ("match_id", "player_id"), cutoff)
        for row in rows:
            row["available"] = bool(row["available"])
        return rows

    def events_as_of(self, cutoff: str) -> list[dict[str, Any]]:
        rows = self._latest_as_of("event_revisions", ("event_id",), cutoff)
        for row in rows:
            row["detail"] = json.loads(row.pop("detail_json"))
        return rows

    def audit_provenance(self) -> dict[str, int]:
        tables = ("match_revisions", "player_revisions", "lineup_revisions", "event_revisions")
        return {
            table: self.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE observed_at = '' OR source_url = '' OR length(source_hash) != 64"
            ).fetchone()[0]
            for table in tables
        }
