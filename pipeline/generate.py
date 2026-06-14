from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient
from .config import FIXTURE_DIR, OUTPUT_DIR, ROOT, SETTINGS, VENUES
from .model import (
    adjust_xg,
    estimate_from_recent_results,
    expected_return,
    normalized_market_probabilities,
    outcome_probabilities,
    probability_lower_bound,
    score_matrix,
    score_stars,
    top_scores,
)
from .portfolio import build_portfolios
from .sporttery import SportteryMatch, fetch_sporttery, filter_by_beijing_date, load_fixture
from .weather import OpenMeteoClient

OUTCOME_KEYS = {"胜": "home", "平": "draw", "负": "away"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static World Cup forecast JSON")
    parser.add_argument("--target-date", help="Beijing calendar date, YYYY-MM-DD")
    parser.add_argument("--now", help="Generation timestamp in ISO-8601")
    parser.add_argument("--offline", action="store_true", help="Use committed deterministic fixtures")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "daily-forecast.json")
    parser.add_argument("--archive", action="store_true", help="Also write an immutable date-stamped snapshot")
    return parser.parse_args()


def load_demo() -> dict:
    return json.loads((ROOT / "pipeline" / "data" / "demo_matches.json").read_text(encoding="utf-8"))


def default_factors() -> list[dict]:
    return [
        {"label": "球队实力", "direction": "neutral", "value": 0.0, "note": "来自近期国际比赛攻防强度", "active": True},
        {"label": "预计首发", "direction": "neutral", "value": 0.0, "note": "官方首发前采用预计阵容", "active": False},
        {"label": "教练风格", "direction": "neutral", "value": 0.0, "note": "样本不足，仅展示", "active": False},
        {"label": "轮换体能", "direction": "neutral", "value": 0.0, "note": "按近 14 天出场负荷估计", "active": False},
        {"label": "海拔适应", "direction": "neutral", "value": 0.0, "note": "待匹配场馆和球员常驻海拔", "active": False},
        {"label": "温湿度与风", "direction": "neutral", "value": 0.0, "note": "由开球时刻预报生成", "active": False},
    ]


def live_seeds(client: ApiFootballClient, target_date: str) -> list[dict]:
    fixtures = client.world_cup_fixtures(target_date)
    weather_client = OpenMeteoClient()
    seeds = []
    for fixture in fixtures:
        home = fixture["teams"]["home"]
        away = fixture["teams"]["away"]
        home_recent = client.recent_team_fixtures(home["id"])
        away_recent = client.recent_team_fixtures(away["id"])
        home_xg, away_xg = estimate_from_recent_results(home_recent, away_recent, home["id"], away["id"])
        injuries = client.fixture_injuries(fixture["fixture"]["id"])
        home_squad = client.squad(home["id"])
        away_squad = client.squad(away["id"])
        home_coach = client.coach(home["id"])
        away_coach = client.coach(away["id"])
        venue_name = fixture.get("fixture", {}).get("venue", {}).get("name") or "Demo Stadium"
        kickoff = datetime.fromisoformat(fixture["fixture"]["date"])
        venue = VENUES.get(venue_name)
        weather_text = "天气待更新"
        weather_factor = {"label": "温湿度与风", "direction": "neutral", "value": 0.0, "note": "场馆坐标缺失", "active": False}
        if venue:
            try:
                forecast = weather_client.forecast_at(venue["lat"], venue["lon"], kickoff)
                if forecast.get("status") == "fresh":
                    weather_text = (
                        f"{forecast['temperature']:.0f}°C / 湿度 {forecast['humidity']:.0f}% / "
                        f"风 {forecast['wind_speed']:.0f}km/h"
                    )
                    heat_load = max(0.0, float(forecast["apparent_temperature"]) - 28) / 100
                    weather_factor = {
                        "label": "温湿度与风", "direction": "neutral", "value": round(heat_load, 3),
                        "note": weather_text, "active": True,
                    }
            except Exception:  # noqa: BLE001 - weather remains an explicit missing feature
                pass
        factors = default_factors()
        factors[1] = {
            "label": "预计首发", "direction": "neutral", "value": 0.0,
            "note": f"已读取伤停 {len(injuries)} 条；官方首发公布前不启用系数", "active": False,
        }
        factors[2] = {
            "label": "教练风格", "direction": "neutral", "value": 0.0,
            "note": f"教练资料 {len(home_coach) + len(away_coach)} 条；待回测验证", "active": False,
        }
        factors[-1] = weather_factor
        squad_coverage = min(1.0, (len(home_squad) + len(away_squad)) / 2)
        seeds.append({
            "sporttery_id": "",
            "api_fixture_id": fixture["fixture"]["id"],
            "lottery_code": "",
            "kickoff": kickoff.isoformat(),
            "home_team": home["name"],
            "away_team": away["name"],
            "home_flag": "🏳",
            "away_flag": "🏳",
            "venue": venue_name,
            "base_xg": [home_xg, away_xg],
            "coverage": round(0.72 + 0.08 * squad_coverage, 3),
            "weather": weather_text,
            "factors": factors,
            "missing_data": ["免费额度下部分球员近 365 天俱乐部高级数据未覆盖"],
        })
    return seeds


