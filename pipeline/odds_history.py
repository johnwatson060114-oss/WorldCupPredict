from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from .config import OUTPUT_DIR, SETTINGS
from .sporttery import SportteryMatch, fetch_sporttery


DEFAULT_DIRECTORY = OUTPUT_DIR / "odds-history"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture compact Sporttery odds history")
    parser.add_argument("--now", help="ISO-8601 observation time")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIRECTORY)
    return parser.parse_args()


def kickoff_datetime(match: SportteryMatch, timezone: ZoneInfo) -> datetime | None:
    if not match.match_date or not match.kickoff_text:
        return None
    time_part = match.kickoff_text.split()[-1]
    try:
        return datetime.fromisoformat(f"{match.match_date}T{time_part}:00").replace(tzinfo=timezone)
    except ValueError:
        return None


def snapshot_kind(minutes_to_kickoff: float | None) -> str:
    if minutes_to_kickoff is not None and 0 <= minutes_to_kickoff <= 60:
        return "closing_60m"
    return "daily"


def closing_line_value(open_odds: float, closing_odds: float) -> float:
    """Decimal-odds CLV; positive means the captured price beat the close."""

    if open_odds <= 1 or closing_odds <= 1:
        raise ValueError("decimal odds must be greater than one")
    return round(open_odds / closing_odds - 1, 8)


def compact_match(match: SportteryMatch, observed_at: datetime, timezone: ZoneInfo) -> dict:
    kickoff = kickoff_datetime(match, timezone)
    minutes = (kickoff - observed_at).total_seconds() / 60 if kickoff else None
    return {
        "matchId": match.match_id,
        "lotteryCode": match.lottery_code,
        "matchDate": match.match_date,
        "kickoffBeijing": kickoff.isoformat(timespec="seconds") if kickoff else None,
        "homeTeam": match.home_team,
        "awayTeam": match.away_team,
        "handicap": match.handicap,
        "minutesToKickoff": round(minutes, 1) if minutes is not None else None,
        "snapshotKind": snapshot_kind(minutes),
        "markets": {
            "胜平负": match.win_draw_loss,
            "让球胜平负": match.handicap_win_draw_loss,
            "比分": match.scores,
            "总进球数": match.total_goals,
            "半全场": match.half_full,
        },
    }


def save_odds_snapshot(
    matches: Iterable[SportteryMatch],
    observed_at: datetime,
    directory: Path = DEFAULT_DIRECTORY,
) -> Path:
    timezone = ZoneInfo(SETTINGS.timezone)
    observed = observed_at.astimezone(timezone)
    world_cup = [
        compact_match(match, observed, timezone)
        for match in matches
        if not match.league_name or match.league_name == "世界杯"
    ]
    payload = {
        "schemaVersion": 1,
        "observedAt": observed.isoformat(timespec="seconds"),
        "timezone": SETTINGS.timezone,
        "matches": world_cup,
        "closingWindowMatches": sum(item["snapshotKind"] == "closing_60m" for item in world_cup),
    }
    day_directory = directory / observed.date().isoformat()
    day_directory.mkdir(parents=True, exist_ok=True)
    filename = observed.strftime("%H%M%S") + ".json"
    path = day_directory / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    index_path = directory / "index.json"
    snapshots = []
    if index_path.exists():
        try:
            snapshots = json.loads(index_path.read_text(encoding="utf-8")).get("snapshots", [])
        except (OSError, json.JSONDecodeError):
            snapshots = []
    relative = path.relative_to(directory.parent).as_posix()
    snapshots = [item for item in snapshots if item.get("path") != relative]
    snapshots.append({
        "observedAt": payload["observedAt"],
        "path": relative,
        "matches": len(world_cup),
        "closingWindowMatches": payload["closingWindowMatches"],
    })
    snapshots.sort(key=lambda item: item["observedAt"])
    index_path.write_text(json.dumps({
        "schemaVersion": 1,
        "generatedAt": payload["observedAt"],
        "snapshots": snapshots,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    timezone = ZoneInfo(SETTINGS.timezone)
    observed = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone)
    path = save_odds_snapshot(fetch_sporttery().values(), observed, args.output_dir)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
