from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import OUTPUT_DIR, SETTINGS

FINAL_DATE = "2026-07-19"


def leg_won(leg: dict, result: dict) -> bool:
    home_score = int(result["homeScore"])
    away_score = int(result["awayScore"])
    if leg["market"] == "比分":
        return leg["selection"] in {f"{home_score}:{away_score}", f"{home_score}-{away_score}"}
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
        won = all(leg_won(leg, settlements[leg["matchId"]]) for leg in ticket.get("legs", []))
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
