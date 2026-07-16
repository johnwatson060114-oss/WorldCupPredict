from __future__ import annotations

import json
from datetime import datetime

from pipeline.current_tournament_evidence import (
    EvidenceMatch,
    apply_current_tournament_evidence,
    load_evidence_matches,
)


def _evidence(
    match_id: str,
    kickoff: str,
    home: str,
    away: str,
    score: tuple[int, int],
    *,
    extra: bool = False,
    process: float = 0.20,
    post90_load: float = 0.0,
):
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
        process_attack_residual_home=process,
        process_attack_residual_away=-process,
        process_defense_residual_home=-process,
        process_defense_residual_away=process,
        first_half_process_residual_home=process,
        first_half_process_residual_away=-process,
        commentary_credibility_home=1.0,
        commentary_credibility_away=1.0,
        post90_load_home=post90_load,
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
        settings={
            "halfLifeMatches": 2.0,
            "shrinkage": 5.0,
            "commentaryProcessScale": 0.45,
            "commentaryMaxSideXgShift": 0.15,
        },
    )

    payload = seed["tournament_evidence"]
    assert payload["policy"] == "current_tournament_commentary_evidence_v2"
    assert payload["home"]["matchesUsed"] == 1
    assert payload["away"]["matchesUsed"] == 0
    assert payload["xgNet"]["home"] > 0
    assert payload["xgNet"]["home"] <= 0.15


def test_extra_time_is_fatigue_metadata_not_a_score_input():
    evidence = [_evidence(
        "past", "2026-07-06T12:00:00+08:00", "A", "C", (1, 1),
        extra=True, post90_load=0.60,
    )]
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
        settings={
            "halfLifeMatches": 2.0,
            "shrinkage": 5.0,
            "commentaryProcessScale": 0.45,
            "commentaryMaxSideXgShift": 0.15,
            "fatigueAttackPerLoad": -0.05,
            "fatigueDefenseRiskPerLoad": 0.03,
        },
    )

    home = seed["tournament_evidence"]["home"]
    assert home["extraTimeLoad"]
    assert home["post90LoadSeverity"] == 0.6
    assert home["fatigueAttackDelta"] == -0.03
    assert home["fatigueDefenseRiskDelta"] == 0.018


def test_canonical_full_time_cap_overrides_legacy_commentary_cap():
    evidence = [_evidence("past", "2026-07-01T12:00:00+08:00", "A", "C", (3, 0))]
    seed = {
        "home_team": "A",
        "away_team": "B",
        "kickoff": "2026-07-10T12:00:00+08:00",
        "base_xg": [1.2, 1.0],
        "model_decomposition": {},
    }

    apply_current_tournament_evidence([seed], "2026-07-10", evidence, settings={
        "halfLifeMatches": 2.0,
        "shrinkage": 5.0,
        "commentaryProcessScale": 1.0,
        "commentaryMaxSideXgShift": 0.15,
        "maxSideXgShift": 0.02,
    })

    payload = seed["tournament_evidence"]
    assert payload["maxSideXgShift"] == 0.02
    assert abs(payload["xgNet"]["home"]) <= 0.02


def test_zero_canonical_cap_disables_full_time_shift():
    evidence = [_evidence("past", "2026-07-01T12:00:00+08:00", "A", "C", (3, 0))]
    seed = {
        "home_team": "A",
        "away_team": "B",
        "kickoff": "2026-07-10T12:00:00+08:00",
        "base_xg": [1.2, 1.0],
        "model_decomposition": {},
    }

    apply_current_tournament_evidence([seed], "2026-07-10", evidence, settings={
        "halfLifeMatches": 2.0,
        "shrinkage": 5.0,
        "commentaryProcessScale": 1.0,
        "commentaryMaxSideXgShift": 0.15,
        "maxSideXgShift": 0.0,
    })

    payload = seed["tournament_evidence"]
    assert seed["base_xg"] == [1.2, 1.0]
    assert payload["diagnosticOnly"] is True


