from itertools import combinations

from pipeline.tournament_rules import (
    ThirdPlaceRow,
    annex_c_assignment,
    knockout_opponent_slots,
    rank_best_thirds,
)


def test_all_495_annex_c_combinations_are_available():
    for groups in combinations("ABCDEFGHIJKL", 8):
        assignment = annex_c_assignment(groups)
        assert set(assignment) == set("ABDEGIKL")
        assert set(assignment.values()) == set(groups)


def test_best_thirds_use_points_goal_difference_goals_and_conduct():
    rows = [
        ThirdPlaceRow("A", "A3", 4, 0, 2, -3),
        ThirdPlaceRow("B", "B3", 4, 0, 2, -1),
        ThirdPlaceRow("C", "C3", 4, 1, 1, -8),
    ]

    ranked = rank_best_thirds(rows)

    assert [row.team for row in ranked] == ["C3", "B3", "A3"]


def test_fixed_and_third_place_knockout_slots_are_exposed():
    assert knockout_opponent_slots("GROUP_A", 2) == [{"group": "B", "position": 2, "mapping": "fixed"}]
    possible = knockout_opponent_slots("GROUP_A", 1)
    assert {item["group"] for item in possible} == set("CEFHI")
