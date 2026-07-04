import json

import pytest

from pipeline.knockout_round32_form import (
    apply_knockout_round32_form,
    load_knockout_round32_profiles,
    team_round32_adjustment,
)


def profile(labels: list[str]) -> dict:
    return {
        "team": "A",
        "summary": "round32 process profile",
        "matches": [
            {
                "observedDate": "2026-07-04",
                "labels": labels,
                "evidenceConfidence": 1.0,
                "sourceUrls": ["https://example.test/report"],
            }
        ],
    }


def test_round32_fatigue_reduces_next_knockout_mean_and_coverage():
    seeds = [
        {
            "home_team": "A",
            "away_team": "B",
            "base_xg": [1.8, 1.0],
            "coverage": 0.80,
            "stage": "ROUND_OF_16",
        }
    ]

    apply_knockout_round32_form(
        seeds,
        "2026-07-05",
        {"A": profile(["extra_time_load", "visible_cramp_or_fatigue"])},
    )

    assert seeds[0]["base_xg"][0] < 1.8
    assert seeds[0]["base_xg"][1] > 1.0
    assert seeds[0]["coverage"] < 0.80
    assert seeds[0]["knockout_round32_form"]["predictionTarget"] == "90_minutes"
    assert seeds[0]["knockout_round32_form"]["homeLatePressure"]["attackMultiplier"] < 1.0


def test_round32_profiles_reject_direct_probability_fields(tmp_path):
    path = tmp_path / "round32.json"
    path.write_text(
        json.dumps(
            {
                "teams": [
                    {
                        "team": "A",
                        "matches": [
                            {
                                "observedDate": "2026-07-04",
                                "labels": ["extra_time_load"],
                                "probability_delta": 0.1,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_knockout_round32_profiles(path)


def test_round32_future_evidence_is_blocked_by_cutoff():
    result = team_round32_adjustment("A", profile(["extra_time_load"]), "2026-07-04")

    assert result.labels == ()
    assert result.attack_delta == 0.0
