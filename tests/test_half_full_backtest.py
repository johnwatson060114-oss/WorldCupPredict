from __future__ import annotations

from tools.backtest_half_full import (
    actual_half_full,
    evaluate_row,
    half_full_probabilities,
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