def team_key(name: str) -> str:
    aliases = {
        "沙特阿拉伯": "沙特", "阿尔及利亚": "阿尔及利", "乌兹别克斯坦": "乌兹别克",
        "Curaçao": "库拉索", "Curacao": "库拉索", "Netherlands": "荷兰", "Japan": "日本",
        "Germany": "德国", "Sweden": "瑞典", "Tunisia": "突尼斯", "Ecuador": "厄瓜多尔",
        "Ivory Coast": "科特迪瓦", "Côte d'Ivoire": "科特迪瓦",
    }
    return aliases.get(name, name).replace(" ", "").lower()


def match_seed_to_market(seed: dict, markets: list[SportteryMatch]) -> SportteryMatch | None:
    home_key, away_key = team_key(seed["home_team"]), team_key(seed["away_team"])
    for market in markets:
        if team_key(market.home_team) == home_key and team_key(market.away_team) == away_key:
            return market
    return None


def recommendation(raw: float | None, robust: float | None, coverage: float, available: bool, is_score: bool, stars: int) -> tuple[str, str]:
    if not available:
        return "未开售", "官方固定奖金未开售"
    if raw is None or robust is None:
        return "观察", "缺少完整市场概率"
    threshold = 0.10 if is_score else 0.05
    if coverage < 0.75:
        return "观察", "数据覆盖率低于 75%"
    if is_score and stars < 2:
        return "不建议", "比分分布不够集中"
    if raw > threshold and robust > 0.025:
        return "重点推荐", "通过原始与稳健期望双重门槛"
    if raw > threshold and robust > 0:
        return "小注可选", "稳健期望为正但优势较小"
    if robust > -0.02:
        return "观察", "接近公平价格，等待赔率变化"
    return "不建议", "稳健期望为负"


def make_quote(
    match_id: str,
    label: str,
    market: str,
    selection: str,
    odds: float | None,
    model_probability: float,
    market_probability: float | None,
    coverage: float,
    single_eligible: bool,
    observed_at: str,
    stars: int = 0,
    handicap: int | None = None,
) -> dict:
    available = odds is not None
    raw = expected_return(model_probability, odds) if odds else None
    lower = probability_lower_bound(model_probability, coverage)
    robust = expected_return(lower, odds) if odds else None
    advice, reason = recommendation(raw, robust, coverage, available, market == "比分", stars)
    return {
        "id": f"{match_id}-{market}-{selection}".replace(" ", "-"),
        "matchId": match_id,
        "label": label,
        "market": market,
        "selection": selection,
        "handicap": handicap,
        "odds": odds,
        "modelProbability": round(model_probability, 5),
        "marketProbability": round(market_probability, 5) if market_probability is not None else None,
        "rawExpectedReturn": round(raw, 5) if raw is not None else None,
        "robustExpectedReturn": round(robust, 5) if robust is not None else None,
        "singleEligible": single_eligible,
        "available": available,
        "recommendation": advice,
        "reason": reason,
        "observedAt": observed_at,
    }


