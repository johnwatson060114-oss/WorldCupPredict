import math

from pipeline.final_four_policy import (
    apply_final_four_policy,
    build_final_four_market_assessment,
    infer_final_four_stage,
    load_final_four_policy,
)
from pipeline.generate import build_match


def test_final_four_stage_prefers_fixture_metadata_and_supports_aliases():
    assert infer_final_four_stage("SEMI_FINALS", "2026-07-20T03:00:00+08:00") == (
        "SEMI_FINAL",
        "fixture_stage",
    )
    assert infer_final_four_stage("bronze final") == ("THIRD_PLACE", "fixture_stage")


def test_final_four_stage_uses_official_beijing_date_fallback():
    assert infer_final_four_stage(None, "2026-07-15T03:00:00+08:00") == (
        "SEMI_FINAL",
        "official_2026_beijing_schedule",
    )
    assert infer_final_four_stage(None, target_date="2026-07-19") == (
        "THIRD_PLACE",
        "official_2026_beijing_schedule",
    )
    assert infer_final_four_stage(None, target_date="2026-07-20") == (
        "FINAL",
        "official_2026_beijing_schedule",
    )


def test_stage_profiles_are_commentary_trained_and_validation_gated():
    policy = load_final_four_policy()
    candidates = {
        stage: profile["candidateTotalXgMultiplier"]
        for stage, profile in policy["stageProfiles"].items()
    }
    assert len(set(candidates.values())) == 3

    seed = {
        "home_team": "France",
        "away_team": "Spain",
        "kickoff": "2026-07-15T03:00:00+08:00",
        "base_xg": [1.2, 1.3],
        "coverage": 0.80,
    }
    apply_final_four_policy([seed], "2026-07-15", policy)

    context = seed["final_four_context"]
    assert seed["stage"] == "SEMI_FINAL"
    assert not context["diagnosticOnly"]
    assert context["matrixAdjustmentApplied"]
    assert seed["base_xg"] != [1.2, 1.3]
    assert math.isclose(seed["coverage"], 0.78)
    assert context["candidateExpectedGoals"] != context["preStageExpectedGoals"]
    assert context["validationStatus"] == "commentary_trained_safety_gated"

    final_seed = {**seed, "stage": "FINAL", "base_xg": [1.2, 1.3], "coverage": 0.80}
    apply_final_four_policy([final_seed], "2026-07-20", policy)
    assert final_seed["final_four_context"]["diagnosticOnly"]
    assert final_seed["base_xg"] == [1.2, 1.3]


def test_market_assessment_requires_gap_and_confidence_lower_bound():
    context = {
        "stage": "SEMI_FINAL",
        "stageParameters": {
            "valueProbabilityGap": 0.05,
            "uncertaintyMultiplier": 1.1,
        },
    }
    assessment = build_final_four_market_assessment(
        context,
        {"home": 0.75, "draw": 0.15, "away": 0.10},
        {"home": 0.55, "draw": 0.25, "away": 0.20},
        0.95,
    )

    assert assessment is not None
    assert assessment["status"] == "value_identified"
    assert assessment["valueSelections"] == ["home"]
    assert assessment["confidence95"]["home"][0] > 0.55


def test_market_assessment_reports_no_value_when_market_is_inside_interval():
    context = {
        "stage": "FINAL",
        "stageParameters": {
            "valueProbabilityGap": 0.06,
            "uncertaintyMultiplier": 1.15,
        },
    }
    assessment = build_final_four_market_assessment(
        context,
        {"home": 0.42, "draw": 0.30, "away": 0.28},
        {"home": 0.39, "draw": 0.31, "away": 0.30},
        0.80,
    )

    assert assessment is not None
    assert assessment["status"] == "no_clear_value"
    assert assessment["valueSelections"] == []


def test_final_four_match_contract_uses_one_regular_time_matrix():
    seed = {
        "home_team": "France",
        "away_team": "Spain",
        "kickoff": "2026-07-15T03:00:00+08:00",
        "base_xg": [1.2, 1.3],
        "coverage": 0.80,
        "missing_data": [],
    }
    apply_final_four_policy([seed], "2026-07-15")

    match = build_match(seed, None, "2026-07-13T15:22:00+08:00")

    assert match["stage"] == "SEMI_FINAL"
    assert match["predictionTarget"] == "90_minutes"
    assert match["drawRisk"]["status"] == "matrix_authoritative"
    assert match["halfFullSignal"]["assistWeight"] == 0.0
    assert match["finalFourModel"]["scoreMatrix"] == "calibrated_regular_time_score_matrix"
    assert len(match["scoreProbabilities"]) == 8
    assert math.isclose(sum(match["outcomeProbabilities"].values()), 1.0, abs_tol=1e-4)