def test_evidence_loader_deduplicates_aliases_and_timezone_equivalent_kickoffs(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    numeric = {
        "id": "100",
        "kickoff": "2026-07-03T03:00:00+08:00",
        "homeTeam": "\u745e\u58eb",
        "awayTeam": "\u963f\u5c14\u53ca\u5229",
        "modelDecomposition": {"longTermExpectedGoals": {"home": 1.2, "away": 0.8}},
    }
    alias = {
        **numeric,
        "id": "\u745e\u58eb vs \u963f\u5c14\u53ca\u5229\u4e9a",
        "kickoff": "2026-07-02T19:00:00Z",
        "awayTeam": "\u963f\u5c14\u53ca\u5229\u4e9a",
        "modelDecomposition": {"longTermExpectedGoals": {"home": 1.4, "away": 0.7}},
    }
    (history / "early.json").write_text(json.dumps({
        "generatedAt": "2026-07-02T10:00:00Z", "matches": [numeric],
    }), encoding="utf-8")
    (history / "late.json").write_text(json.dumps({
        "generatedAt": "2026-07-02T12:00:00Z", "matches": [alias],
    }), encoding="utf-8")
    settlements = tmp_path / "settlements.json"
    settlements.write_text(json.dumps({"matches": [
        {"matchId": "100", "homeScore": 1, "awayScore": 0},
        {"matchId": alias["id"], "homeScore": 1, "awayScore": 0},
    ]}), encoding="utf-8")
    commentary = tmp_path / "commentary.json"
    commentary.write_text(json.dumps({"matches": []}), encoding="utf-8")

    rows = load_evidence_matches(history, settlements, commentary)

    assert len(rows) == 1
    assert rows[0].match_id == alias["id"]
    assert rows[0].away_team == "\u963f\u5c14\u53ca\u5229\u4e9a"
    assert rows[0].home_xg == 1.4


def test_half_split_uses_only_prior_commentary_process_and_is_bounded():
    evidence = [EvidenceMatch(
        match_id="past", kickoff=datetime.fromisoformat("2026-07-01T12:00:00+08:00"),
        home_team="A", away_team="C", home_xg=1.0, away_xg=1.0,
        home_goals=2, away_goals=0, extra_time_load=False,
        half_home_goals=2, half_away_goals=0,
        process_attack_residual_home=0.2, process_attack_residual_away=-0.2,
        process_defense_residual_home=-0.2, process_defense_residual_away=0.2,
        first_half_process_residual_home=0.2, first_half_process_residual_away=-0.2,
        commentary_credibility_home=1.0, commentary_credibility_away=1.0,
    )]
    seed = {"home_team": "A", "away_team": "B", "kickoff": "2026-07-10T12:00:00+08:00",
            "base_xg": [1.2, 1.0], "model_decomposition": {}}
    apply_current_tournament_evidence([seed], "2026-07-10", evidence, settings={
        "halfLifeMatches": 2.0, "shrinkage": 5.0,
        "commentaryProcessScale": 0.45, "commentaryMaxSideXgShift": 0.0,
        "halfFullEvidence": {"halfLifeMatches": 1.5, "shrinkage": 5.0,
                             "maxFirstHalfXgShift": 0.05, "blend": 0.25},
    })
    split = seed["tournament_evidence"]["halfFullEvidence"]
    assert split["firstHalfXgShift"]["home"] == 0.045
    assert split["blend"] == 0.25
    assert split["firstHalfExpectedGoals"]["home"] + split["secondHalfExpectedGoals"]["home"] == 1.2


def test_half_split_uses_opponent_adjusted_halftime_score_residuals() -> None:
    evidence = [EvidenceMatch(
        match_id="past", kickoff=datetime.fromisoformat("2026-07-01T12:00:00+08:00"),
        home_team="A", away_team="Strong C", home_xg=1.6, away_xg=1.4,
        home_goals=2, away_goals=1, extra_time_load=False,
        half_home_goals=1, half_away_goals=0,
    )]
    seed = {
        "home_team": "A", "away_team": "B",
        "kickoff": "2026-07-10T12:00:00+08:00",
        "base_xg": [1.2, 1.0], "model_decomposition": {},
    }
    apply_current_tournament_evidence([seed], "2026-07-10", evidence, settings={
        "halfLifeMatches": 2.0,
        "shrinkage": 5.0,
        "commentaryProcessScale": 0.0,
        "commentaryMaxSideXgShift": 0.0,
        "halfFullEvidence": {
            "halfLifeMatches": 1.5,
            "shrinkage": 3.0,
            "halfScoreResidualScale": 0.4,
            "maxFirstHalfXgShift": 0.05,
            "blend": 0.5,
        },
    })

    evidence_payload = seed["tournament_evidence"]
    split = evidence_payload["halfFullEvidence"]
    assert evidence_payload["home"]["halfTimeMatchesUsed"] == 1
    assert split["halfScoreResidualScale"] == 0.4
    assert split["firstHalfXgShift"]["home"] > 0
    assert split["firstHalfXgShift"]["home"] <= 0.05