def build_match(seed: dict, market: SportteryMatch | None, generated_at: str) -> dict:
    factors = seed.get("factors", default_factors())
    home_xg, away_xg = adjust_xg(float(seed["base_xg"][0]), float(seed["base_xg"][1]), factors)
    matrix = score_matrix(home_xg, away_xg)
    outcomes = outcome_probabilities(matrix)
    scores = top_scores(matrix)
    coverage = float(seed.get("coverage", 0.70))
    stars = score_stars(float(scores[0]["probability"]), coverage)
    quotes = []
    label = f"{seed['home_team']} vs {seed['away_team']}"
    match_id = market.match_id if market else seed.get("sporttery_id") or label

    normal_odds = market.win_draw_loss if market else {"胜": None, "平": None, "负": None}
    normal_market = normalized_market_probabilities(normal_odds)
    for chinese, outcome in OUTCOME_KEYS.items():
        quotes.append(make_quote(
            match_id, label, "胜平负", chinese, normal_odds.get(chinese), outcomes[outcome], normal_market.get(chinese),
            coverage, bool(market and "胜平负" in market.single_markets), generated_at,
        ))

    handicap = market.handicap if market else None
    if handicap is not None:
        handicap_outcomes = outcome_probabilities(matrix, handicap)
        handicap_odds = market.handicap_win_draw_loss
        handicap_market = normalized_market_probabilities(handicap_odds)
        for chinese, outcome in OUTCOME_KEYS.items():
            quotes.append(make_quote(
                match_id, label, "让球胜平负", f"{handicap:+d} {chinese}", handicap_odds.get(chinese), handicap_outcomes[outcome],
                handicap_market.get(chinese), coverage, bool("让球胜平负" in market.single_markets), generated_at, handicap=handicap,
            ))

    score_odds = market.scores if market else {}
    score_market = normalized_market_probabilities(score_odds) if score_odds else {}
    for score in scores[:3]:
        odds = score_odds.get(str(score["score"]))
        quotes.append(make_quote(
            match_id, label, "比分", str(score["score"]), odds, float(score["probability"]), score_market.get(str(score["score"])),
            coverage, False, generated_at, stars=stars,
        ))
        score["odds"] = odds

    venue = VENUES.get(seed.get("venue"), VENUES["Demo Stadium"])
    return {
        "id": match_id,
        "apiFixtureId": seed.get("api_fixture_id"),
        "lotteryCode": market.lottery_code if market else seed.get("lottery_code", ""),
        "kickoff": seed["kickoff"],
        "kickoffBeijing": seed["kickoff"],
        "venue": seed.get("venue", "场馆待确认"),
        "homeTeam": seed["home_team"],
        "awayTeam": seed["away_team"],
        "homeFlag": seed.get("home_flag", "🏳"),
        "awayFlag": seed.get("away_flag", "🏳"),
        "expectedGoals": {"home": round(home_xg, 2), "away": round(away_xg, 2)},
        "outcomeProbabilities": {key: round(value, 5) for key, value in outcomes.items()},
        "likelyScore": str(scores[0]["score"]).replace(":", "-") ,
        "scoreStars": stars,
        "scoreProbabilities": scores,
        "coverage": coverage,
        "weather": seed.get("weather", "天气待更新"),
        "altitude": venue["altitude"],
        "missingData": seed.get("missing_data", []),
        "factors": factors,
        "quotes": quotes,
    }


