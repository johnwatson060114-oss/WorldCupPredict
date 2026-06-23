from __future__ import annotations

import json
import math
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


def outcome_label(home_score: int, away_score: int) -> str:
    return "home" if home_score > away_score else "draw" if home_score == away_score else "away"


def predicted_outcome_for_review(match: dict) -> tuple[str, str]:
    decision = match.get("outcomeDecision") or {}
    selection = decision.get("selection")
    if selection in {"home", "draw", "away"}:
        return selection, "outcomeDecision"
    probabilities = match["outcomeProbabilities"]
    return max(("home", "draw", "away"), key=lambda key: float(probabilities[key])), "outcomeProbabilities"


def build_match_review(match: dict, result: dict) -> dict:
    actual_home = int(result["homeScore"])
    actual_away = int(result["awayScore"])
    probabilities = match["outcomeProbabilities"]
    actual_outcome = outcome_label(actual_home, actual_away)
    predicted_home, predicted_away = (int(value) for value in match["likelyScore"].split("-"))
    predicted_outcome, predicted_outcome_source = predicted_outcome_for_review(match)
    goal_error = abs(predicted_home - actual_home) + abs(predicted_away - actual_away)
    actual_vector = {key: 1.0 if key == actual_outcome else 0.0 for key in ("home", "draw", "away")}
    brier = sum((float(probabilities[key]) - actual_vector[key]) ** 2 for key in actual_vector)
    outcome_correct = predicted_outcome == actual_outcome
    if outcome_correct and goal_error >= 4:
        diagnosis = "方向正确，但明显低估比赛开放度和大比分尾部。"
    elif outcome_correct:
        diagnosis = "赛果方向正确，但比分尺度仍有偏差。"
    elif predicted_outcome == "away" and actual_outcome == "home":
        diagnosis = "方向反转：客胜倾向未兑现，主队强度被明显低估。"
    elif predicted_outcome == "draw" and actual_outcome == "home":
        diagnosis = "平局倾向失效，主队进攻上限被明显低估。"
    else:
        diagnosis = "赛果方向判断错误，需要继续积累同类对阵样本。"
    return {
        "matchId": match["id"],
        "label": f"{match['homeTeam']} vs {match['awayTeam']}",
        "predictedScore": match["likelyScore"],
        "actualScore": f"{actual_home}-{actual_away}",
        "predictedOutcome": predicted_outcome,
        "predictedOutcomeSource": predicted_outcome_source,
        "actualOutcome": actual_outcome,
        "outcomeCorrect": outcome_correct,
        "exactScore": predicted_home == actual_home and predicted_away == actual_away,
        "goalAbsoluteError": goal_error,
        "actualOutcomeProbability": round(float(probabilities[actual_outcome]), 5),
        "logLoss": round(-math.log(max(1e-12, float(probabilities[actual_outcome]))), 5),
        "brier": round(brier, 5),
        "diagnosis": diagnosis,
    }


def build_day_review(forecast: dict, settlements: dict[str, dict], strategies: list[dict]) -> dict | None:
    matches = forecast.get("matches", [])
    if not matches or any(match["id"] not in settlements for match in matches):
        return None
    reviews = [build_match_review(match, settlements[match["id"]]) for match in matches]
    ticket_signatures = {
        tuple(
            (leg["matchId"], leg["market"], leg["selection"])
            for ticket in portfolio.get("tickets", [])
            for leg in ticket.get("legs", [])
        )
        for portfolio in forecast.get("portfolios", [])
        if portfolio.get("tickets")
    }
    all_lost = bool(strategies) and all(
        strategy["status"] in {"settled", "no-bet"} and (strategy.get("profit") or 0) <= 0
        for strategy in strategies
    )
    strategy_diagnosis = (
        "三档策略实际使用同一组串关标的，风险没有分散；这是升级前策略差异不足的直接证据。"
        if len(ticket_signatures) == 1 and all_lost
        else "策略结果已按真实派彩结算，继续观察多日样本后再调整资金规则。"
    )
    return {
        "snapshotLabel": "升级前基线快照",
        "matches": reviews,
        "summary": {
            "matchCount": len(reviews),
            "outcomeAccuracy": round(sum(item["outcomeCorrect"] for item in reviews) / len(reviews), 4),
            "exactScoreAccuracy": round(sum(item["exactScore"] for item in reviews) / len(reviews), 4),
            "meanGoalAbsoluteError": round(sum(item["goalAbsoluteError"] for item in reviews) / len(reviews), 3),
            "logLoss": round(sum(item["logLoss"] for item in reviews) / len(reviews), 5),
            "brier": round(sum(item["brier"] for item in reviews) / len(reviews), 5),
            "strategyDiagnosis": strategy_diagnosis,
        },
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
            strategies = [settle_portfolio(portfolio, settlements) for portfolio in forecast.get("portfolios", [])]
            days.append({
                "targetDate": forecast["targetDate"],
                "generatedAt": forecast["generatedAt"],
                "coverage": forecast.get("overallCoverage", 0),
                "strategies": strategies,
                "review": build_day_review(forecast, settlements, strategies),
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
