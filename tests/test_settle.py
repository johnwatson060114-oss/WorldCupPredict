import json

from pipeline import settle
from pipeline.settlement_store import assert_unique_settlements, deduplicate_settlements


def test_source_failure_preserves_existing_settlements(monkeypatch, tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-15.json").write_text(json.dumps({
        "targetDate": "2026-06-15",
        "matches": [],
    }), encoding="utf-8")
    output = tmp_path / "settlements.json"
    existing = {
        "generatedAt": "2026-06-14T18:00:00+08:00",
        "matches": [{"matchId": "m1", "homeScore": 1, "awayScore": 0}],
    }
    output.write_text(json.dumps(existing), encoding="utf-8")

    class UnavailableApiClient:
        enabled = True

        def world_cup_fixtures(self, _target_date):
            raise RuntimeError("plan does not include this season")

    class DisabledFootballDataClient:
        enabled = False

    monkeypatch.setattr(settle, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(settle, "ApiFootballClient", UnavailableApiClient)
    monkeypatch.setattr(settle, "FootballDataClient", DisabledFootballDataClient)

    settle.main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["matches"] == existing["matches"]


def test_football_data_settles_by_fixture_id(monkeypatch, tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-15.json").write_text(json.dumps({
        "targetDate": "2026-06-15",
        "matches": [{
            "id": "lottery-1",
            "apiFixtureId": 537358,
            "homeTeam": "瑞典",
            "awayTeam": "突尼斯",
        }],
    }), encoding="utf-8")

    class FootballDataResultClient:
        enabled = True

        def world_cup_matches(self):
            return [{
                "id": 537358,
                "utcDate": "2026-06-15T02:00:00Z",
                "status": "FINISHED",
                "homeTeam": {"name": "Sweden"},
                "awayTeam": {"name": "Tunisia"},
                "score": {"fullTime": {"home": 2, "away": 1}},
            }]

    class DisabledApiClient:
        enabled = False

    monkeypatch.setattr(settle, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(settle, "FootballDataClient", FootballDataResultClient)
    monkeypatch.setattr(settle, "ApiFootballClient", DisabledApiClient)

    settle.main()

    payload = json.loads((tmp_path / "settlements.json").read_text(encoding="utf-8"))
    assert payload["matches"][0]["matchId"] == "lottery-1"
    assert payload["matches"][0]["fixtureId"] == 537358
    assert payload["matches"][0]["homeScore"] == 2


def test_settlements_deduplicate_numeric_and_label_keys_without_losing_odds():
    records = [
        {
            "matchId": "2040170",
            "fixtureId": 537351,
            "matchLabel": "德国 vs 库拉索",
            "homeScore": 7,
            "awayScore": 1,
            "settledAt": "2026-06-14T17:00:00Z",
            "closingOdds": {"胜平负": {"胜": 1.1}},
        },
        {
            "matchId": "德国 vs 库拉索",
            "matchLabel": "德国 vs 库拉索",
            "homeScore": 7,
            "awayScore": 1,
            "settledAt": "2026-06-14T17:00:00Z",
        },
    ]
    fixture_index = {
        "537351": {
            "fixtureId": 537351,
            "matchLabel": "德国 vs 库拉索",
            "group": "GROUP_E",
            "matchday": 1,
        }
    }

    result = deduplicate_settlements(records, fixture_index)

    assert len(result) == 1
    assert result[0]["fixtureId"] == 537351
    assert result[0]["closingOdds"]["胜平负"]["胜"] == 1.1
    assert_unique_settlements(result)
