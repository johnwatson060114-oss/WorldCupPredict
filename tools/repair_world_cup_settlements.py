from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.football_data import localized_team_name
from pipeline.settlement_store import deduplicate_settlements, normalized_match_label


SOURCE = ROOT / ".cache" / "pipeline" / "football-data" / "97a7f68839a6f94960f7d194.json"
OUTPUT = ROOT / "public" / "data" / "settlements.json"


def main() -> None:
    source_payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    fixtures = [
        fixture
        for fixture in source_payload.get("value", source_payload).get("matches", [])
        if fixture.get("stage") == "GROUP_STAGE"
    ]
    existing_payload = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {"matches": []}
    existing = deduplicate_settlements(existing_payload.get("matches", []))
    existing_by_label = {normalized_match_label(item): item for item in existing}
    repaired = []
    for fixture in fixtures:
        score = fixture.get("score", {}).get("fullTime", {})
        if fixture.get("status") != "FINISHED" or score.get("home") is None or score.get("away") is None:
            continue
        home = localized_team_name(fixture["homeTeam"])
        away = localized_team_name(fixture["awayTeam"])
        label = f"{home} vs {away}"
        previous = existing_by_label.get(normalized_match_label({"matchLabel": label}), {})
        item = {
            **previous,
            "matchId": previous.get("matchId") or str(fixture["id"]),
            "fixtureId": fixture["id"],
            "matchLabel": label,
            "group": fixture.get("group"),
            "matchday": fixture.get("matchday"),
            "homeScore": score["home"],
            "awayScore": score["away"],
            "halfTimeHomeScore": (fixture.get("score", {}).get("halfTime") or {}).get("home"),
            "halfTimeAwayScore": (fixture.get("score", {}).get("halfTime") or {}).get("away"),
            "settledAt": fixture.get("utcDate"),
        }
        repaired.append(item)
    repaired = deduplicate_settlements(repaired)
    payload = {
        "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "scheduledGroupMatchdaysOneAndTwo": 48,
        "completedGroupMatchdaysOneAndTwo": len(repaired),
        "matches": repaired,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(repaired)} unique completed matches")


if __name__ == "__main__":
    main()
