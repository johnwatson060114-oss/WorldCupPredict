import json

import pytest

from pipeline.group_stage_form import (
    MAX_TEAM_DIRECTION_XG,
    apply_group_stage_form,
    load_group_stage_profiles,
    team_group_stage_adjustment,
)


def profile(credibility: float = 0.8, objective_status: str = "enabled") -> dict:
    return {
        "team": "A",
        "summary": "group state",
        "matches": [
            {
                "observedMatchday": 1,
                "observedDate": "2026-06-12",
                "credibilityWeight": credibility,
                "credibilityLabels": ["sustained_pressure"],
                "evidenceConfidence": 0.7,
                "objectiveForm": {
                    "attackDelta": 0.08,
                    "defenseDelta": 0.03,
                    "admissionStatus": objective_status,
                },
                "tacticalCandidate": {
                    "attackDelta": 0.02,
                    "defenseDelta": 0.0,
                    "admissionStatus": "enabled",
                },
            },
            {
                "observedMatchday": 3,
                "observedDate": "2026-06-26",
                "credibilityWeight": credibility,
                "credibilityLabels": ["third_round_context_reviewed"],
                "evidenceConfidence": 0.8,
                "objectiveForm": {
                    "attackDelta": 0.12,
                    "defenseDelta": 0.04,
                    "admissionStatus": objective_status,
                },
                "tacticalCandidate": {
                    "attackDelta": 0.03,
                    "defenseDelta": 0.0,
                    "admissionStatus": "enabled",
                },
            },
        ],
        "evidence": {"mode": "minute_by_minute_events"},
    }


def test_group_stage_gate_blocks_untrusted_score_residuals():
    adjustment = team_group_stage_adjustment("A", profile(credibility=0.0), "2026-06-29")

    assert adjustment.combined_attack == 0.0
    assert adjustment.coverage == 0.0


def test_group_stage_applies_only_visible_commentary_supported_matches():
    seeds = [{"home_team": "A", "away_team": "B", "base_xg": [1.2, 1.1], "coverage": 0.8}]

    apply_group_stage_form(seeds, "2026-06-20", {"A": profile()})

    assert seeds[0]["base_xg"][0] > 1.2
    assert seeds[0]["model_decomposition"]["formLayer"] == "group_stage_commentary_gated_v1"
    assert seeds[0]["group_stage_form"]["home"]["observedMatchdays"] == [1]


def test_group_stage_direction_is_bounded():
    strong = profile()
    for match in strong["matches"]:
        match["objectiveForm"]["attackDelta"] = 1.0
        match["tacticalCandidate"]["attackDelta"] = 1.0
    adjustment = team_group_stage_adjustment("A", strong, "2026-06-29")

    assert adjustment.combined_attack == MAX_TEAM_DIRECTION_XG


def test_group_stage_evidence_cannot_smuggle_direct_xg(tmp_path):
    payload = {"teams": [{**profile(), "evidence": {"xg_adjustment": 0.2}}]}
    path = tmp_path / "group-stage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="group-stage evidence"):
        load_group_stage_profiles(path)
