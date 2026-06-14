import json

from pipeline.strategy_history import build_strategy_history


def test_strategy_history_settles_single_ticket(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-15.json").write_text(json.dumps({
        "targetDate": "2026-06-15",
        "generatedAt": "2026-06-14T18:00:00+08:00",
        "overallCoverage": 0.9,
        "portfolios": [{
            "key": "balanced",
            "name": "均衡",
            "stake": 10,
            "tickets": [{
                "potentialPayout": 18,
                "legs": [{"matchId": "m1", "market": "胜平负", "selection": "胜"}],
            }],
        }],
    }), encoding="utf-8")
    settlements = tmp_path / "settlements.json"
    settlements.write_text(json.dumps({
        "matches": [{"matchId": "m1", "homeScore": 2, "awayScore": 0}],
    }), encoding="utf-8")

    payload = build_strategy_history(history_dir, settlements)

    result = payload["days"][0]["strategies"][0]
    assert result["status"] == "settled"
    assert result["profit"] == 8
    assert result["roi"] == 0.8
