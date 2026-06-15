from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import ROOT


DEFAULT_RULES_PATH = ROOT / "pipeline" / "data" / "fifa-2026-discipline.json"


@dataclass(frozen=True)
class DisciplineRules:
    version: str
    published_at: str
    source_urls: tuple[str, ...]
    yellow_card_threshold: int
    yellow_suspension_matches: int
    indirect_red_suspension_matches: int
    direct_red_suspension_matches: int
    clear_single_yellows_after_stages: frozenset[str]
    team_conduct_points: dict[str, int]

    @classmethod
    def load(cls, path: Path = DEFAULT_RULES_PATH) -> "DisciplineRules":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=data["version"],
            published_at=data["published_at"],
            source_urls=tuple(data["source_urls"]),
            yellow_card_threshold=int(data["yellow_card_threshold"]),
            yellow_suspension_matches=int(data["yellow_suspension_matches"]),
            indirect_red_suspension_matches=int(data["indirect_red_suspension_matches"]),
            direct_red_suspension_matches=int(data["direct_red_suspension_matches"]),
            clear_single_yellows_after_stages=frozenset(data["clear_single_yellows_after_stages"]),
            team_conduct_points={key: int(value) for key, value in data["team_conduct_points"].items()},
        )


@dataclass
class PlayerDisciplineState:
    player_id: str
    team_id: str
    position: str = "unknown"
    caution_match_ids: list[str] = field(default_factory=list)
    pending_suspensions: int = 0
    served_suspensions: int = 0
    audit_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MatchDisciplineResult:
    team_conduct_scores: dict[str, int]
    suspended_next_match: tuple[str, ...]
    rule_version: str


class DisciplineEngine:
    def __init__(self, rules: DisciplineRules | None = None):
        self.rules = rules or DisciplineRules.load()

    def start_team_match(self, team_id: str, states: dict[str, PlayerDisciplineState]) -> list[str]:
        suspended = []
        for state in states.values():
            if state.team_id == team_id and state.pending_suspensions > 0:
                suspended.append(state.player_id)
                state.pending_suspensions -= 1
                state.served_suspensions += 1
                state.audit_log.append({"action": "served_suspension"})
        return sorted(suspended)

    def process_match(
        self,
        match_id: str,
        stage: str,
        events: Iterable[dict[str, Any]],
        states: dict[str, PlayerDisciplineState],
        stage_complete: bool = False,
    ) -> MatchDisciplineResult:
        by_player: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            event_type = str(event["event_type"])
            if event_type not in {"yellow", "second_yellow", "direct_red"}:
                continue
            player_id = str(event["player_id"])
            team_id = str(event["team_id"])
            states.setdefault(player_id, PlayerDisciplineState(player_id=player_id, team_id=team_id))
            if states[player_id].team_id != team_id:
                raise ValueError(f"player {player_id} is mapped to multiple teams")
            by_player.setdefault(player_id, []).append(event)

        conduct: dict[str, int] = {}
        for player_id, player_events in by_player.items():
            state = states[player_id]
            event_types = [str(event["event_type"]) for event in player_events]
            yellow_count = event_types.count("yellow")
            indirect_red = "second_yellow" in event_types or yellow_count >= 2
            direct_red = "direct_red" in event_types

            if direct_red:
                state.pending_suspensions += self.rules.direct_red_suspension_matches
                deduction_key = "yellow_and_direct_red" if yellow_count else "direct_red"
                state.audit_log.append({"action": "direct_red", "match_id": match_id})
            elif indirect_red:
                state.pending_suspensions += self.rules.indirect_red_suspension_matches
                deduction_key = "indirect_red"
                state.audit_log.append({"action": "indirect_red", "match_id": match_id})
            elif yellow_count == 1:
                if match_id not in state.caution_match_ids:
                    state.caution_match_ids.append(match_id)
                deduction_key = "yellow"
                state.audit_log.append({"action": "yellow", "match_id": match_id})
                if len(state.caution_match_ids) >= self.rules.yellow_card_threshold:
                    state.pending_suspensions += self.rules.yellow_suspension_matches
                    state.caution_match_ids = state.caution_match_ids[self.rules.yellow_card_threshold:]
                    state.audit_log.append({"action": "yellow_threshold", "match_id": match_id})
            else:
                continue

            conduct[state.team_id] = conduct.get(state.team_id, 0) + self.rules.team_conduct_points[deduction_key]

        if stage_complete and stage in self.rules.clear_single_yellows_after_stages:
            self.clear_single_yellows(states, stage)

        suspended = tuple(sorted(
            state.player_id for state in states.values() if state.pending_suspensions > 0
        ))
        return MatchDisciplineResult(conduct, suspended, self.rules.version)

    @staticmethod
    def clear_single_yellows(states: dict[str, PlayerDisciplineState], stage: str) -> None:
        for state in states.values():
            if state.caution_match_ids:
                state.audit_log.append({
                    "action": "clear_single_yellows",
                    "stage": stage,
                    "match_ids": list(state.caution_match_ids),
                })
                state.caution_match_ids.clear()

    @staticmethod
    def apply_official_decision(
        decision: dict[str, Any],
        states: dict[str, PlayerDisciplineState],
    ) -> None:
        action = str(decision["action"])
        player_id = str(decision["player_id"])
        if player_id not in states:
            raise KeyError(player_id)
        state = states[player_id]
        if action == "add_suspension":
            state.pending_suspensions += int(decision.get("matches", 1))
        elif action == "reduce_suspension":
            state.pending_suspensions = max(0, state.pending_suspensions - int(decision.get("matches", 1)))
        elif action == "revoke_caution":
            match_id = str(decision["match_id"])
            state.caution_match_ids = [item for item in state.caution_match_ids if item != match_id]
        elif action == "correct_identity":
            target_id = str(decision["target_player_id"])
            target = states[target_id]
            match_id = str(decision["match_id"])
            if match_id in state.caution_match_ids:
                state.caution_match_ids.remove(match_id)
                if match_id not in target.caution_match_ids:
                    target.caution_match_ids.append(match_id)
        else:
            raise ValueError(f"unsupported official decision: {action}")
        state.audit_log.append({"action": "official_decision", "decision": dict(decision)})
