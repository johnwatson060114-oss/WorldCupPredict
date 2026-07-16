from __future__ import annotations

import json

from tools.backtest_score_matrix import archived_forecasts, build_report, build_rows


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


def test_archived_forecasts_deduplicate_alias_ids_and_keep_latest_pre_kickoff(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    match = {
        "homeTeam": "France",
        "awayTeam": "Spain",
        "kickoff": "2026-07-15T03:00:00+08:00",
        "expectedGoals": {"home": 1.2, "away": 1.3},
    }
    (history_dir / "early.json").write_text(json.dumps({
        "generatedAt": "2026-07-12T12:00:00+08:00",
        "matches": [{**match, "id": "2040507"}],
    }), encoding="utf-8")
    (history_dir / "late.json").write_text(json.dumps({
        "generatedAt": "2026-07-14T12:00:00+08:00",
        "matches": [{**match, "id": "France vs Spain", "kickoff": "2026-07-14T19:00:00Z"}],
    }), encoding="utf-8")
    (history_dir / "at-kickoff.json").write_text(json.dumps({
        "generatedAt": "2026-07-15T03:00:00+08:00",
        "matches": [{**match, "id": "leaked"}],
    }), encoding="utf-8")
    (history_dir / "missing-generated.json").write_text(json.dumps({
        "matches": [{**match, "id": "missing-generated", "homeTeam": "A"}],
    }), encoding="utf-8")
    (history_dir / "missing-kickoff.json").write_text(json.dumps({
        "generatedAt": "2026-07-14T12:00:00+08:00",
        "matches": [{**match, "id": "missing-kickoff", "homeTeam": "B", "kickoff": None}],
    }), encoding="utf-8")
    settlements = {
        "2040507": {
            "matchId": "2040507", "homeScore": 0, "awayScore": 2,
            "settlementScoreBasis": "90_minutes", "settlementSourceUrl": "https://example.test/result",
        },
        "France vs Spain": {"matchId": "France vs Spain", "homeScore": 0, "awayScore": 2},
        "leaked": {"matchId": "leaked"},
        "missing-generated": {"matchId": "missing-generated"},
        "missing-kickoff": {"matchId": "missing-kickoff"},
    }

    forecasts = archived_forecasts(history_dir, settlements)

    assert set(forecasts) == {"France vs Spain"}
    assert forecasts["France vs Spain"]["historyPath"].endswith("late.json")
    assert forecasts["France vs Spain"]["settlementMatchId"] == "2040507"
    row = build_rows(forecasts, settlements)[0]
    assert row["forecastMatchId"] == "France vs Spain"
    assert row["settlementMatchId"] == "2040507"
    assert row["settlementScoreBasis"] == "90_minutes"
