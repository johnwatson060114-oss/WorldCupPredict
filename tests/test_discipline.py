from pipeline.discipline import DisciplineEngine, DisciplineRules, PlayerDisciplineState


def card(player: str, team: str, event_type: str) -> dict:
    return {"player_id": player, "team_id": team, "event_type": event_type}


def test_official_2026_rules_are_versioned_and_auditable():
    rules = DisciplineRules.load()

    assert rules.yellow_card_threshold == 2
    assert rules.clear_single_yellows_after_stages == {"group", "quarterfinal"}
    assert rules.team_conduct_points["yellow_and_direct_red"] == -5
    assert all(url.startswith("https://") for url in rules.source_urls)


def test_two_yellows_in_different_matches_trigger_next_match_suspension():
    engine = DisciplineEngine()
    states: dict[str, PlayerDisciplineState] = {}
    engine.process_match("m1", "group", [card("p1", "A", "yellow")], states)
    result = engine.process_match("m2", "group", [card("p1", "A", "yellow")], states)

    assert result.suspended_next_match == ("p1",)
    assert states["p1"].caution_match_ids == []
    assert engine.start_team_match("A", states) == ["p1"]
    assert states["p1"].served_suspensions == 1


def test_two_yellows_in_same_match_are_one_indirect_red_not_accumulation():
    engine = DisciplineEngine()
    states: dict[str, PlayerDisciplineState] = {}
    result = engine.process_match(
        "m1", "group", [card("p1", "A", "yellow"), card("p1", "A", "second_yellow")], states
    )

    assert states["p1"].pending_suspensions == 1
    assert states["p1"].caution_match_ids == []
    assert result.team_conduct_scores == {"A": -3}


def test_direct_red_after_yellow_uses_single_five_point_deduction():
    engine = DisciplineEngine()
    states: dict[str, PlayerDisciplineState] = {}
    result = engine.process_match(
        "m1", "group", [card("p1", "A", "yellow"), card("p1", "A", "direct_red")], states
    )

    assert result.team_conduct_scores == {"A": -5}
    assert states["p1"].pending_suspensions == 1


def test_stage_reset_clears_only_untriggered_yellows():
    engine = DisciplineEngine()
    states = {
        "p1": PlayerDisciplineState("p1", "A", caution_match_ids=["m1"]),
        "p2": PlayerDisciplineState("p2", "A", pending_suspensions=1),
    }
    engine.process_match("m3", "group", [], states, stage_complete=True)

    assert states["p1"].caution_match_ids == []
    assert states["p2"].pending_suspensions == 1


def test_official_decisions_can_revoke_and_add_penalties():
    engine = DisciplineEngine()
    states = {
        "wrong": PlayerDisciplineState("wrong", "A", caution_match_ids=["m1"]),
        "right": PlayerDisciplineState("right", "A"),
    }
    engine.apply_official_decision({"action": "correct_identity", "player_id": "wrong", "target_player_id": "right", "match_id": "m1"}, states)
    engine.apply_official_decision({"action": "add_suspension", "player_id": "right", "matches": 2}, states)
    engine.apply_official_decision({"action": "reduce_suspension", "player_id": "right", "matches": 1}, states)

    assert states["wrong"].caution_match_ids == []
    assert states["right"].caution_match_ids == ["m1"]
    assert states["right"].pending_suspensions == 1
