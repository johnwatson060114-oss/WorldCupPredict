from pipeline.match_timeline import (
    cooling_break_minutes,
    extract_timeline,
    match_tactical_summary,
    minute_value,
    tactical_direction,
)


def commentary(minute: str, text: str) -> dict:
    return {"time": {"displayValue": minute}, "text": text}


def play_commentary(minute: str, text: str, period: int, team: str | None = None) -> dict:
    play = {"period": {"number": period}}
    if team:
        play["team"] = {"displayName": team}
    return {"time": {"displayValue": minute}, "text": text, "play": play}


def test_timeline_extracts_event_coordinates_and_actual_breaks():
    events = extract_timeline([
        commentary("25'", "Delay in match for a drinks break."),
        commentary("30'", "Attempt saved. A Player (Team A) right footed shot is saved."),
        commentary("68'", "Delay in match for a drinks break."),
        commentary("73'", "Delay in match because of an injury A Player (Team A)."),
        commentary("82'", "VAR Decision: Card upgraded B Player (Team B)."),
    ], ["Team A", "Team B"], "https://example.test/commentary")

    assert cooling_break_minutes(events) == (25.0, 68.0)
    assert [event["type"] for event in events] == [
        "cooling_break", "chance_saved", "cooling_break", "injury", "var",
    ]
    assert all(event["sourceUrl"].startswith("https://") for event in events)


def test_added_time_is_converted_to_elapsed_minute():
    assert minute_value("45'+4'") == 49.0
    assert minute_value("90'+7'") == 97.0


def test_post_break_volume_creates_a_bounded_tactical_signal():
    source = "https://example.test/commentary"
    rows = [
        commentary("25'", "Delay in match for a drinks break."),
        commentary("28'", "Attempt saved. P1 (Team A) right footed shot is saved."),
        commentary("31'", "Attempt missed. P2 (Team A) right footed shot misses."),
        commentary("35'", "Attempt blocked. P3 (Team A) right footed shot is blocked."),
        commentary("68'", "Delay in match for a drinks break."),
        commentary("72'", "Attempt saved. P4 (Team A) right footed shot is saved."),
        commentary("75'", "Attempt missed. P5 (Team A) header misses."),
        commentary("79'", "Attempt blocked. P6 (Team A) shot is blocked."),
        commentary("83'", "Attempt saved. P7 (Team A) shot is saved."),
    ]
    events = extract_timeline(rows, ["Team A", "Team B"], source)
    summary = match_tactical_summary(events, ["Team A", "Team B"])
    labels = summary["teams"]["Team A"]["labels"]
    attack, defense = tactical_direction(labels * 4)

    assert "second_break_attack_increase" in labels
    assert attack == 0.05
    assert defense == 0.0


def test_distortion_events_are_classified_for_credibility_gates():
    events = extract_timeline([
        commentary("12'", "Goal! Team A 1, Team B 0. Player One (Team A) converts the penalty."),
        commentary("31'", "Own Goal by Player Two, Team B. Team A 2, Team B 0."),
        commentary("55'", "Goalkeeping error by Player Three (Team B)."),
    ], ["Team A", "Team B"], "https://example.test/commentary")

    assert [event["type"] for event in events] == ["penalty_goal", "own_goal", "keeper_error"]


def test_knockout_load_events_are_classified_and_labeled():
    events = extract_timeline([
        commentary("90'", "Start of extra time."),
        commentary("94'", "Player One (Team A) is cramping and looks physically drained."),
        commentary("101'", "Player Two (Team A) is shown the yellow card."),
        commentary("108'", "Player Three (Team A) is shown the yellow card."),
        commentary("120'", "Team A won the match on penalties."),
    ], ["Team A", "Team B"], "https://example.test/commentary")
    summary = match_tactical_summary(events, ["Team A", "Team B"])
    labels = summary["teams"]["Team A"]["labels"]

    assert [event["type"] for event in events] == [
        "extra_time",
        "fatigue",
        "yellow_card",
        "yellow_card",
        "penalty_shootout",
    ]
    assert "extra_time_load" in labels
    assert "visible_cramp_or_fatigue" in labels
    assert "card_suspension_risk" in labels
    assert "penalty_shootout_load" in labels


def test_saved_attempt_belongs_to_shooter_not_later_named_goalkeeper():
    events = extract_timeline([
        commentary(
            "12'",
            "Attempt saved. Striker (Team A) right footed shot is saved by Keeper (Long Team B).",
        ),
    ], ["Team A", "Long Team B"], "https://example.test/commentary")

    assert events[0]["team"] == "Team A"


def test_extra_time_pressure_is_archived_but_excluded_from_regular_time_tactics():
    rows = [
        play_commentary("80'", "Attempt saved. P1 (Team A) shot is saved.", 2, "Team A"),
        play_commentary("93'", "Goal! Team A 1, Team B 0. P2 (Team A) scores.", 3, "Team A"),
        play_commentary("101'", "Attempt missed. P3 (Team A) shot misses.", 3, "Team A"),
    ]
    events = extract_timeline(rows, ["Team A", "Team B"], "https://example.test/commentary")
    summary = match_tactical_summary(events, ["Team A", "Team B"])

    assert [event["regulationTime"] for event in events] == [True, False, False]
    assert summary["coverage"]["post90ClassifiedEvents"] == 2
    assert summary["teams"]["Team A"]["attackingEventsBySegment"] == [0, 0, 0, 1]
