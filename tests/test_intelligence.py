import json

import pytest

from pipeline.intelligence import (
    apply_intelligence,
    load_intelligence_snapshot,
    save_intelligence_snapshot,
    validate_intelligence_event,
)


def event(**overrides):
    value = {
        "event_id": "intel-1",
        "event_type": "suspension",
        "subject": {"type": "player", "id": "p1", "name": "Player One"},
        "teams": ["A"],
        "target_date": "2026-06-20",
        "source_url": "https://example.test/official-bulletin",
        "published_at": "2026-06-15T08:00:00Z",
        "confirmation": "official",
        "confidence": 1.0,
        "claim": "Player One is suspended for the next match",
        "conflicts": [],
        "conclusion": {"availability": "out", "reason": "automatic suspension"},
    }
    value.update(overrides)
    return value


def test_post_cutoff_intelligence_is_rejected():
    with pytest.raises(ValueError, match="after the prediction cutoff"):
        validate_intelligence_event(event(published_at="2026-06-16T08:00:00Z"), "2026-06-15T12:00:00Z")


def test_llm_output_cannot_directly_adjust_probability_or_xg():
    invalid = event(conclusion={"availability": "out", "xg_adjustment": -0.2})
    with pytest.raises(ValueError, match="cannot provide probability"):
        validate_intelligence_event(invalid, "2026-06-15T12:00:00Z")


def test_snapshot_is_immutable_hashed_and_round_trips(tmp_path):
    path = save_intelligence_snapshot([event()], "2026-06-20", "2026-06-15T12:00:00Z", tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["events_sha256"]) == 64
    assert load_intelligence_snapshot(path, "2026-06-15T12:00:00Z")[0]["event_id"] == "intel-1"
    assert save_intelligence_snapshot([event()], "2026-06-20", "2026-06-15T12:00:00Z", tmp_path) == path


def test_snapshot_generated_after_cutoff_is_rejected(tmp_path):
    path = save_intelligence_snapshot([event()], "2026-06-20", "2026-06-15T12:00:00Z", tmp_path)

    with pytest.raises(ValueError, match="snapshot was generated after"):
        load_intelligence_snapshot(path, "2026-06-15T11:00:00Z")


def test_conflicts_are_preserved_for_audit():
    conflicts = [{"source_url": "https://example.test/report", "claim": "appeal pending"}]
    validated = validate_intelligence_event(event(conflicts=conflicts), "2026-06-15T12:00:00Z")

    assert validated["conflicts"] == conflicts


def test_official_suspension_becomes_fact_but_not_free_probability_adjustment():
    seeds = [{"home_team": "A", "away_team": "B", "factors": []}]
    apply_intelligence(seeds, [event()])

    assert seeds[0]["confirmed_absences"][0]["player"] == "Player One"
    assert seeds[0]["factors"][0]["active"] is False
    assert seeds[0]["factors"][0]["value"] == 0.0
