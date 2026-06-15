import math

from pipeline.lineup import PlayerValue, apply_lineup_impacts, calculate_absence_impact, shrink_player


def player(player_id: str, name: str, position: str, attack: float, defense: float, sample: int = 30) -> PlayerValue:
    return PlayerValue(
        player_id=player_id,
        name=name,
        team="A",
        position=position,
        attack_value=attack,
        defense_value=defense,
        sample_size=sample,
        model_version="player-value-v1",
        source_url="https://example.test/player",
        observed_at="2026-06-15T00:00:00Z",
    )


def test_low_sample_player_values_shrink_to_position_and_team_priors():
    raw = player("p1", "Starter", "CB", 0.2, 0.3, sample=2)
    shrunk = shrink_player(raw, {"CB": {"attack": 0.02, "defense": 0.10}}, {"A": {"attack": 0.04, "defense": 0.08}})

    assert 0.03 < shrunk.attack_value < raw.attack_value
    assert 0.09 < shrunk.defense_value < raw.defense_value


def test_absence_uses_starter_minus_same_position_replacement_value():
    starter = player("p1", "Starter", "CB", 0.06, 0.22)
    replacement = player("p2", "Replacement", "CB", 0.03, 0.09)
    home, away, plans = calculate_absence_impact(
        1.5, 1.0, [starter], [], [replacement], [], {"p1"}
    )

    assert math.isclose(home, 1.47)
    assert math.isclose(away, 1.13)
    assert plans[0]["attackDelta"] == 0.03
    assert plans[0]["defenseDelta"] == 0.13
    assert plans[0]["replacementId"] == "p2"


def test_confirmed_suspension_is_applied_only_when_traceable_values_exist():
    seeds = [{
        "home_team": "A",
        "away_team": "B",
        "base_xg": [1.5, 1.0],
        "confirmed_absences": [{"player": "Starter", "status": "suspended"}],
        "player_values": [
            {**player("p1", "Starter", "CB", 0.06, 0.22).__dict__, "role": "starter"},
            {**player("p2", "Replacement", "CB", 0.03, 0.09).__dict__, "role": "bench"},
        ],
    }]

    apply_lineup_impacts(seeds)

    assert seeds[0]["base_xg"] == [1.47, 1.13]
    assert seeds[0]["lineup_impact"][0]["status"] == "applied"


def test_missing_player_values_do_not_change_mean_prediction():
    seeds = [{
        "home_team": "A", "away_team": "B", "base_xg": [1.5, 1.0],
        "confirmed_absences": [{"player": "Unknown", "status": "suspended"}],
    }]

    apply_lineup_impacts(seeds)

    assert seeds[0]["base_xg"] == [1.5, 1.0]
    assert "lineup_impact" not in seeds[0]
