from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import OUTPUT_DIR, SETTINGS

FINAL_DATE = "2026-07-19"
STANDARD_SCORES = {
    "1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2", "5:0", "5:1", "5:2",
    "0:0", "1:1", "2:2", "3:3",
    "0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4", "0:5", "1:5", "2:5",
}


def leg_won(leg: dict, result: dict) -> bool | None:
    home_score = int(result["homeScore"])
    away_score = int(result["awayScore"])
    if leg["market"] == "比分":
        score = f"{home_score}:{away_score}"
        if leg["selection"] in {score, score.replace(":", "-")}:
            return True
        if score in STANDARD_SCORES:
            return False
        outcome = "胜其它" if home_score > away_score else "平其它" if home_score == away_score else "负其它"
        return leg["selection"] == outcome
    if leg["market"] == "总进球数":
        total = home_score + away_score
        return leg["selection"] == ("7+" if total >= 7 else str(total))
    if leg["market"] == "半全场":
        half_home = result.get("halfTimeHomeScore")
        half_away = result.get("halfTimeAwayScore")
        if half_home is None or half_away is None:
            return None
        half = "胜" if half_home > half_away else "平" if half_home == half_away else "负"
        full = "胜" if home_score > away_score else "平" if home_score == away_score else "负"
        return leg["selection"] == f"{half}{full}"
    handicap_match = re.match(r"^([+-]\d+)\s+(胜|平|负)$", leg["selection"])
    handicap = int(handicap_match.group(1)) if handicap_match else 0
    selection = handicap_match.group(2) if handicap_match else leg["selection"]
    adjusted_home = home_score + handicap
    outcome = "胜" if adjusted_home > away_score else "平" if adjusted_home == away_score else "负"
    return selection == outcome


def settle_portfolio(portfolio: dict, settlements: dict[str, dict]) -> dict:
    tickets = portfolio.get("tickets", [])
    if not tickets:
        return {
            "key": portfolio["key"],
            "name": portfolio["name"],
            "stake": 0,
            "payout": 0,
            "profit": 0,
            "roi": None,
            "status": "no-bet",
        }
    match_ids = {leg["matchId"] for ticket in tickets for leg in ticket.get("legs", [])}
    if any(match_id not in settlements for match_id in match_ids):
        return {
            "key": portfolio["key"],
            "name": portfolio["name"],
            "stake": portfolio["stake"],
            "payout": None,
            "profit": None,
            "roi": None,
            "status": "pending",
        }
    payout = 0.0
    for ticket in tickets:
        outcomes = [leg_won(leg, settlements[leg["matchId"]]) for leg in ticket.get("legs", [])]
        if any(outcome is None for outcome in outcomes):
            return {
                "key": portfolio["key"], "name": portfolio["name"], "stake": portfolio["stake"],
                "payout": None, "profit": None, "roi": None, "status": "pending",
            }
        won = all(outcomes)
        if won:
            payout += float(ticket["potentialPayout"])
    stake = float(portfolio["stake"])
    profit = payout - stake
    return {
        "key": portfolio["key"],
        "name": portfolio["name"],
        "stake": round(stake, 2),
        "payout": round(payout, 2),
        "profit": round(profit, 2),
        "roi": round(profit / stake, 6) if stake else None,
        "status": "settled",
    }


def build_strategy_history(history_dir: Path, settlement_path: Path) -> dict:
    settlement_payload = {"matches": []}
    if settlement_path.exists():
        settlement_payload = json.loads(settlement_path.read_text(encoding="utf-8"))
    settlements = {item["matchId"]: item for item in settlement_payload.get("matches", [])}
    days = []
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.json")):
            forecast = json.loads(path.read_text(encoding="utf-8"))
            days.append({
                "targetDate": forecast["targetDate"],
                "generatedAt": forecast["generatedAt"],
                "coverage": forecast.get("overallCoverage", 0),
                "strategies": [settle_portfolio(portfolio, settlements) for portfolio in forecast.get("portfolios", [])],
            })
    return {
        "generatedAt": datetime.now(ZoneInfo(SETTINGS.timezone)).isoformat(timespec="seconds"),
        "finalDate": FINAL_DATE,
        "days": days,
    }


def main() -> None:
    output = OUTPUT_DIR / "strategy-history.json"
    payload = build_strategy_history(OUTPUT_DIR / "history", OUTPUT_DIR / "settlements.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output} with {len(payload['days'])} archived strategy days")


if __name__ == "__main__":
    main()
