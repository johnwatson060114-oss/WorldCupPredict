from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.elo_ratings import allocate_total_goals_by_elo


PROFILE_PATH = ROOT / "pipeline" / "data" / "first-round-performance.json"
PUBLIC_PATH = ROOT / "public" / "data" / "first-round-review.json"
ELO_NAMES_PATH = ROOT / ".cache" / "pipeline" / "elo-ratings" / "aba55e5bf5205a63dbcaec83.json"
ELO_WORLD_PATH = ROOT / ".cache" / "pipeline" / "elo-ratings" / "c07c64ce7cea930c8b40dd29.json"

FIFA_SCORES_URL = "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures"
TEXT_CENTRE_URL = "https://www.espn.com/soccer/scoreboard/_/league/fifa.world"

MATCHES = [
    ("2026-06-11", "Mexico", "South Africa", 2, 0),
    ("2026-06-11", "South Korea", "Czechia", 2, 1),
    ("2026-06-12", "Canada", "Bosnia and Herzegovina", 1, 1),
    ("2026-06-12", "United States", "Paraguay", 4, 1),
    ("2026-06-13", "Qatar", "Switzerland", 1, 1),
    ("2026-06-13", "Brazil", "Morocco", 1, 1),
    ("2026-06-13", "Haiti", "Scotland", 0, 1),
    ("2026-06-13", "Australia", "Turkey", 2, 0),
    ("2026-06-14", "Germany", "Curaçao", 7, 1),
    ("2026-06-14", "Ivory Coast", "Ecuador", 1, 0),
    ("2026-06-14", "Netherlands", "Japan", 2, 2),
    ("2026-06-14", "Sweden", "Tunisia", 5, 1),
    ("2026-06-15", "Belgium", "Egypt", 1, 1),
    ("2026-06-15", "Iran", "New Zealand", 2, 2),
    ("2026-06-15", "Spain", "Cape Verde", 0, 0),
    ("2026-06-15", "Saudi Arabia", "Uruguay", 1, 1),
    ("2026-06-16", "France", "Senegal", 3, 1),
    ("2026-06-16", "Iraq", "Norway", 1, 4),
    ("2026-06-16", "Argentina", "Algeria", 3, 0),
    ("2026-06-16", "Austria", "Jordan", 3, 1),
    ("2026-06-17", "Portugal", "DR Congo", 1, 1),
    ("2026-06-17", "Uzbekistan", "Colombia", 1, 3),
    ("2026-06-17", "Ghana", "Panama", 1, 0),
    ("2026-06-17", "England", "Croatia", 4, 2),
]

ZH = {
    "Algeria": "阿尔及利亚", "Argentina": "阿根廷", "Australia": "澳大利亚", "Austria": "奥地利",
    "Belgium": "比利时", "Bosnia and Herzegovina": "波黑", "Brazil": "巴西", "Canada": "加拿大",
    "Cape Verde": "佛得角", "Colombia": "哥伦比亚", "Croatia": "克罗地亚", "Curaçao": "库拉索",
    "Czechia": "捷克", "DR Congo": "民主刚果", "Ecuador": "厄瓜多尔", "Egypt": "埃及",
    "England": "英格兰", "France": "法国", "Germany": "德国", "Ghana": "加纳", "Haiti": "海地",
    "Iran": "伊朗", "Iraq": "伊拉克", "Ivory Coast": "科特迪瓦", "Japan": "日本", "Jordan": "约旦",
    "Mexico": "墨西哥", "Morocco": "摩洛哥", "Netherlands": "荷兰", "New Zealand": "新西兰",
    "Norway": "挪威", "Panama": "巴拿马", "Paraguay": "巴拉圭", "Portugal": "葡萄牙", "Qatar": "卡塔尔",
    "Saudi Arabia": "沙特", "Scotland": "苏格兰", "Senegal": "塞内加尔", "South Africa": "南非",
    "South Korea": "韩国", "Spain": "西班牙", "Sweden": "瑞典", "Switzerland": "瑞士",
    "Tunisia": "突尼斯", "Turkey": "土耳其", "United States": "美国", "Uruguay": "乌拉圭",
    "Uzbekistan": "乌兹别克斯坦",
}

RED_CARD_DISTORTED = {frozenset(("Mexico", "South Africa"))}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cached_elo_ratings() -> dict[str, int]:
    names_payload = json.loads(ELO_NAMES_PATH.read_text(encoding="utf-8"))["value"]
    world_payload = json.loads(ELO_WORLD_PATH.read_text(encoding="utf-8"))["value"]
    names = {}
    for line in names_payload.splitlines():
        columns = line.split("\t")
        if len(columns) >= 2:
            names[columns[0]] = columns[1]
    ratings = {}
    for line in world_payload.splitlines():
        columns = line.split("\t")
        if len(columns) >= 4 and columns[3].isdigit():
            name = names.get(columns[2])
            if name:
                ratings[name] = int(columns[3])
    return ratings


def performance_status(score: float) -> str:
    if score >= 0.08:
        return "above_expectation"
    if score <= -0.08:
        return "below_expectation"
    return "near_expectation"


def status_summary(team: str, opponent: str, result: str, status: str) -> str:
    labels = {
        "above_expectation": "首轮赛果兑现高于Elo赛前中性预期",
        "below_expectation": "首轮赛果兑现低于Elo赛前中性预期",
        "near_expectation": "首轮赛果兑现大致处于Elo赛前中性预期附近",
    }
    return f"{team}首轮对阵{opponent}取得{result}；{labels[status]}。详细战术维度等待可归档文字赛况佐证。"


