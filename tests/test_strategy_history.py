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


def test_strategy_history_settles_total_goals_and_half_full(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-15.json").write_text(json.dumps({
        "targetDate": "2026-06-15", "generatedAt": "before-match", "overallCoverage": 0.9,
        "portfolios": [{"key": "balanced", "name": "均衡", "stake": 4, "tickets": [
            {"potentialPayout": 6, "legs": [{"matchId": "m1", "market": "总进球数", "selection": "3"}]},
            {"potentialPayout": 8, "legs": [{"matchId": "m1", "market": "半全场", "selection": "平胜"}]},
        ]}],
    }), encoding="utf-8")
    settlements = tmp_path / "settlements.json"
    settlements.write_text(json.dumps({"matches": [{
        "matchId": "m1", "homeScore": 2, "awayScore": 1,
        "halfTimeHomeScore": 0, "halfTimeAwayScore": 0,
    }]}), encoding="utf-8")

    result = build_strategy_history(history_dir, settlements)["days"][0]["strategies"][0]

    assert result["status"] == "settled"
    assert result["payout"] == 14


def test_strategy_history_builds_time_consistent_match_review(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-15.json").write_text(json.dumps({
        "targetDate": "2026-06-15", "generatedAt": "before-match", "overallCoverage": 0.72,
        "matches": [{
            "id": "m1", "homeTeam": "德国", "awayTeam": "库拉索", "likelyScore": "2-0",
            "outcomeProbabilities": {"home": 0.87, "draw": 0.11, "away": 0.02},
        }],
        "portfolios": [],
    }), encoding="utf-8")
    settlements = tmp_path / "settlements.json"
    settlements.write_text(json.dumps({
        "matches": [{"matchId": "m1", "homeScore": 7, "awayScore": 1}],
    }), encoding="utf-8")

    review = build_strategy_history(history_dir, settlements)["days"][0]["review"]

    assert review["snapshotLabel"] == "升级前基线快照"
    assert review["summary"]["outcomeAccuracy"] == 1.0
    assert review["summary"]["exactScoreAccuracy"] == 0.0
    assert review["matches"][0]["goalAbsoluteError"] == 6
    assert "大比分尾部" in review["matches"][0]["diagnosis"]
