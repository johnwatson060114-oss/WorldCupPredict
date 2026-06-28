from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable


EVENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cooling_break", re.compile(r"\b(drinks?|cooling|hydration) break\b", re.I)),
    ("var", re.compile(r"\b(VAR|video review)\b", re.I)),
    ("substitution", re.compile(r"^Substitution,", re.I)),
    ("injury", re.compile(r"\b(injur|treatment|medical attention|unable to continue)\w*", re.I)),
    ("second_yellow", re.compile(r"\bsecond yellow card\b", re.I)),
    ("red_card", re.compile(r"\bshown the red card\b|\bcard upgraded\b", re.I)),
    ("yellow_card", re.compile(r"\bshown the yellow card\b", re.I)),
    ("penalty_goal", re.compile(r"\bconverts the penalty\b|\bpenalty[ -]shootout\b", re.I)),
    ("penalty_event", re.compile(r"\bpenalty (?:conceded|won|awarded|saved|missed)\b", re.I)),
    ("own_goal", re.compile(r"\bown goal\b", re.I)),
    ("keeper_error", re.compile(r"\bgoalkeeping error\b|\bkeeper error\b|\berror by the goalkeeper\b", re.I)),
    ("goal", re.compile(r"^Goal!", re.I)),
    ("chance_saved", re.compile(r"^Attempt saved\.", re.I)),
    ("chance_missed", re.compile(r"^Attempt missed\.", re.I)),
    ("chance_blocked", re.compile(r"^Attempt blocked\.", re.I)),
    ("woodwork", re.compile(r"\bhits? the (left |right )?(post|bar|crossbar)\b", re.I)),
)

ATTACKING_EVENT_TYPES = {
    "goal",
    "penalty_goal",
    "penalty_event",
    "own_goal",
    "chance_saved",
    "chance_missed",
    "chance_blocked",
    "woodwork",
}
CARD_EVENT_TYPES = {"yellow_card", "second_yellow", "red_card"}
DISTORTION_EVENT_TYPES = {"penalty_goal", "penalty_event", "own_goal", "keeper_error"}


def minute_value(display_value: str) -> float:
    value = str(display_value or "").strip().replace("’", "'")
    match = re.match(r"(\d+)'(?:\+(\d+)')?", value)
    if not match:
        return 0.0
    base = int(match.group(1))
    added = int(match.group(2) or 0)
    return float(base + added)


def classify_commentary(text: str) -> str | None:
    for event_type, pattern in EVENT_PATTERNS:
        if pattern.search(str(text or "")):
            return event_type
    return None


def commentary_team(text: str, team_names: Iterable[str]) -> str | None:
    candidates = sorted((str(team) for team in team_names), key=len, reverse=True)
    for team in candidates:
        if (
            f"({team})" in text
            or text.startswith(f"{team} ")
            or text.startswith(f"Substitution, {team}.")
        ):
            return team
    return None


def _player_name(text: str, team: str | None) -> str | None:
    if not team or f"({team})" not in text:
        return None
    prefix = text.split(f"({team})", 1)[0]
    prefix = re.sub(
        (
            r"^(Goal!\s.*?\.\s|Substitution,\s[^.]+\.\s|VAR Decision:\s*|"
            r"Attempt (?:saved|missed|blocked)\.\s*|"
            r"Delay in match because of an injury\s*)"
        ),
        "",
        prefix,
    ).strip()
    for separator in (" replaces ", " is shown ", " right footed", " left footed", " header"):
        if separator in prefix:
            prefix = prefix.split(separator, 1)[0]
    return prefix[-80:].strip(" .") or None


def _substitution_players(text: str) -> tuple[str | None, str | None]:
    match = re.search(r"\.\s*([^.]*)\s+replaces\s+([^.]*)\.", text)
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def _short_summary(event_type: str, player: str | None, replaced_player: str | None) -> str:
    labels = {
        "cooling_break": "补水暂停",
        "var": "VAR复核",
        "substitution": "换人",
        "injury": "伤情或治疗中断",
        "second_yellow": "第二张黄牌",
        "red_card": "红牌",
        "yellow_card": "黄牌",
        "goal": "进球",
        "chance_saved": "射门被扑",
        "chance_missed": "射门偏出",
        "chance_blocked": "射门被封堵",
        "woodwork": "击中门框",
    }
    if event_type == "cooling_break":
        return labels[event_type]
    actor = player or "未知球员"
    if event_type == "substitution" and replaced_player:
        return f"{actor} 换下 {replaced_player}"
    return f"{actor}：{labels[event_type]}"


