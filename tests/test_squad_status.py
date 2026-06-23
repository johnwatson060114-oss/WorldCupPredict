from pipeline.squad_status import build_squad_status


def event(event_type: str, player: str, team: str) -> dict:
    return {
        "type": event_type,
        "player": player,
        "team": team,
        "sourceUrl": "https://example.test",
        "displayMinute": "40'",
        "minute": 40.0,
        "summary": f"{player}：伤情或治疗中断",
    }


def test_two_match_yellow_accumulation_and_injury_are_exposed():
    status = build_squad_status([
        {
            "fixtureId": "m1",
            "utcDate": "2026-06-11T12:00:00Z",
            "homeTeam": "A",
            "awayTeam": "B",
            "events": [event("yellow_card", "Player 1", "A")],
        },
        {
            "fixtureId": "m2",
            "utcDate": "2026-06-18T12:00:00Z",
            "homeTeam": "A",
            "awayTeam": "C",
            "events": [
                event("yellow_card", "Player 1", "A"),
                event("injury", "Player 2", "A"),
                {
                    **event("substitution", "Replacement", "A"),
                    "minute": 45.0,
                    "displayMinute": "45'",
                    "summary": "Replacement 换下 Player 2",
                    "replacedPlayer": "Player 2",
                },
            ],
        },
    ])

    player = next(item for item in status["players"] if item["player"] == "Player 1")
    assert player["pendingSuspensions"] == 1
    assert status["matches"][-1]["suspendedNextMatch"] == ["Player 1"]
    assert status["injuries"][0]["status"] == "doubtful"
