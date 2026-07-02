from __future__ import annotations

import json

from tools.backtest_score_matrix import archived_forecasts, build_report


def test_score_matrix_backtest_includes_cross_day_parlay_matches(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-07-01.json").write_text(
        json.dumps(
            {
                "generatedAt": "2026-06-30T18:00:00+08:00",
                "parlayMatches": [
                    {
                        "id": "m1",
                        "homeTeam": "Home",
                        "awayTeam": "Away",
                        "kickoff": "2026-07-01T01:00:00+08:00",
                        "modelDecomposition": {
                            "adjustedExpectedGoals": {"home": 1.4, "away": 0.9}
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settlements_path = tmp_path / "settlements.json"
    settlements_path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "matchId": "m1",
                        "homeScore": 1,
                        "awayScore": 0,
                        "halfTimeHomeScore": 0,
                        "halfTimeAwayScore": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settlements = {"m1": {"matchId": "m1"}}

    forecasts = archived_forecasts(history_dir, settlements)
    report = build_report(history_dir, settlements_path)

    assert set(forecasts) == {"m1"}
    assert forecasts["m1"]["historySection"] == "parlayMatches"
    assert report["scope"]["matchedSettledMatches"] == 1
    assert report["metrics"]["latestCompleted"]["base"]["matches"] == 1