def extract_timeline(
    commentary: Iterable[dict[str, Any]],
    team_names: Iterable[str],
    source_url: str,
) -> list[dict[str, Any]]:
    teams = tuple(team_names)
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in commentary:
        text = str(item.get("text") or "").strip()
        event_type = classify_commentary(text)
        if event_type is None:
            continue
        display_minute = str(item.get("time", {}).get("displayValue") or "")
        team = commentary_team(text, teams)
        player = _player_name(text, team)
        incoming, outgoing = _substitution_players(text)
        if event_type == "substitution" and incoming:
            player = incoming
        key = (display_minute, event_type, text)
        if key in seen:
            continue
        seen.add(key)
        events.append({
            "minute": minute_value(display_minute),
            "displayMinute": display_minute,
            "type": event_type,
            "team": team,
            "player": player,
            "replacedPlayer": outgoing,
            "summary": (
                f"{player or 'unknown'}: {event_type}"
                if event_type in DISTORTION_EVENT_TYPES
                else _short_summary(event_type, player, outgoing)
            ),
            "setPiece": (
                "following a corner" in text.lower()
                or "following a set piece" in text.lower()
                or "following a free kick" in text.lower()
            ),
            "seriousInjuryHint": "unable to continue" in text.lower(),
            "sourceUrl": source_url,
        })
    return sorted(events, key=lambda event: (float(event["minute"]), str(event["type"]), str(event["summary"])))


def cooling_break_minutes(events: Iterable[dict[str, Any]]) -> tuple[float, float]:
    minutes = sorted(
        float(event["minute"])
        for event in events
        if event.get("type") == "cooling_break" and float(event.get("minute", 0)) > 0
    )
    first = next((minute for minute in minutes if minute < 45), 25.0)
    second = next((minute for minute in minutes if minute >= 45), 70.0)
    return first, second


def event_segment(minute: float, first_break: float, second_break: float) -> int:
    if minute <= first_break:
        return 1
    if minute <= 45:
        return 2
    if minute <= second_break:
        return 3
    return 4


def _rate(count: int, duration: float) -> float:
    return count / max(1.0, duration) * 15.0


def match_tactical_summary(
    events: Iterable[dict[str, Any]],
    team_names: Iterable[str],
) -> dict[str, Any]:
    event_list = list(events)
    teams = tuple(team_names)
    first_break, second_break = cooling_break_minutes(event_list)
    durations = {
        1: first_break,
        2: max(1.0, 45 - first_break),
        3: max(1.0, second_break - 45),
        4: max(1.0, 90 - second_break),
    }
    result: dict[str, Any] = {
        "coolingBreakMinutes": [first_break, second_break],
        "teams": {},
        "coverage": {
            "classifiedEvents": len(event_list),
            "attackingEvents": sum(event.get("type") in ATTACKING_EVENT_TYPES for event in event_list),
            "injuryEvents": sum(event.get("type") == "injury" for event in event_list),
            "cardEvents": sum(event.get("type") in CARD_EVENT_TYPES for event in event_list),
        },
    }
    for team in teams:
        attacking = [event for event in event_list if event.get("team") == team and event.get("type") in ATTACKING_EVENT_TYPES]
        counts = Counter(
            event_segment(float(event["minute"]), first_break, second_break)
            for event in attacking
        )
        rates = {segment: round(_rate(counts[segment], durations[segment]), 3) for segment in range(1, 5)}
        labels: list[str] = []
        if rates[2] - rates[1] >= 1.0 and counts[2] >= 2:
            labels.append("first_break_attack_increase")
        if rates[2] - rates[1] <= -1.0 and counts[1] >= 2:
            labels.append("first_break_attack_decrease")
        if rates[4] - rates[3] >= 1.0 and counts[4] >= 2:
            labels.append("second_break_attack_increase")
        if rates[4] - rates[3] <= -1.0 and counts[3] >= 2:
            labels.append("second_break_attack_decrease")
        late_share = counts[4] / max(1, len(attacking))
        if counts[4] >= 3 and late_share >= 0.40:
            labels.append("late_pressure")
        if counts[3] >= 3 and counts[4] == 0:
            labels.append("late_attack_drop")
        set_piece_attempts = sum(
            bool(event.get("setPiece"))
            for event in attacking
        )
        if set_piece_attempts >= 2:
            labels.append("set_piece_creation")
        substitutions_after_break = sum(
            event.get("type") == "substitution"
            and event.get("team") == team
            and (
                first_break < float(event["minute"]) <= first_break + 10
                or second_break < float(event["minute"]) <= second_break + 10
            )
            for event in event_list
        )
        if substitutions_after_break >= 2:
            labels.append("post_break_substitution_burst")
        result["teams"][team] = {
            "attackingEventsBySegment": [counts[index] for index in range(1, 5)],
            "attackingRatePer15BySegment": [rates[index] for index in range(1, 5)],
            "setPieceAttempts": set_piece_attempts,
            "postBreakSubstitutions": substitutions_after_break,
            "labels": labels,
        }
    return result


def tactical_direction(labels: Iterable[str]) -> tuple[float, float]:
    values = Counter(labels)
    attack = (
        0.015 * values["first_break_attack_increase"]
        + 0.020 * values["second_break_attack_increase"]
        + 0.015 * values["late_pressure"]
        + 0.010 * values["set_piece_creation"]
        - 0.015 * values["first_break_attack_decrease"]
        - 0.020 * values["second_break_attack_decrease"]
        - 0.020 * values["late_attack_drop"]
    )
    return max(-0.05, min(0.05, attack)), 0.0
