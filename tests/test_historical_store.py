import hashlib

import pytest

from pipeline.historical_store import HistoricalStore, normalize_timestamp, save_immutable_snapshot


def provenance(payload: bytes, observed_at: str) -> dict:
    return {
        "observed_at": observed_at,
        "source_url": "https://example.test/match-1",
        "source_hash": hashlib.sha256(payload).hexdigest(),
    }


def match_record(payload: bytes, observed_at: str, home_goals: int | None = None) -> dict:
    return {
        "match_id": "match-1",
        "kickoff_utc": "2025-06-15T18:00:00Z",
        "competition": "World Cup",
        "stage": "group",
        "venue_attribute": "neutral",
        "host_team_id": None,
        "neutral": True,
        "home_team_id": "A",
        "away_team_id": "B",
        "home_goals_90": home_goals,
        "away_goals_90": 0 if home_goals is not None else None,
        "home_goals_extra_time": None,
        "away_goals_extra_time": None,
        "home_penalties": None,
        "away_penalties": None,
        "home_elo": 1800,
        "away_elo": 1700,
        "odds": {"home": 2.0, "draw": 3.2, "away": 4.0},
        "rule_period": "2025-laws",
        **provenance(payload, observed_at),
    }


def test_as_of_queries_prevent_post_match_revision_leakage(tmp_path):
    before = b'{"status":"scheduled"}'
    after = b'{"status":"finished","score":"2-0"}'
    with HistoricalStore(tmp_path / "history.sqlite3") as store:
        store.add_match(match_record(before, "2025-06-15T10:00:00Z"))
        store.add_match(match_record(after, "2025-06-15T20:00:00Z", home_goals=2))

        scheduled = store.matches_as_of("2025-06-15T17:00:00Z")
        assert store.matches_as_of("2025-06-15T17:00:00Z", completed_only=True) == []
        completed = store.matches_as_of("2025-06-16T00:00:00Z", completed_only=True)

    assert scheduled[0]["home_goals_90"] is None
    assert len(completed) == 1
    assert completed[0]["home_goals_90"] == 2
    assert completed[0]["home_goals_extra_time"] is None
    assert completed[0]["home_penalties"] is None


def test_players_lineups_and_events_are_versioned_by_publication_time(tmp_path):
    raw = b"official bulletin"
    source = provenance(raw, "2025-06-15T12:00:00Z")
    event_source = provenance(raw, "2025-06-15T20:00:00Z")
    with HistoricalStore(tmp_path / "history.sqlite3") as store:
        store.add_player({"player_id": "p1", "team_id": "A", "name": "Player", "position": "CB", "valid_from": "2025-01-01T00:00:00Z", **source})
        store.add_lineup({"match_id": "match-1", "player_id": "p1", "team_id": "A", "role": "starter", "shirt_number": 4, "available": True, **source})
        store.add_event({"event_id": "e1", "match_id": "match-1", "player_id": "p1", "team_id": "A", "minute": 23, "event_type": "yellow_card", "detail": {"reason": "foul"}, "occurred_at": "2025-06-15T18:23:00Z", **event_source})

        assert store.players_as_of("2025-06-15T11:59:59Z") == []
        assert store.lineups_as_of("2025-06-15T13:00:00Z")[0]["available"] is True
        assert store.events_as_of("2025-06-15T13:00:00Z") == []
        assert store.events_as_of("2025-06-15T21:00:00Z")[0]["detail"] == {"reason": "foul"}
        assert all(value == 0 for value in store.audit_provenance().values())


def test_raw_snapshots_are_content_addressed_and_immutable(tmp_path):
    first = save_immutable_snapshot(tmp_path, "official-feed", "2025-06-15T12:00:00+08:00", b"payload")
    second = save_immutable_snapshot(tmp_path, "official-feed", "2025-06-15T12:00:00+08:00", b"payload")

    assert first == second
    assert first["path"].read_bytes() == b"payload"


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone"):
        normalize_timestamp("2025-06-15T12:00:00")
