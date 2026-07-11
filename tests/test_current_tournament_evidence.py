from __future__ import annotations

from datetime import datetime

from pipeline.current_tournament_evidence import EvidenceMatch, apply_current_tournament_evidence


def _evidence(match_id: str, kickoff: str, home: str, away: str, score: tuple[int, int], *, extra: bool = False):
    return EvidenceMatch(
        match_id=match_id,
        kickoff=datetime.fromisoformat(kickoff),
        home_team=home,
        away_team=away,
        home_xg=1.0,
        away_xg=1.0,
        home_goals=score[0],
        away_goals=score[1],
        extra_time_load=extra,
    )


def test_evidence_layer_is_strictly_pre_kickoff_and_stage_independent():
    evidence = [
        _evidence("past", "2026-07-01T12:00:00+08:00", "A", "C", (3, 0)),
        _evidence("future", "2026-07-12T12:00:00+08:00", "A", "D", (9, 0)),
    ]
    seed = {
        "home_team": "A",
        "away_team": "B",
        "kickoff": "2026-07-10T12:00:00+08:00",
        "base_xg": [1.2, 1.0],
        "stage": "GROUP_STAGE",
        "model_decomposition": {},
    }

    apply_current_tournament_evidence(
        [seed],
        "2026-07-10",
        evidence,
        settings={"halfLifeMatches": 2.0, "shrinkage": 5.0, "maxSideXgShift": 0.15},
    )

    payload = seed["tournament_evidence"]
    assert payload["policy"] == "current_tournament_evidence_v1"
    assert payload["home"]["matchesUsed"] == 1
    assert payload["away"]["matchesUsed"] == 0
    assert payload["xgNet"]["home"] > 0
    assert payload["xgNet"]["home"] <= 0.15


def test_extra_time_is_fatigue_metadata_not_a_score_input():
    evidence = [_evidence("past", "2026-07-06T12:00:00+08:00", "A", "C", (1, 1), extra=True)]
    seed = {
        "home_team": "A",
        "away_team": "B",
        "kickoff": "2026-07-10T12:00:00+08:00",
        "base_xg": [1.2, 1.0],
        "model_decomposition": {},
    }

    apply_current_tournament_evidence(
        [seed],
        "2026-07-10",
        evidence,
        settings={"halfLifeMatches": 2.0, "shrinkage": 5.0, "maxSideXgShift": 0.15},
    )

    home = seed["tournament_evidence"]["home"]
    assert home["extraTimeLoad"]
    assert home["fatigueAttackDelta"] == -0.03
    assert home["fatigueDefenseRiskDelta"] == 0.02
