from __future__ import annotations

from tools.backtest_half_full import (
    actual_half_full,
    archived_forecasts,
    evaluate_row,
    half_full_probabilities,
    supplemental_score_matrix_forecasts,
    summarize,
)


def test_actual_half_full_label_uses_halftime_and_fulltime_results():
    settlement = {
        "homeScore": 2,
        "awayScore": 1,
        "halfTimeHomeScore": 0,
        "halfTimeAwayScore": 0,
    }

    assert actual_half_full(settlement) == "\u5e73\u80dc"


def test_actual_half_full_excludes_missing_halftime_scores():
    settlement = {
        "homeScore": 2,
        "awayScore": 1,
        "halfTimeHomeScore": None,
        "halfTimeAwayScore": 0,
    }

    assert actual_half_full(settlement) is None


def test_half_full_probabilities_normalize_archived_quotes():
    match = {
        "quotes": [
            {"market": "\u534a\u5168\u573a", "selection": "\u80dc\u80dc", "modelProbability": 2},
            {"market": "\u534a\u5168\u573a", "selection": "\u5e73\u80dc", "modelProbability": 1},
            {"market": "\u6bd4\u5206", "selection": "1:0", "modelProbability": 1},
        ]
    }

    probabilities = half_full_probabilities(match)

    assert probabilities["\u80dc\u80dc"] == 2 / 3
    assert probabilities["\u5e73\u80dc"] == 1 / 3
    assert probabilities["\u80dc\u5e73"] == 0


def test_evaluate_row_computes_top1_and_top3_hits():
    forecast = {
        "historyPath": "public/data/history/2026-06-15.json",
        "historyGeneratedAt": "2026-06-15T10:00:00+08:00",
        "match": {
            "id": "m1",
            "homeTeam": "Home",
            "awayTeam": "Away",
            "outcomeProbabilities": {"home": 0.45, "draw": 0.30, "away": 0.25},
            "quotes": [
                {"market": "\u534a\u5168\u573a", "selection": "\u80dc\u80dc", "modelProbability": 0.5},
                {"market": "\u534a\u5168\u573a", "selection": "\u5e73\u80dc", "modelProbability": 0.3},
                {"market": "\u534a\u5168\u573a", "selection": "\u5e73\u5e73", "modelProbability": 0.2},
            ],
        },
    }
    settlement = {
        "homeScore": 2,
        "awayScore": 1,
        "halfTimeHomeScore": 0,
        "halfTimeAwayScore": 0,
    }

    row = evaluate_row("m1", forecast, settlement)

    assert row is not None
    assert row["actual"] == "\u5e73\u80dc"
    assert row["predicted"] == "\u80dc\u80dc"
    assert row["hit"] is False
    assert row["top3Hit"] is True


def test_evaluate_row_classifies_post_group_date_without_legacy_context_as_knockout():
    forecast = {
        "historyPath": "public/data/history/2026-07-15.json",
        "historyGeneratedAt": "2026-07-13T16:00:00+08:00",
        "match": {
            "id": "m2",
            "kickoff": "2026-07-15T03:00:00+08:00",
            "homeTeam": "France",
            "awayTeam": "Spain",
            "outcomeProbabilities": {"home": 0.33, "draw": 0.27, "away": 0.40},
            "quotes": [
                {"market": "\u534a\u5168\u573a", "selection": "\u8d1f\u8d1f", "modelProbability": 0.4},
                {"market": "\u534a\u5168\u573a", "selection": "\u5e73\u8d1f", "modelProbability": 0.3},
                {"market": "\u534a\u5168\u573a", "selection": "\u5e73\u5e73", "modelProbability": 0.3},
            ],
        },
    }
    settlement = {
        "homeScore": 0,
        "awayScore": 2,
        "halfTimeHomeScore": 0,
        "halfTimeAwayScore": 1,
    }

    assert evaluate_row("m2", forecast, settlement)["stage"] == "knockout"


def test_summarize_reports_model_and_in_sample_baseline_accuracy():
    rows = [
        {"actual": "\u5e73\u80dc", "predicted": "\u5e73\u80dc", "hit": True, "top3Hit": True, "logLoss": 1.0, "brier": 0.5, "actualProbability": 0.3},
        {"actual": "\u5e73\u80dc", "predicted": "\u80dc\u80dc", "hit": False, "top3Hit": True, "logLoss": 2.0, "brier": 0.7, "actualProbability": 0.1},
        {"actual": "\u80dc\u80dc", "predicted": "\u80dc\u80dc", "hit": True, "top3Hit": True, "logLoss": 0.5, "brier": 0.2, "actualProbability": 0.6},
    ]

    summary = summarize(rows)

    assert summary["matches"] == 3
    assert summary["hits"] == 2
    assert summary["accuracy"] == 2 / 3
    assert summary["inSampleMostCommonActual"] == "\u5e73\u80dc"
    assert summary["inSampleMostCommonAccuracy"] == 2 / 3


def test_supplemental_score_matrix_forecasts_reconstruct_half_full_when_archived_quotes_missing(tmp_path):
    artifact = tmp_path / "score-matrix.json"
    artifact.write_text(
        """{
  "latestMatches": [
    {
      "matchId": "2040345",
      "homeTeam": "Home",
      "awayTeam": "Away",
      "kickoff": "2026-07-01T01:00:00+08:00",
      "historyPath": "public/data/history/2026-07-01.json",
      "historyGeneratedAt": "2026-06-30T18:37:21+08:00",
      "stage": "knockout",
      "xg": {"home": 0.9, "away": 2.0}
    }
  ]
}""",
        encoding="utf-8",
    )
    settlements = {
        "2040345": {
            "homeScore": 1,
            "awayScore": 2,
            "halfTimeHomeScore": 0,
            "halfTimeAwayScore": 1,
        }
    }

    forecasts = supplemental_score_matrix_forecasts(artifact, settlements, {})

    assert set(forecasts) == {"2040345"}
    match = forecasts["2040345"]["match"]
    assert match["halfFullSource"] == "reconstructed_from_archived_xg"
    assert len([quote for quote in match["quotes"] if quote["market"] == "\u534a\u5168\u573a"]) == 9
    assert abs(sum(match["outcomeProbabilities"].values()) - 1) < 1e-9


def test_archived_forecasts_include_cross_day_parlay_matches(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-07-01.json").write_text(
        """{
  "generatedAt": "2026-06-30T18:00:00+08:00",
  "parlayMatches": [
    {
      "id": "m1",
      "homeTeam": "Home",
      "awayTeam": "Away",
      "kickoff": "2026-07-01T01:00:00+08:00",
      "quotes": [
        {"market": "\u534a\u5168\u573a", "selection": "\u80dc\u80dc", "modelProbability": 0.5},
        {"market": "\u534a\u5168\u573a", "selection": "\u5e73\u80dc", "modelProbability": 0.5}
      ]
    }
  ]
}""",
        encoding="utf-8",
    )
    settlements = {"m1": {"matchId": "m1", "homeScore": 1, "awayScore": 0, "halfTimeHomeScore": 0, "halfTimeAwayScore": 0}}

    forecasts = archived_forecasts(history_dir, settlements)

    assert set(forecasts) == {"m1"}
    assert forecasts["m1"]["historySection"] == "parlayMatches"
