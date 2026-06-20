import json

import pytest

from pipeline.tournament_form import (
    CURRENT_TOURNAMENT_FORM_MULTIPLIER,
    MAX_TEAM_DIRECTION_XG,
    apply_tournament_form,
    form_decay,
    load_first_round_profiles,
    team_form_adjustment,
)


def profile(attack: float = 0.3, defense: float = -0.3):
    return {
        "team": "A",
        "observedMatchday": 1,
        "observedDate": "2026-06-17",
        "evidenceConfidence": 0.7,
        "summary": "首轮状态",
        "commentaryEvidence": {"mode": "text_only", "labels": []},
        "objectiveForm": {
            "attackDelta": attack,
            "defenseDelta": defense,
            "admissionStatus": "enabled",
        },
    }


def test_team_form_caps_each_direction_and_decays_after_two_matchdays():
    early = team_form_adjustment("A", profile(), "2026-06-27")
    later = team_form_adjustment("A", profile(), "2026-07-03")
    assert early.attack_delta == MAX_TEAM_DIRECTION_XG
    assert early.defense_delta == -MAX_TEAM_DIRECTION_XG
    assert form_decay(1, 3) == 1.0
    assert 0 < later.attack_delta < early.attack_delta
    assert CURRENT_TOURNAMENT_FORM_MULTIPLIER > 1


def test_form_layer_adjusts_xg_without_mutating_long_term_baseline():
    seeds = [{"home_team": "A", "away_team": "B", "base_xg": [1.5, 1.1]}]
    profiles = {
        "A": profile(attack=0.08, defense=0.04),
        "B": {**profile(attack=-0.02, defense=-0.03), "team": "B"},
    }
    apply_tournament_form(seeds, "2026-06-20", profiles)
    decomposition = seeds[0]["model_decomposition"]
    assert decomposition["longTermExpectedGoals"] == {"home": 1.5, "away": 1.1}
    assert seeds[0]["base_xg"] != [1.5, 1.1]
    assert seeds[0]["tournament_form"]["commentaryMode"] == "text_only"


def test_postmatch_form_is_not_visible_to_earlier_forecast():
    adjustment = team_form_adjustment("A", profile(attack=0.08), "2026-06-16")
    assert adjustment.attack_delta == 0
    assert adjustment.admission_status == "future_unavailable"


def test_commentary_cannot_smuggle_xg_adjustment(tmp_path):
    payload = {
        "teams": [{
            **profile(),
            "commentaryEvidence": {"mode": "text_only", "xg_adjustment": 0.2},
        }],
    }
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="commentary evidence"):
        load_first_round_profiles(path)
