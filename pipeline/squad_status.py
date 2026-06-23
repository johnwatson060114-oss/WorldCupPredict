from __future__ import annotations

from typing import Any, Iterable

from .discipline import DisciplineEngine, PlayerDisciplineState


def discipline_event(event: dict[str, Any], team_ids: dict[str, str]) -> dict[str, str] | None:
    event_type = str(event.get("type") or "")
    mapped = {
        "yellow_card": "yellow",
        "second_yellow": "second_yellow",
        "red_card": "direct_red",
    }.get(event_type)
    player = str(event.get("player") or "").strip()
    team = str(event.get("team") or "").strip()
    if not mapped or not player or team not in team_ids:
        return None
    return {"player_id": player, "team_id": team_ids[team], "event_type": mapped}


def build_squad_status(
    matches: Iterable[dict[str, Any]],
    team_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    match_list = sorted(matches, key=lambda match: str(match.get("utcDate") or ""))
    all_teams = {
        str(team)
        for match in match_list
        for team in (match.get("homeTeam"), match.get("awayTeam"))
        if team
    }
    ids = team_ids or {team: team for team in all_teams}
    engine = DisciplineEngine()
    states: dict[str, PlayerDisciplineState] = {}
    match_results: list[dict[str, Any]] = []
    injuries: dict[tuple[str, str], dict[str, Any]] = {}
    for match in match_list:
        home = str(match.get("homeTeam") or "")
        away = str(match.get("awayTeam") or "")
        served = {
            home: engine.start_team_match(ids.get(home, home), states),
            away: engine.start_team_match(ids.get(away, away), states),
        }
        events = [
            mapped for mapped in (
                discipline_event(event, ids) for event in match.get("events", [])
            )
            if mapped is not None
        ]
        result = engine.process_match(
            str(match.get("fixtureId") or match.get("id")),
            "group",
            events,
            states,
        )
        for event in match.get("events", []):
            if event.get("type") != "injury" or not event.get("team") or not event.get("player"):
                continue
            minute = float(event.get("minute") or 0)
            player = str(event["player"])
            severe = bool(event.get("seriousInjuryHint")) or any(
                candidate.get("type") == "substitution"
                and minute <= float(candidate.get("minute") or 0) <= minute + 10
                and candidate.get("replacedPlayer") == player
                for candidate in match.get("events", [])
            )
            key = (str(event["team"]), str(event["player"]))
            injuries[key] = {
                "team": key[0],
                "player": key[1],
                "status": "doubtful" if severe else "monitor",
                "availabilityProbability": 0.50 if severe else 0.85,
                "confidence": 0.65 if severe else 0.35,
                "observedAtMinute": event.get("displayMinute"),
                "sourceUrl": event.get("sourceUrl"),
                "note": (
                    "比赛中伤退或出现无法坚持的迹象；等待球队官方赛前更新"
                    if severe else "比赛中接受治疗但继续参赛；列入观察，等待球队官方更新"
                ),
            }
        match_results.append({
            "fixtureId": match.get("fixtureId"),
            "servedSuspensions": served,
            "teamConductScores": result.team_conduct_scores,
            "suspendedNextMatch": list(result.suspended_next_match),
            "ruleVersion": result.rule_version,
        })
    pending = [
        {
            "player": state.player_id,
            "team": state.team_id,
            "pendingSuspensions": state.pending_suspensions,
            "cautionMatchIds": list(state.caution_match_ids),
            "servedSuspensions": state.served_suspensions,
            "auditLog": list(state.audit_log),
        }
        for state in states.values()
        if state.pending_suspensions or state.caution_match_ids or state.served_suspensions
    ]
    return {
        "matches": match_results,
        "players": sorted(pending, key=lambda item: (item["team"], item["player"])),
        "injuries": sorted(injuries.values(), key=lambda item: (item["team"], item["player"])),
    }