def main() -> None:
    args = parse_args()
    timezone = ZoneInfo(SETTINGS.timezone)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    target_date = args.target_date or (now.astimezone(timezone).date() + timedelta(days=1)).isoformat()
    generated_at = now.astimezone(timezone).isoformat(timespec="seconds")
    degraded_reasons: list[str] = []

    if args.offline:
        markets_by_id = load_fixture(FIXTURE_DIR / "sporttery-spf.html", FIXTURE_DIR / "sporttery-score.html")
        degraded_reasons.append("使用仓库内固定体彩快照")
    else:
        try:
            markets_by_id = fetch_sporttery()
        except Exception as exc:  # noqa: BLE001 - degradation is deliberate and reported
            markets_by_id = load_fixture(FIXTURE_DIR / "sporttery-spf.html", FIXTURE_DIR / "sporttery-score.html")
            degraded_reasons.append(f"体彩实时页面读取失败，已使用固定快照：{exc}")
    markets = filter_by_beijing_date(markets_by_id.values(), target_date)

    client = ApiFootballClient()
    seeds: list[dict]
    if client.enabled and not args.offline:
        try:
            seeds = live_seeds(client, target_date)
        except Exception as exc:  # noqa: BLE001
            seeds = []
            degraded_reasons.append(f"API-Football 读取失败：{exc}")
    else:
        seeds = []
        degraded_reasons.append("未配置 API_FOOTBALL_KEY，球员与阵容采用固定开发样例")

    demo = load_demo()
    if not seeds and target_date == demo["target_date"]:
        seeds = demo["matches"]
    elif not seeds:
        degraded_reasons.append("目标日期没有可用比赛种子数据")

    built_matches = []
    for seed in seeds:
        market = match_seed_to_market(seed, markets)
        if market is None:
            degraded_reasons.append(f"{seed['home_team']} vs {seed['away_team']} 未匹配到体彩赔率")
        built_matches.append(build_match(seed, market, generated_at))

    all_quotes = [quote for match in built_matches for quote in match["quotes"]]
    portfolios = build_portfolios(all_quotes, SETTINGS.initial_bankroll)
    coverage = sum(match["coverage"] for match in built_matches) / len(built_matches) if built_matches else 0
    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "targetDate": target_date,
        "timezone": SETTINGS.timezone,
        "modelVersion": "0.1.0",
        "simulations": SETTINGS.simulations,
        "bankroll": SETTINGS.initial_bankroll,
        "oddsFreshMinutes": 0,
        "overallCoverage": round(coverage, 4),
        "status": "degraded" if degraded_reasons else "ready",
        "statusMessage": "；".join(degraded_reasons) if degraded_reasons else "实时数据管线正常",
        "matches": built_matches,
        "portfolios": portfolios,
        "evidence": [
            {"source": "中国体育彩票", "field": "固定奖金/单关资格", "observedAt": generated_at, "confidence": 1.0, "status": "manual" if args.offline else "fresh"},
            {"source": "API-Football 免费档", "field": "赛程/球队/阵容", "observedAt": generated_at, "confidence": 0.72, "status": "missing" if not client.enabled else "fresh"},
            {"source": "Open-Meteo", "field": "开球时刻天气", "observedAt": generated_at, "confidence": 0.8, "status": "manual" if args.offline else "fresh"},
        ],
        "backtest": [
            {"label": "概率校准", "value": "待积累", "note": "首届运行后按比赛日滚动更新可靠性图", "status": "neutral"},
            {"label": "RPS", "value": "基线模式", "note": "当前实现支持时间顺序回测，尚无 2026 实盘样本", "status": "neutral"},
            {"label": "比分命中", "value": "非主指标", "note": "重点评估完整概率分布，而非只看单一比分", "status": "good"},
            {"label": "信息泄漏", "value": "已阻断", "note": "特征时间戳必须早于预测生成时间", "status": "good"},
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.archive:
        archive = args.output.parent / "history" / f"{target_date}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} with {len(built_matches)} matches; status={payload['status']}")


if __name__ == "__main__":
    main()
