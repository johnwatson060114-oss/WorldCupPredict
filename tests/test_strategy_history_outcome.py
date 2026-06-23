import json

from pipeline.strategy_history import build_strategy_history


def test_strategy_history_uses_outcome_decision_instead_of_likely_score(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-23.json").write_text(json.dumps({
        "targetDate": "2026-06-23",
        "generatedAt": "before-match",
        "overallCoverage": 0.8,
        "matches": [{
            "id": "m1",
            "homeTeam": "Norway",
            "awayTeam": "Senegal",
            "likelyScore": "1-1",
            "outcomeProbabilities": {"home": 0.52, "draw": 0.23, "away": 0.25},
            "outcomeDecision": {"selection": "home", "status": "watch"},
        }],
        "portfolios": [],
    }), encoding="utf-8")
    settlements = tmp_path / "settlements.json"
    settlements.write_text(json.dumps({
        "matches": [{"matchId": "m1", "homeScore": 3, "awayScore": 2}],
    }), encoding="utf-8")

    match_review = build_strategy_history(history_dir, settlements)["days"][0]["review"]["matches"][0]

    assert match_review["predictedScore"] == "1-1"
    assert match_review["predictedOutcome"] == "home"
    assert match_review["predictedOutcomeSource"] == "outcomeDecision"
    assert match_review["outcomeCorrect"] is True
