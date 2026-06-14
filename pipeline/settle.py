from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient
from .config import OUTPUT_DIR, SETTINGS


def team_key(name: str) -> str:
    return name.replace(" ", "").replace("阿尔及利亚", "阿尔及利").lower()


def main() -> None:
    history_dir = OUTPUT_DIR / "history"
    output = OUTPUT_DIR / "settlements.json"
    existing = {"generatedAt": datetime.now(ZoneInfo(SETTINGS.timezone)).isoformat(timespec="seconds"), "matches": []}
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
    by_id = {item["matchId"]: item for item in existing.get("matches", [])}
    client = ApiFootballClient()
    if not client.enabled or not history_dir.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Settlement refresh skipped: API_FOOTBALL_KEY or forecast history is missing")
        return

    for path in sorted(history_dir.glob("*.json")):
        forecast = json.loads(path.read_text(encoding="utf-8"))
        target_date = forecast["targetDate"]
        fixtures = client.world_cup_fixtures(target_date)
        for match in forecast.get("matches", []):
            if match["id"] in by_id:
                continue
            for fixture in fixtures:
                home = fixture["teams"]["home"]["name"]
                away = fixture["teams"]["away"]["name"]
                status = fixture["fixture"]["status"]["short"]
                if team_key(home) != team_key(match["homeTeam"]) or team_key(away) != team_key(match["awayTeam"]):
                    continue
                if status not in {"FT", "AET", "PEN"}:
                    continue
                by_id[match["id"]] = {
                    "matchId": match["id"],
                    "homeScore": fixture["goals"]["home"],
                    "awayScore": fixture["goals"]["away"],
                    "settledAt": fixture["fixture"]["date"],
                }
                break

    payload = {
        "generatedAt": datetime.now(ZoneInfo(SETTINGS.timezone)).isoformat(timespec="seconds"),
        "matches": list(by_id.values()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output} with {len(by_id)} settled matches")


if __name__ == "__main__":
    main()