def build() -> dict[str, Any]:
    ratings = cached_elo_ratings()
    matches = []
    teams = []
    total_goals = 0
    for index, (match_date, home, away, home_goals, away_goals) in enumerate(MATCHES, start=1):
        total_goals += home_goals + away_goals
        home_rating = ratings.get(home, 1500)
        away_rating = ratings.get(away, 1500)
        expected_home, expected_away = allocate_total_goals_by_elo(2.55, home_rating, away_rating)
        distorted = frozenset((home, away)) in RED_CARD_DISTORTED
        high_variance = home_goals + away_goals >= 6 or abs(home_goals - expected_home) >= 3
        reliability = 0.40 if distorted else 0.50 if high_variance else 0.65
        match_id = f"md1-{index:02d}"
        sources = [
            {
                "type": "official_result",
                "url": FIFA_SCORES_URL,
                "publishedAt": f"{match_date}T23:59:00Z",
                "summary": f"FIFA赛程与赛果入口：{home} {home_goals}-{away_goals} {away}。",
                "archivedText": True,
            },
            {
                "type": "text_match_centre",
                "url": TEXT_CENTRE_URL,
                "publishedAt": f"{match_date}T23:59:00Z",
                "summary": "文字比赛中心来源索引；本地未归档逐分钟正文，因此不据此推断压迫、推进或机会质量。",
                "archivedText": False,
            },
        ]
        matches.append({
            "id": match_id,
            "date": match_date,
            "homeTeam": ZH[home],
            "awayTeam": ZH[away],
            "score": f"{home_goals}-{away_goals}",
            "redCardDistorted": distorted,
            "highVarianceFinishing": high_variance,
            "lineupStatus": "unavailable",
            "eventStatus": "partial" if distorted else "unavailable",
            "statisticsStatus": "result_only",
            "sources": sources,
        })

        for team, opponent, goals_for, goals_against, expected_for, expected_against, side in (
            (home, away, home_goals, away_goals, expected_home, expected_away, "home"),
            (away, home, away_goals, home_goals, expected_away, expected_home, "away"),
        ):
            attack_residual = goals_for - expected_for
            defense_residual = expected_against - goals_against
            # Fixed, conservative conversion. It is not fit to these 24 games.
            attack_delta = clamp(attack_residual * 0.025 * reliability, -0.08, 0.08)
            defense_delta = clamp(defense_residual * 0.025 * reliability, -0.08, 0.08)
            form_score = attack_delta + defense_delta
            status = performance_status(form_score)
            result = "胜" if goals_for > goals_against else "平" if goals_for == goals_against else "负"
            teams.append({
                "team": ZH[team],
                "teamEn": team,
                "opponent": ZH[opponent],
                "side": side,
                "observedMatchday": 1,
                "observedDate": match_date,
                "matchId": match_id,
                "scoreFor": goals_for,
                "scoreAgainst": goals_against,
                "eloBeforeReview": ratings.get(team),
                "expectedGoalsReference": round(expected_for, 4),
                "expectedGoalsAgainstReference": round(expected_against, 4),
                "performanceStatus": status,
                "summary": status_summary(ZH[team], ZH[opponent], result, status),
                "evidenceConfidence": reliability,
                "dimensions": {
                    "attackCreation": None,
                    "defensiveControl": None,
                    "midfieldProgression": None,
                    "transition": None,
                    "setPieces": None,
                    "goalkeeping": None,
                    "stamina": None,
                    "status": "insufficient_archived_text_detail",
                },
                "commentaryEvidence": {
                    "mode": "text_only",
                    "archivedMinuteByMinute": False,
                    "labels": [],
                    "note": "文字赛况入口已记录，但逐分钟正文未归档；文本评价不直接修改概率或xG。",
                    "sources": sources,
                },
                "objectiveForm": {
                    "attackDelta": round(attack_delta, 4),
                    "defenseDelta": round(defense_delta, 4),
                    "admissionStatus": "observation_only" if distorted else "enabled",
                    "derivedFrom": ["official_result", "pre-review_elo_reference"],
                    "redCardAdjusted": distorted,
                    "finishingOutlierShrunk": high_variance,
                    "opponentStrengthAdjusted": True,
                    "leadingStateAdjusted": False,
                },
            })

    payload = {
        "schemaVersion": 1,
        "generatedAt": "2026-06-18T13:00:00+08:00",
        "round": {
            "name": "group_matchday_1",
            "completedLocalDate": "2026-06-17",
            "matches": len(matches),
            "teams": len(teams),
            "totalGoals": total_goals,
            "averageGoals": round(total_goals / len(matches), 3),
            "commentaryMode": "text_only",
        },
        "method": {
            "stateCapPerTeamDirectionXg": 0.12,
            "conversionWasFitOnFirstRound": False,
            "commentaryDirectlyChangesProbability": False,
            "missingTextPolicy": "show evidence gap; do not invent tactical ratings",
            "productionPolicy": "bounded tournament form can apply; distribution changes remain shadow-only",
        },
        "matches": matches,
        "teams": sorted(teams, key=lambda item: item["team"]),
    }
    return payload


def main() -> None:
    payload = build()
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(content, encoding="utf-8")
    PUBLIC_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {len(payload['teams'])} team profiles across {len(payload['matches'])} matches")


if __name__ == "__main__":
    main()
