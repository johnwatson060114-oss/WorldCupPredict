from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from .config import ROOT


ANNEX_C_PATH = ROOT / "pipeline" / "data" / "fifa-2026-annex-c.json"
THIRD_PLACE_WINNER_ELIGIBILITY = {
    "A": frozenset("CEFHI"),
    "B": frozenset("EFGIJ"),
    "D": frozenset("BEFIJ"),
    "E": frozenset("ABCDF"),
    "G": frozenset("AEHIJ"),
    "I": frozenset("CDFGH"),
    "K": frozenset("DEIJL"),
    "L": frozenset("EHIJK"),
}
FIXED_ROUND_OF_32 = {
    ("A", 2): ("B", 2),
    ("B", 2): ("A", 2),
    ("C", 1): ("F", 2),
    ("F", 2): ("C", 1),
    ("F", 1): ("C", 2),
    ("C", 2): ("F", 1),
    ("E", 2): ("I", 2),
    ("I", 2): ("E", 2),
    ("K", 2): ("L", 2),
    ("L", 2): ("K", 2),
    ("H", 1): ("J", 2),
    ("J", 2): ("H", 1),
    ("J", 1): ("H", 2),
    ("H", 2): ("J", 1),
    ("D", 2): ("G", 2),
    ("G", 2): ("D", 2),
}


@dataclass(frozen=True)
class ThirdPlaceRow:
    group: str
    team: str
    points: int
    goal_difference: int
    goals_for: int
    conduct: int = 0
    ranking_history: tuple[int, ...] = ()


def rank_best_thirds(rows: Iterable[ThirdPlaceRow]) -> list[ThirdPlaceRow]:
    return sorted(
        rows,
        key=lambda row: (
            row.points,
            row.goal_difference,
            row.goals_for,
            row.conduct,
            tuple(-rank for rank in row.ranking_history),
            row.team,
        ),
        reverse=True,
    )


def load_annex_c(path: Path = ANNEX_C_PATH) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    combinations_map = dict(payload.get("combinations", {}))
    if len(combinations_map) != 495:
        raise ValueError("FIFA Annex C must contain all 495 combinations")
    expected = {"".join(parts) for parts in combinations("ABCDEFGHIJKL", 8)}
    if set(combinations_map) != expected:
        raise ValueError("FIFA Annex C combination keys are incomplete")
    return combinations_map


def annex_c_assignment(
    qualifying_third_groups: Iterable[str],
    combinations_map: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    groups = tuple(sorted({str(group).replace("GROUP_", "") for group in qualifying_third_groups}))
    if len(groups) != 8:
        raise ValueError("exactly eight third-place groups are required")
    mapping = combinations_map or load_annex_c()
    key = "".join(groups)
    if key not in mapping:
        raise KeyError(key)
    return dict(mapping[key])


def knockout_opponent_slots(
    group: str,
    position: int,
    qualifying_third_groups: Iterable[str] | None = None,
    combinations_map: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    group_code = str(group).replace("GROUP_", "")
    fixed = FIXED_ROUND_OF_32.get((group_code, int(position)))
    if fixed:
        return [{"group": fixed[0], "position": fixed[1], "mapping": "fixed"}]
    if position == 1 and group_code in THIRD_PLACE_WINNER_ELIGIBILITY:
        if qualifying_third_groups is None:
            return [
                {"group": candidate, "position": 3, "mapping": "eligible"}
                for candidate in sorted(THIRD_PLACE_WINNER_ELIGIBILITY[group_code])
            ]
        assignment = annex_c_assignment(qualifying_third_groups, combinations_map)
        return [{"group": assignment[group_code], "position": 3, "mapping": "annex_c"}]
    if position == 3:
        if qualifying_third_groups is not None:
            assignment = annex_c_assignment(qualifying_third_groups, combinations_map)
            winners = [winner for winner, third_group in assignment.items() if third_group == group_code]
        else:
            winners = [
                winner for winner, eligible in THIRD_PLACE_WINNER_ELIGIBILITY.items()
                if group_code in eligible
            ]
        return [
            {"group": winner, "position": 1, "mapping": "annex_c" if qualifying_third_groups else "eligible"}
            for winner in sorted(winners)
        ]
    return []
