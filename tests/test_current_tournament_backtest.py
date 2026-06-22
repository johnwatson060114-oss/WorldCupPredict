from tools.backtest_current_tournament import forecast_diagnostics, settlement_key


def test_settlement_key_prefers_numeric_quote_id_for_legacy_forecast():
    match = {
        "id": "Team A vs Team B",
        "quotes": [{"matchId": "2040999"}],
    }

    assert settlement_key(match) == "2040999"


def test_forecast_diagnostics_reports_total_goal_tail_miss():
    match = {
        "likelyScore": "1-0",
        "quotes": [
            {"market": "总进球数", "selection": label, "modelProbability": probability}
            for label, probability in {
                "0": 0.10,
                "1": 0.30,
                "2": 0.28,
                "3": 0.17,
                "4": 0.08,
                "5": 0.04,
                "6": 0.02,
                "7+": 0.01,
            }.items()
        ],
    }

    diagnostics = forecast_diagnostics(match, 2, 2)

    assert diagnostics["actualTotalBucket"] == "4"
    assert diagnostics["predictedTotalBucket"] == "1"
    assert not diagnostics["totalGoalsExactHit"]
    assert not diagnostics["totalGoalsCoreHit"]
    assert not diagnostics["likelyScoreHit"]
