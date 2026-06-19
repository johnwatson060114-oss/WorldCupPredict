from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient
from .config import OUTPUT_DIR, SETTINGS
from .football_data import FootballDataClient, localized_team_name
from .zgzcw_history import closing_odds_metadata, fetch_closing_odds, sales_issue


def team_key(name: str) -> str:
    return name.replace(" ", "").replace("阿尔及利亚", "阿尔及利").lower()


def main() -> None:
    history_dir = OUTPUT_DIR / "history"
    output = OUTPUT_DIR / "settlements.json"
    existing = {"generatedAt": datetime.now(ZoneInfo(SETTINGS.timezone)).isoformat(timespec="seconds"), "matches": []}
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
    by_id = {item["matchId"]: item for item in existing.get("matches", [])}
    football_client = FootballDataClient()
    api_client = ApiFootballClient()
    if not history_dir.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Settlement refresh skipped: no forecast history is available")
        return

    football_matches: list[dict] | None = None
    if football_client.enabled:
        try:
            football_matches = football_client.world_cup_matches()
        except Exception as exc:  # noqa: BLE001 - API-Football remains a fallback
            print(f"football-data.org settlements unavailable: {type(exc).__name__}")

    unavailable_dates: set[str] = set()
    forecast_matches: dict[str, dict] = {}
    for path in sorted(history_dir.glob("*.json")):
        forecast = json.loads(path.read_text(encoding="utf-8"))
        target_date = forecast["targetDate"]
        for match in forecast.get("matches", []):
            forecast_matches[match["id"]] = match
        if not football_client.enabled and not api_client.enabled:
            continue
        source = "football-data" if football_matches is not None else "api-football"
        fixtures = football_matches
        if fixtures is None:
            try:
                fixtures = api_client.world_cup_fixtures(target_date)
            except Exception as exc:  # noqa: BLE001 - settlement must not block the daily build
                unavailable_dates.add(target_date)
                print(f"Settlement source unavailable for {target_date}: {type(exc).__name__}")
                continue
        for match in forecast.get("matches", []):
            if match["id"] in by_id:
                continue
            for fixture in fixtures:
                if source == "football-data":
                    home = localized_team_name(fixture["homeTeam"])
                    away = localized_team_name(fixture["awayTeam"])
                    status = fixture.get("status")
                    fixture_id = fixture.get("id")
                    score = fixture.get("score", {}).get("fullTime", {})
                    half_time = fixture.get("score", {}).get("halfTime", {}) or {}
                    settled_at = fixture.get("utcDate")
                    final_statuses = {"FINISHED"}
                else:
                    home = fixture["teams"]["home"]["name"]
                    away = fixture["teams"]["away"]["name"]
                    status = fixture["fixture"]["status"]["short"]
                    fixture_id = fixture["fixture"].get("id")
                    score = fixture["goals"]
                    half_time = fixture.get("score", {}).get("halftime", {}) or {}
                    settled_at = fixture["fixture"]["date"]
                    final_statuses = {"FT", "AET", "PEN"}
                id_matches = match.get("apiFixtureId") and fixture_id == match.get("apiFixtureId")
                names_match = team_key(home) == team_key(match["homeTeam"]) and team_key(away) == team_key(match["awayTeam"])
                if not id_matches and not names_match:
                    continue
                if status not in final_statuses:
                    continue
                by_id[match["id"]] = {
                    "matchId": match["id"],
                    "homeScore": score["home"],
                    "awayScore": score["away"],
                    "halfTimeHomeScore": half_time.get("home"),
                    "halfTimeAwayScore": half_time.get("away"),
                    "settledAt": settled_at,
                }
                break

    issue_matches: dict[str, list[str]] = {}
    for match_id, match in forecast_matches.items():
        settlement = by_id.get(match_id)
        kickoff = match.get("kickoffBeijing") or match.get("kickoff")
        if not settlement or settlement.get("closingOdds") or not kickoff:
            continue
        issue_matches.setdefault(sales_issue(kickoff), []).append(match_id)

    checked_at = datetime.now(ZoneInfo(SETTINGS.timezone)).isoformat(timespec="seconds")
    for issue, match_ids in issue_matches.items():
        try:
            issue_odds = fetch_closing_odds(issue)
        except Exception as exc:  # noqa: BLE001 - archive failure must not erase results
            print(f"Closing odds unavailable for {issue}: {type(exc).__name__}")
            continue
        for match_id in match_ids:
            odds = issue_odds.get(match_id)
            if odds:
                by_id[match_id].update(closing_odds_metadata(issue, odds, checked_at))

    payload = {
        "generatedAt": datetime.now(ZoneInfo(SETTINGS.timezone)).isoformat(timespec="seconds"),
        "matches": list(by_id.values()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output} with {len(by_id)} settled matches")
    if unavailable_dates:
        print(f"Settlement refresh skipped {len(unavailable_dates)} date(s); existing results were preserved")


if __name__ == "__main__":
    main()
