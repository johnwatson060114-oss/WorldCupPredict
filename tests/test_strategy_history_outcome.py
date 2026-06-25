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


def test_strategy_history_matches_settlements_by_match_label(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-06-24.json").write_text(json.dumps({
        "targetDate": "2026-06-24",
        "generatedAt": "before-match",
        "overallCoverage": 0.8,
        "matches": [{
            "id": "Portugal vs Uzbekistan",
            "homeTeam": "Portugal",
            "awayTeam": "Uzbekistan",
            "likelyScore": "1-1",
            "outcomeProbabilities": {"home": 0.59, "draw": 0.22, "away": 0.19},
            "outcomeDecision": {"selection": "home", "status": "watch"},
        }],
        "portfolios": [],
    }), encoding="utf-8")
    settlements = tmp_path / "settlements.json"
    settlements.write_text(json.dumps({
        "matches": [{
            "matchId": "537405",
            "fixtureId": 537405,
            "matchLabel": "Portugal vs Uzbekistan",
            "homeScore": 5,
            "awayScore": 0,
        }],
    }), encoding="utf-8")

    review = build_strategy_history(history_dir, settlements)["days"][0]["review"]

    assert review["summary"]["matchCount"] == 1
    assert review["matches"][0]["actualScore"] == "5-0"
    assert review["matches"][0]["outcomeCorrect"] is True
