from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient
from .availability import apply_availability, load_availability
from .config import (
    FIXTURE_DIR,
    MANUAL_DIR,
    OUTPUT_DIR,
    OUTCOME_RECOMMENDATION_THRESHOLD,
    PIPELINE_VERSION,
    ROOT,
    SETTINGS,
    VENUES,
    FIXTURE_VENUES,
)
from .model_registry import check_and_apply_adoption, get_model_version
from .model_policy import load_model_policy
from .odds_history import save_odds_snapshot
from .elo_ratings import EloRatingsClient, allocate_total_goals_by_elo, expected_goals_from_elo
from .goal_models import goal_model_xg
from .football_data import (
    FootballDataClient,
    TEAM_NAMES_ZH,
    api_football_shape,
    localized_team_name,
    parse_utc,
    team_flag,
)
from .factor_gate import apply_factor_admissions, load_factor_admissions
from .model import (
    adjust_xg,
    estimate_from_recent_results,
    expected_return,
    half_full_probabilities,
    normalized_market_probabilities,
    outcome_probabilities,
    probability_lower_bound,
    score_matrix,
    score_stars,
    total_goals_probabilities,
    top_scores,
)
from .lineup import apply_lineup_impacts
from .intelligence import apply_intelligence, load_daily_intelligence
from .current_tournament import apply_current_tournament_context
from .draw_risk import apply_draw_risk_layer
from .market_guard import apply_market_strength_calibration, market_conflict_decision
from .portfolio import build_portfolios
from .provenance import build_snapshot_manifest
from .simulation import MatchSimulationInput, TournamentSimulation, simulate_tournament
from .sporttery import SportteryMatch, fetch_sporttery, filter_by_beijing_date, load_fixture
from .two_round_form import apply_two_round_form, load_two_round_profiles
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


def preserve_parlay_matches(
    fresh_matches: list[dict[str, Any]],
    cache_path: Path,
    target_date: str,
    generated_at: str,
) -> tuple[list[dict[str, Any]], int]:
    cached_matches: list[dict[str, Any]] = []
    if cache_path.exists():
        try:
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_matches = cached_payload.get("matches", [])
        except (OSError, json.JSONDecodeError, AttributeError):
            cached_matches = []

    def remains_selectable(match: dict[str, Any]) -> bool:
        kickoff_date = str(match.get("kickoffBeijing", ""))[:10]
        quotes = match.get("quotes", [])
        return (
            kickoff_date > target_date
            and isinstance(quotes, list)
            and any(quote.get("odds") for quote in quotes if isinstance(quote, dict))
        )

    merged = {
        match["id"]: match
        for match in cached_matches
        if isinstance(match, dict) and match.get("id") and remains_selectable(match)
    }
    cached_ids = set(merged)
    fresh_ids = {match.get("id") for match in fresh_matches}
    for match in fresh_matches:
        if match.get("id") and remains_selectable(match):
            merged[match["id"]] = match

    published = sorted(merged.values(), key=lambda match: match["kickoffBeijing"])
    fallback_count = sum(match["id"] in cached_ids and match["id"] not in fresh_ids for match in published)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"generatedAt": generated_at, "matches": published}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return published, fallback_count


def local_snapshot_paths() -> list[Path]:
    return [
        ROOT / "pipeline" / "data" / "demo_matches.json",
        ROOT / "pipeline" / "data" / "fifa-2026-discipline.json",
        ROOT / "pipeline" / "data" / "factor-admissions.json",
        ROOT / "pipeline" / "data" / "two-round-performance.json",
        ROOT / "pipeline" / "data" / "tournament-availability.json",
        ROOT / "public" / "data" / "two-round-match-timelines.json",
        ROOT / "pipeline" / "data" / "fifa-2026-annex-c.json",
        ROOT / "pipeline" / "data" / "model-policy.json",
        FIXTURE_DIR / "sporttery-spf.html",
        FIXTURE_DIR / "sporttery-score.html",
        *sorted(MANUAL_DIR.glob("*.csv")),
        *sorted((MANUAL_DIR / "intelligence").rglob("*.json")),
    ]


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


def football_data_seeds(client: FootballDataClient, target_date: str, all_matches: list[dict] | None = None) -> list[dict]:
    timezone = ZoneInfo(SETTINGS.timezone)
    all_matches = all_matches if all_matches is not None else client.world_cup_matches()
    fixtures = client.matches_on_beijing_date(target_date, all_matches)
    seeds = []
    try:
        elo_ratings = EloRatingsClient().ratings()
    except Exception:  # noqa: BLE001 - tournament results remain a valid lower-coverage fallback
        elo_ratings = {}
    elo_median = sorted(elo_ratings.values())[len(elo_ratings) // 2] if elo_ratings else None
    model_policy = load_model_policy()
    elo_allocation_weight = float(model_policy["eloAllocationWeight"])
    for fixture in fixtures:
        kickoff_utc = parse_utc(fixture["utcDate"])
        kickoff = kickoff_utc.astimezone(timezone)
        home = fixture["homeTeam"]
        away = fixture["awayTeam"]
        finished = [
            match for match in all_matches
            if match.get("status") == "FINISHED" and parse_utc(match["utcDate"]) < kickoff_utc
        ]
        home_recent = [
            match for match in finished
            if home["id"] in {match.get("homeTeam", {}).get("id"), match.get("awayTeam", {}).get("id")}
        ]
        away_recent = [
            match for match in finished
            if away["id"] in {match.get("homeTeam", {}).get("id"), match.get("awayTeam", {}).get("id")}
        ]
        home_name = localized_team_name(home)
        away_name = localized_team_name(away)
        home_name_en = home.get("name", home_name)  # English name for goal model CSV lookup
        away_name_en = away.get("name", away_name)
        home_rating = elo_ratings.get(home_name)
        away_rating = elo_ratings.get(away_name)
        ratings_complete = home_rating is not None and away_rating is not None
        ratings_partial = (home_rating is None) != (away_rating is None)
        sample_count = len(home_recent) + len(away_recent)
        if ratings_complete:
            gm = goal_model_xg(home_name_en, away_name_en, target_date)
            if gm is not None:
                total_xg = sum(gm)
                elo_home_xg, elo_away_xg = allocate_total_goals_by_elo(total_xg, home_rating, away_rating)
                home_xg = (1 - elo_allocation_weight) * gm[0] + elo_allocation_weight * elo_home_xg
                away_xg = (1 - elo_allocation_weight) * gm[1] + elo_allocation_weight * elo_away_xg
                model_note = (
                    f"进球模型估计总量 {total_xg:.2f}，Elo {home_rating} vs {away_rating} "
                    f"按历史验证权重 {elo_allocation_weight:.2f} 分配双方份额；赛前样本 {sample_count} 场"
                )
            else:
                home_xg, away_xg = expected_goals_from_elo(home_rating, away_rating)
                total_xg = home_xg + away_xg
                model_note = f"Elo {home_rating} vs {away_rating}；总量回退至 {total_xg:.2f}，本届赛前补充样本 {sample_count} 场"
        elif ratings_partial and elo_median is not None:
            home_xg, away_xg = expected_goals_from_elo(home_rating or elo_median, away_rating or elo_median)
            model_note = f"Elo {home_rating or '缺失'} vs {away_rating or '缺失'}；缺失一方以全球中位数 {elo_median} 收缩"
        else:
            home_xg, away_xg = estimate_from_recent_results(
                api_football_shape(home_recent),
                api_football_shape(away_recent),
                home["id"],
                away["id"],
            )
            model_note = f"双方 Elo 缺失；读取本届赛前已结束比赛 {sample_count} 场并收缩到中性基线"
        factors = default_factors()
        factors[0] = {
            "label": "球队实力", "direction": "neutral", "value": 0.0,
            "note": model_note,
            "active": True,
            "admissionStatus": "core",
        }
        factors[1] = {
            "label": "预计首发", "direction": "neutral", "value": 0.0,
            "note": "免费数据源不提供可靠的赛前首发与伤停，未纳入系数",
            "active": False,
        }
        factors[2] = {
            "label": "教练风格", "direction": "neutral", "value": 0.0,
            "note": "免费数据源不提供教练战术变化，等待带来源的人工校正",
            "active": False,
        }
        venue_name = (
            FIXTURE_VENUES.get((fixture["homeTeam"]["tla"], fixture["awayTeam"]["tla"]))
            or fixture.get("venue")
            or "场馆待确认"
        )
        venue = VENUES.get(venue_name)
        weather_text = "场馆坐标待确认，天气未启用"
        if venue:
            try:
                forecast = OpenMeteoClient().forecast_at(venue["lat"], venue["lon"], kickoff)
                if forecast.get("status") == "fresh":
                    weather_text = (
                        f"{forecast['temperature']:.0f}°C / 湿度 {forecast['humidity']:.0f}% / "
                        f"风 {forecast['wind_speed']:.0f}km/h"
                    )
                    factors[-1] = {
                        "label": "温湿度与风", "direction": "neutral", "value": 0.0,
                        "note": weather_text, "active": True,
                    }
            except Exception:  # noqa: BLE001 - missing weather is reported in the output
                pass
        missing_data = ["缺少可靠的预计首发、实时伤停和球员近 365 天俱乐部高级数据"]
        if ratings_partial:
            missing_team = home_name if home_rating is None else away_name
            missing_data.append(f"{missing_team} 的 Elo 评分缺失，暂以全球中位数收缩")
        elif not ratings_complete:
            missing_data.append("双方 Elo 评分缺失，基础实力仅使用赛前可见比赛结果")
        seeds.append({
            "sporttery_id": "",
            "api_fixture_id": fixture["id"],
            "lottery_code": "",
            "kickoff": kickoff.isoformat(timespec="seconds"),
            "home_team": home_name,
            "away_team": away_name,
            "home_flag": team_flag(home),
            "away_flag": team_flag(away),
            "venue": venue_name,
            "base_xg": [home_xg, away_xg],
            "model_decomposition": {
                "totalGoalsProvider": "hierarchical_goal_model" if ratings_complete and gm is not None else "elo_fallback",
                "strengthAllocator": "world_football_elo",
                "allocationPolicy": "separated_total_and_strength_v1",
                "eloAllocationWeight": elo_allocation_weight,
                "allocationValidationSet": model_policy.get("validationSet", "FIFA World Cup 2018 and 2022"),
                "estimatedTotalGoals": round(home_xg + away_xg, 4),
            },
            "coverage": round(min(0.86, (0.80 if ratings_complete else 0.66 if ratings_partial else 0.58) + sample_count * 0.01), 3),
            "weather": weather_text,
            "factors": factors,
            "elo_live": ratings_complete,
            "missing_data": missing_data,
        })
    return seeds


def team_key(name: str) -> str:
    aliases = {
        "沙特阿拉伯": "沙特", "阿尔及利亚": "阿尔及利", "乌兹别克斯坦": "乌兹别克",
        "刚果金": "民主刚果",
        "Curaçao": "库拉索", "Curacao": "库拉索", "Netherlands": "荷兰", "Japan": "日本",
        "Germany": "德国", "Sweden": "瑞典", "Tunisia": "突尼斯", "Ecuador": "厄瓜多尔",
        "Ivory Coast": "科特迪瓦", "Côte d'Ivoire": "科特迪瓦", "DR Congo": "民主刚果",
        "Congo DR": "民主刚果",
    }
    return aliases.get(name, name).replace(" ", "").lower()


def _market_date_matches_seed(seed: dict, market: SportteryMatch) -> bool:
    if not market.kickoff_text:
        return True
    try:
        seed_prefix = datetime.fromisoformat(seed["kickoff"]).strftime("%m-%d")
    except ValueError:
        return True
    return market.kickoff_text.startswith(seed_prefix)


def match_seed_to_market(seed: dict, markets: list[SportteryMatch]) -> SportteryMatch | None:
    home_key, away_key = team_key(seed["home_team"]), team_key(seed["away_team"])
    for market in markets:
        if (
            _market_date_matches_seed(seed, market)
            and team_key(market.home_team) == home_key
            and team_key(market.away_team) == away_key
        ):
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


def outcome_recommendation_decision(outcomes: dict[str, float]) -> dict[str, float | str]:
    selection = max(outcomes, key=outcomes.get)
    probability = float(outcomes[selection])
    return {
        "threshold": OUTCOME_RECOMMENDATION_THRESHOLD,
        "maxProbability": probability,
        "selection": selection,
        "status": "recommended" if probability >= OUTCOME_RECOMMENDATION_THRESHOLD else "watch",
    }


def apply_mutual_draw_outcome_guard(
    decision: dict[str, float | str],
    outcomes: dict[str, float],
    seed: dict,
) -> dict[str, float | str]:
    current = seed.get("current_tournament") or {}
    if not current.get("mutualDrawUtility"):
        return decision
    selection = str(decision.get("selection") or "")
    if selection == "draw":
        return decision
    draw_probability = float(outcomes.get("draw", 0.0))
    leader_probability = float(decision.get("maxProbability") or 0.0)
    if draw_probability <= 0.0 or leader_probability <= 0.0:
        return decision
    guarded = dict(decision)
    guarded["guard"] = "third_round_mutual_draw_utility"
    if leader_probability - draw_probability <= 0.04:
        guarded["selection"] = "draw"
        guarded["maxProbability"] = draw_probability
        guarded["status"] = "watch"
        return guarded
    if guarded.get("status") == "recommended" and draw_probability >= 0.18 and draw_probability >= leader_probability * 0.30:
        guarded["status"] = "watch"
    return guarded


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
    excluded_scores: list[str] | None = None,
    recommendation_gate: tuple[bool, str] | None = None,
    market_conflict: dict[str, Any] | None = None,
    odds_source: str = "official",
    metadata: dict[str, Any] | None = None,
) -> dict:
    available = odds is not None
    raw = expected_return(model_probability, odds) if odds else None
    lower = probability_lower_bound(model_probability, coverage)
    robust = expected_return(lower, odds) if odds else None
    advice, reason = recommendation(raw, robust, coverage, available, market == "比分", stars)
    if available and recommendation_gate is not None and not recommendation_gate[0]:
        advice, reason = "观察", recommendation_gate[1]
    conflict = market_conflict or {
        "status": "unavailable",
        "blocked": True,
        "maxGap": None,
        "modelFavorite": None,
        "marketFavorite": None,
        "reason": "缺少市场冲突判断",
    }
    if available and market_conflict is not None and conflict["blocked"]:
        advice, reason = "观察", str(conflict["reason"])
    formal_eligible = bool(
        available
        and odds_source == "official"
        and advice in {"重点推荐", "小注可选"}
        and robust is not None
        and robust > 0
        and not conflict["blocked"]
        and (recommendation_gate is None or recommendation_gate[0])
    )
    return {
        "id": f"{match_id}-{market}-{selection}".replace(" ", "-"),
        "matchId": match_id,
        "label": label,
        "market": market,
        "selection": selection,
        "handicap": handicap,
        "excludedScores": excluded_scores or [],
        "odds": odds,
        "modelProbability": round(model_probability, 5),
        "marketProbability": round(market_probability, 5) if market_probability is not None else None,
        "coverage": round(coverage, 4),
        "rawExpectedReturn": round(raw, 5) if raw is not None else None,
        "robustExpectedReturn": round(robust, 5) if robust is not None else None,
        "singleEligible": single_eligible,
        "available": available,
        "recommendation": advice,
        "reason": reason,
        "oddsSource": odds_source,
        "marketConflict": conflict,
        "formalEligible": formal_eligible,
        "formalBlockReason": None if formal_eligible else reason,
        "observedAt": observed_at,
        **(metadata or {}),
    }


def score_selection_probability(selection: str, matrix: list[list[float]], offered: set[str]) -> float:
    if ":" in selection and selection.replace(":", "").isdigit():
        home, away = (int(value) for value in selection.split(":"))
        return matrix[home][away] if home < len(matrix) and away < len(matrix[home]) else 0.0
    other_outcome = {"胜其它": "home", "平其它": "draw", "负其它": "away"}.get(selection)
    if other_outcome is None:
        return 0.0
    probability = 0.0
    for home, row in enumerate(matrix):
        for away, value in enumerate(row):
            outcome = "home" if home > away else "draw" if home == away else "away"
            if outcome == other_outcome and f"{home}:{away}" not in offered:
                probability += value
    return probability


def _sample_odds(probability: float, margin: float = 0.08) -> float | None:
    """Generate a sample decimal odds from a model probability with a margin.

    Returns None when the probability is too small to price safely.
    """
    if probability <= 0.001:
        return None
    return round(max(1.01, 1.0 / probability * (1.0 - margin)), 2)


def _sample_odds_dict(probabilities: dict[str, float], margin: float = 0.08) -> dict[str, float | None]:
    """Convert probability dict to sample odds dict."""
    return {key: _sample_odds(value, margin) for key, value in probabilities.items()}


def fallback_handicap(home_xg: float, away_xg: float) -> int:
    # The line is applied to the home score: favorites give goals, underdogs receive them.
    return -round(home_xg - away_xg)


def _score_outcome(score: str) -> str:
    home, away = (int(value) for value in str(score).replace(":", "-").split("-"))
    return "home" if home > away else "draw" if home == away else "away"


def _third_round_open_game_context(seed: dict[str, Any]) -> bool:
    current = seed.get("current_tournament") or {}
    if current.get("policy") not in {
        "matchday_three_scenarios_annex_c_v3_open_game",
        "matchday_three_scenarios_annex_c_v4_draw_utility",
    }:
        return False
    if current.get("mutualDrawUtility"):
        return False
    motivations = {str(current.get("homeMotivation") or ""), str(current.get("awayMotivation") or "")}
    scenarios = [current.get("homeScenarios") or {}, current.get("awayScenarios") or {}]
    return (
        any(bool(scenario.get("firstPlacePathIncentive")) for scenario in scenarios)
        or any(float(scenario.get("thirdScenarioShare") or 0.0) >= 0.15 for scenario in scenarios)
        or bool(motivations & {"must_win", "goal_difference_chase", "eliminated"})
    )


def select_likely_score(
    scores: list[dict[str, Any]],
    outcome_decision: dict[str, Any],
    seed: dict[str, Any],
) -> tuple[str, str]:
    top_score = str(scores[0]["score"]).replace(":", "-")
    current = seed.get("current_tournament") or {}
    if current.get("mutualDrawUtility") and _score_outcome(top_score) != "draw":
        top_probability = float(scores[0]["probability"])
        draw_scores = [
            item for item in scores
            if _score_outcome(str(item["score"])) == "draw"
            and float(item["probability"]) >= top_probability * 0.55
        ]
        if draw_scores:
            return str(draw_scores[0]["score"]).replace(":", "-"), "third_round_mutual_draw_score"
    selection = str(outcome_decision.get("selection") or "")
    if (
        selection not in {"home", "away"}
        or _score_outcome(top_score) == selection
        or not _third_round_open_game_context(seed)
    ):
        return top_score, "top_score_probability"

    top_probability = float(scores[0]["probability"])
    aligned = [
        item for item in scores
        if _score_outcome(str(item["score"])) == selection
        and float(item["probability"]) >= top_probability * 0.72
    ]
    if not aligned:
        return top_score, "top_score_probability"
    return str(aligned[0]["score"]).replace(":", "-"), "third_round_outcome_aligned_score"


def build_match(
    seed: dict,
    market: SportteryMatch | None,
    generated_at: str,
    simulation: TournamentSimulation | None = None,
) -> dict:
    factors = seed.get("factors", default_factors())
    home_xg, away_xg = adjust_xg(float(seed["base_xg"][0]), float(seed["base_xg"][1]), factors)
    match_id = market.match_id if market else seed.get("sporttery_id") or f"{seed['home_team']} vs {seed['away_team']}"
    simulated = simulation.summaries.get(match_id) if simulation else None
    matrix = simulated["matrix"] if simulated else score_matrix(home_xg, away_xg)
    raw_outcomes = simulated["outcomes"] if simulated else outcome_probabilities(matrix)
    draw_risk_result = apply_draw_risk_layer(
        raw_outcomes,
        {
            **seed,
            "base_xg": [home_xg, away_xg],
        },
    )
    outcomes = draw_risk_result.probabilities
    outcome_decision = apply_mutual_draw_outcome_guard(
        outcome_recommendation_decision(outcomes),
        outcomes,
        seed,
    )
    scores = top_scores(matrix)
    likely_score, likely_score_source = select_likely_score(scores, outcome_decision, seed)
    no_live_market = market is None
    coverage = float(seed.get("coverage", 0.70))
    if no_live_market:
        coverage = max(0.0, coverage - 0.05)
    stars = score_stars(float(scores[0]["probability"]), coverage)
    quotes = []
    label = f"{seed['home_team']} vs {seed['away_team']}"
    quote_metadata = {
        "kickoffBeijing": seed["kickoff"],
        "lotteryCode": market.lottery_code if market else seed.get("lottery_code", ""),
        "matchDate": datetime.fromisoformat(seed["kickoff"]).date().isoformat(),
    }

    if market:
        normal_odds = market.win_draw_loss
    else:
        normal_odds = _sample_odds_dict(
            {"胜": outcomes["home"], "平": outcomes["draw"], "负": outcomes["away"]}
        )
    normal_market = normalized_market_probabilities(normal_odds)
    normal_model = {"胜": outcomes["home"], "平": outcomes["draw"], "负": outcomes["away"]}
    normal_conflict = market_conflict_decision(normal_model, normal_market)
    for chinese, outcome in OUTCOME_KEYS.items():
        quotes.append(make_quote(
            match_id, label, "胜平负", chinese, normal_odds.get(chinese), outcomes[outcome], normal_market.get(chinese),
            coverage, bool(market and "胜平负" in market.single_markets), generated_at,
            recommendation_gate=(
                outcome_decision["status"] == "recommended",
                f"胜平负最高概率 {float(outcome_decision['maxProbability']):.1%} 低于 60% 门槛",
            ),
            market_conflict=normal_conflict,
            odds_source="official" if market else "simulated",
            metadata=quote_metadata,
        ))

    handicap = market.handicap if market else fallback_handicap(home_xg, away_xg)
    handicap_outcomes = outcome_probabilities(matrix, handicap)
    if market:
        handicap_odds = market.handicap_win_draw_loss
    else:
        handicap_odds = _sample_odds_dict(
            {"胜": handicap_outcomes["home"], "平": handicap_outcomes["draw"], "负": handicap_outcomes["away"]}
        )
    handicap_market = normalized_market_probabilities(handicap_odds)
    handicap_model = {"胜": handicap_outcomes["home"], "平": handicap_outcomes["draw"], "负": handicap_outcomes["away"]}
    handicap_conflict = market_conflict_decision(handicap_model, handicap_market)
    for chinese, outcome in OUTCOME_KEYS.items():
        quotes.append(make_quote(
            match_id, label, "让球胜平负", f"{handicap:+d} {chinese}", handicap_odds.get(chinese), handicap_outcomes[outcome],
            handicap_market.get(chinese), coverage, bool(market and "让球胜平负" in market.single_markets), generated_at, handicap=handicap,
            market_conflict=handicap_conflict,
            odds_source="official" if market else "simulated",
            metadata=quote_metadata,
        ))

    # --- 比分 (31 standard sporttery.cn score options) ---
    # Real sporttery offers exactly these 31 selections for every match.
    # We always generate all of them so the personal-betting UI has the
    # full set — even when live odds are unavailable.
    SPORTTERY_HOME_SCORES = ["1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2", "5:0", "5:1", "5:2"]
    SPORTTERY_DRAW_SCORES = ["0:0", "1:1", "2:2", "3:3"]
    SPORTTERY_AWAY_SCORES = ["0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4", "0:5", "1:5", "2:5"]
    ALL_STANDARD_SCORES = SPORTTERY_HOME_SCORES + ["胜其它"] + SPORTTERY_DRAW_SCORES + ["平其它"] + SPORTTERY_AWAY_SCORES + ["负其它"]

    score_odds = market.scores if market else {}
    if score_odds:
        # Live market available: use real odds, but still generate ALL 31 scores
        pass
    else:
        # Degraded mode: generate simulated odds for every standard score
        for sel in ALL_STANDARD_SCORES:
            prob = score_selection_probability(sel, matrix, set())
            if prob > 0.0001:
                sampled = _sample_odds(prob)
                if sampled:
                    score_odds[sel] = sampled

    offered_scores = {sel for sel in score_odds if ":" in sel}
    score_market = normalized_market_probabilities(score_odds) if score_odds else {}
    score_selections = list(score_odds) if score_odds else ALL_STANDARD_SCORES[:8]
    score_model = {
        selection: score_selection_probability(selection, matrix, {sel for sel in score_odds if ":" in sel})
        for selection in score_selections
    }
    score_conflict = market_conflict_decision(score_model, score_market)
    for selection in score_selections:
        odds = score_odds.get(selection)
        probability = score_selection_probability(selection, matrix, offered_scores)
        quotes.append(make_quote(
            match_id, label, "比分", selection, odds, probability, score_market.get(selection),
            coverage, False, generated_at, stars=stars, excluded_scores=sorted(offered_scores),
            market_conflict=score_conflict,
            odds_source="official" if market else "simulated",
            metadata=quote_metadata,
        ))

    total_goal_model = total_goals_probabilities(matrix)
    if market:
        total_goal_odds = market.total_goals
    else:
        total_goal_odds = _sample_odds_dict(total_goal_model)
    total_goal_market = normalized_market_probabilities(total_goal_odds) if total_goal_odds else {}
    total_goal_conflict = market_conflict_decision(total_goal_model, total_goal_market)
    for selection, probability in total_goal_model.items():
        quotes.append(make_quote(
            match_id, label, "总进球数", selection, total_goal_odds.get(selection), probability,
            total_goal_market.get(selection), coverage, bool(market and "总进球数" in market.single_markets), generated_at,
            market_conflict=total_goal_conflict,
            odds_source="official" if market else "simulated",
            metadata=quote_metadata,
        ))

    half_full_model = simulated["halfFull"] if simulated else half_full_probabilities(home_xg, away_xg)
    if market:
        half_full_odds = market.half_full
    else:
        half_full_odds = _sample_odds_dict(half_full_model)
    half_full_market = normalized_market_probabilities(half_full_odds) if half_full_odds else {}
    half_full_conflict = market_conflict_decision(half_full_model, half_full_market)
    for selection, probability in half_full_model.items():
        half_full_coverage = max(0.0, coverage - 0.08)
        quotes.append(make_quote(
            match_id, label, "半全场", selection, half_full_odds.get(selection), probability,
            half_full_market.get(selection), half_full_coverage, bool(market and "半全场" in market.single_markets), generated_at,
            market_conflict=half_full_conflict,
            odds_source="official" if market else "simulated",
            metadata=quote_metadata,
        ))


    venue = VENUES.get(seed.get("venue"))
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
        "modelDecomposition": seed.get("model_decomposition", {
            "longTermExpectedGoals": {"home": round(home_xg, 4), "away": round(away_xg, 4)},
            "adjustedExpectedGoals": {"home": round(home_xg, 4), "away": round(away_xg, 4)},
        }),
        "tournamentForm": seed.get("tournament_form"),
        "currentTournament": seed.get("current_tournament"),
        "drawRisk": draw_risk_result.metadata,
        "outcomeProbabilities": {key: round(value, 5) for key, value in outcomes.items()},
        "outcomeDecision": {
            **outcome_decision,
            "maxProbability": round(float(outcome_decision["maxProbability"]), 5),
        },
        "likelyScore": likely_score,
        "likelyScoreSource": likely_score_source,
        "scoreStars": stars,
        "scoreProbabilities": scores,
        "coverage": coverage,
        "weather": seed.get("weather", "天气待更新"),
        "altitude": venue["altitude"] if venue else 0,
        "missingData": seed.get("missing_data", []),
        "factors": factors,
        "lineupImpact": seed.get("lineup_impact", []),
        "intelligence": seed.get("intelligence", []),
        "simulation": simulated["quality"] if simulated else None,
        "quotes": quotes,
    }


def _sporttery_fixture_seeds(
    all_markets: list[SportteryMatch],
    target_date: str,
) -> list[dict]:
    """Build match seeds from live sporttery.cn match data.

    When football-data.org is unavailable, sporttery already returns correct
    Chinese team names and kickoff times — this function extracts them into
    the seed format the rest of the pipeline expects.
    """
    # Try Elo for better xG, fall back to neutral
    try:
        elo_client = EloRatingsClient()
        elo_ratings = elo_client.ratings()
        elo_live = True
    except Exception:
        elo_ratings = {}
        elo_live = False
    model_policy = load_model_policy()
    elo_allocation_weight = float(model_policy["eloAllocationWeight"])

    seeds = []
    for m in all_markets:
        if m.match_date != target_date:
            continue
        # Only World Cup matches — sporttery also lists domestic leagues
        if m.league_name and m.league_name != "世界杯":
            continue
        if not m.home_team or not m.away_team:
            continue
        # Reconstruct ISO kickoff from match_date + kickoff_text
        time_part = m.kickoff_text.split()[-1] if m.kickoff_text else "12:00"
        kickoff = f"{m.match_date}T{time_part}:00+08:00"

        # Compute xG: goal model → Elo → neutral
        home_xg, away_xg, total_provider = _compute_xg_for_sporttery_seed(
            m.home_team,
            m.away_team,
            target_date,
            elo_ratings,
            elo_allocation_weight,
        )

        seeds.append({
            "home_team": m.home_team,
            "away_team": m.away_team,
            "home_flag": team_flag({"name": m.home_team}),
            "away_flag": team_flag({"name": m.away_team}),
            "kickoff": kickoff,
            "sporttery_id": m.match_id,
            "lottery_code": m.lottery_code,
            "venue": "待定",
            "base_xg": [home_xg, away_xg],
            "model_decomposition": {
                "totalGoalsProvider": total_provider,
                "strengthAllocator": "world_football_elo" if elo_live else "statistical_split",
                "allocationPolicy": "separated_total_and_strength_v1",
                "eloAllocationWeight": elo_allocation_weight if total_provider == "hierarchical_goal_model" else 0.0,
                "allocationValidationSet": model_policy.get("validationSet", "FIFA World Cup 2018 and 2022"),
                "estimatedTotalGoals": round(home_xg + away_xg, 4),
            },
            "coverage": 0.80,
            "weather": "天气待更新",
            "factors": _sporttery_factors(home_xg, away_xg, elo_live),
            "missing_data": ["赛程来自体彩API（football-data.org不可用）"],
            "elo_live": elo_live,
        })
    return seeds


def _sporttery_factors(home_xg: float, away_xg: float, elo_live: bool) -> list[dict]:
    """Build factor list for sporttery-sourced matches.

    Only the "球队实力" factor is active with core admission status;
    the rest stay as defaults (inactive observation-only) because we
    have no lineup/injury/coach/weather data from the sporttery API.
    """
    factors = default_factors()
    xg_diff = abs(home_xg - away_xg)
    if xg_diff > 1.5:
        strength_note = "进球模型显示双方进攻实力差距较大"
    elif xg_diff > 0.6:
        strength_note = "进球模型显示存在一定实力差距"
    else:
        strength_note = "进球模型显示双方实力接近"
    if elo_live:
        strength_note += "（Elo实时数据可获取）"
    factors[0] = {
        "label": "球队实力", "direction": "neutral", "value": 0.0,
        "note": strength_note, "active": True, "admissionStatus": "core",
    }
    return factors


def _compute_xg_for_sporttery_seed(
    home_cn: str,
    away_cn: str,
    target_date: str,
    elo_ratings: dict[str, int],
    elo_allocation_weight: float,
) -> tuple[float, float, str]:
    """Best-effort xG for a match whose teams come from sporttery (Chinese names)."""
    # 1) Hierarchical Poisson goal model (needs English names)
    home_en = _cn_to_en_team_name(home_cn)
    away_en = _cn_to_en_team_name(away_cn)
    if home_en and away_en:
        try:
            gm = goal_model_xg(home_en, away_en, target_date)
            if gm is not None:
                home_elo = elo_ratings.get(home_cn) or elo_ratings.get(team_key(home_cn))
                away_elo = elo_ratings.get(away_cn) or elo_ratings.get(team_key(away_cn))
                if home_elo and away_elo:
                    elo_home, elo_away = allocate_total_goals_by_elo(sum(gm), home_elo, away_elo)
                    return (
                        (1 - elo_allocation_weight) * gm[0] + elo_allocation_weight * elo_home,
                        (1 - elo_allocation_weight) * gm[1] + elo_allocation_weight * elo_away,
                        "hierarchical_goal_model",
                    )
                return gm[0], gm[1], "hierarchical_goal_model"
        except Exception:
            pass

    # 2) Elo ratings → Poisson xG
    home_elo = elo_ratings.get(home_cn) or elo_ratings.get(team_key(home_cn))
    away_elo = elo_ratings.get(away_cn) or elo_ratings.get(team_key(away_cn))
    if home_elo and away_elo:
        home_xg, away_xg = expected_goals_from_elo(home_elo, away_elo)
        return home_xg, away_xg, "elo_fallback"

    # 3) Neutral fallback
    return 1.35, 1.10, "neutral_fallback"


def _cn_to_en_team_name(cn_name: str) -> str | None:
    """Reverse-map Chinese team name to English for the goal model."""
    # Direct reverse of TEAM_NAMES_ZH
    reverse: dict[str, str] = {}
    for en, zh in TEAM_NAMES_ZH.items():
        reverse[zh] = en
    # Handle sporttery abbreviations
    aliases = {
        "刚果金": "Congo DR",
        "民主刚果": "Congo DR",
        "沙特": "Saudi Arabia",
    }
    return aliases.get(cn_name) or reverse.get(cn_name)


def _load_strategy_bankrolls(history_path: Path, initial_bankroll: int) -> dict[str, float] | None:
    """Read strategy-history.json and compute per-strategy rolling bankrolls.

    Mirrors the frontend ``strategyRollingBankrolls()`` logic so that the
    pipeline generates portfolios at the correct scale from the start.
    Returns None when no history file is available (first run).
    """
    if not history_path.exists():
        return None
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    keys = ("conservative", "balanced", "aggressive")
    bankrolls = {key: float(initial_bankroll) for key in keys}

    for day in sorted(history.get("days", []), key=lambda d: d["targetDate"]):
        for s in day.get("strategies", []):
            key = s["key"]
            if key not in bankrolls:
                continue
            if s.get("status") == "settled" and s.get("profit") is not None:
                bankrolls[key] = max(0.0, bankrolls[key] + float(s["profit"]))

    return bankrolls


def main() -> None:
    args = parse_args()
    timezone = ZoneInfo(SETTINGS.timezone)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    target_date = args.target_date or (now.astimezone(timezone).date() + timedelta(days=1)).isoformat()
    generated_at = now.astimezone(timezone).isoformat(timespec="seconds")
    degraded_reasons: list[str] = []
    sporttery_live = False
    football_data_live = False
    elo_live = False
    team_data_live = False

    if args.offline:
        markets_by_id = load_fixture(FIXTURE_DIR / "sporttery-spf.html", FIXTURE_DIR / "sporttery-score.html")
        degraded_reasons.append("使用仓库内固定体彩快照")
    else:
        try:
            markets_by_id = fetch_sporttery()
            sporttery_live = True
        except Exception as exc:  # noqa: BLE001 - degradation is deliberate and reported
            print(f"[sporttery] live fetch failed: {type(exc).__name__}: {exc}")
            markets_by_id = load_fixture(FIXTURE_DIR / "sporttery-spf.html", FIXTURE_DIR / "sporttery-score.html")
            degraded_reasons.append("体彩实时赔率暂时不可用，已切换到固定快照")
    all_markets = list(markets_by_id.values())
    if sporttery_live and not args.offline:
        try:
            save_odds_snapshot(all_markets, now)
        except OSError:
            degraded_reasons.append("赔率历史快照写入失败，当前预测仍可继续")

    football_client = FootballDataClient()
    client = ApiFootballClient()
    seeds: list[dict]
    all_football_matches: list[dict] | None = None
    if football_client.enabled and not args.offline:
        try:
            all_football_matches = football_client.world_cup_matches()
            seeds = football_data_seeds(football_client, target_date, all_football_matches)
            football_data_live = bool(seeds)
            elo_live = bool(seeds) and all(seed.get("elo_live", False) for seed in seeds)
            team_data_live = bool(seeds)
            if seeds:
                degraded_reasons.append("免费数据源不含可靠的预计首发、实时伤停和球员俱乐部高级数据")
            if seeds and not elo_live:
                degraded_reasons.append("国家队 Elo 基础实力暂时不可用，已回归中性基线")
        except Exception as exc:  # noqa: BLE001
            print(f"[football-data] live fetch failed: {type(exc).__name__}: {exc}")
            seeds = []
            degraded_reasons.append("football-data.org 世界杯赛程暂时不可用")
    else:
        seeds = []

    if not seeds and client.enabled and not args.offline:
        try:
            seeds = live_seeds(client, target_date)
            team_data_live = bool(seeds)
        except Exception as exc:  # noqa: BLE001
            print(f"[api-football] live fetch failed: {type(exc).__name__}: {exc}")
            seeds = []
            degraded_reasons.append("球队实时数据暂时不可用，已切换到固定开发样例")
    elif not seeds:
        degraded_reasons.append("球队与阵容实时数据尚未启用，当前使用固定开发样例")

    # --- Sporttery fixture fallback ---
    # When football-data.org / API-Football are unavailable but sporttery.cn is
    # live, use sporttery's own match list as the fixture source.  Team names,
    # kickoff times, and match IDs are all correct — no date-shifting of stale
    # demo data.
    if not seeds and sporttery_live and all_markets:
        sporttery_seeds = _sporttery_fixture_seeds(all_markets, target_date)
        if sporttery_seeds:
            seeds = sporttery_seeds
            degraded_reasons.append("赛程来自体彩API（football-data.org不可用），xG由Elo/进球模型估算")

    demo = load_demo()
    if not seeds and target_date == demo["target_date"]:
        seeds = demo["matches"]
    elif not seeds and demo.get("matches"):
        demo_date = datetime.strptime(demo["target_date"], "%Y-%m-%d").date()
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
        delta = (target - demo_date).days
        seeds = []
        for match in demo["matches"]:
            adapted = dict(match)
            kickoff = datetime.fromisoformat(match["kickoff"]) + timedelta(days=delta)
            adapted["kickoff"] = kickoff.isoformat()
            adapted.pop("sporttery_id", None)
            adapted.pop("lottery_code", None)
            adapted.pop("api_fixture_id", None)
            seeds.append(adapted)
        degraded_reasons.append("使用固定开发样例（日期已调整至目标日），赔率为模拟值")
    elif not seeds:
        degraded_reasons.append("目标日期没有可用比赛种子数据")

    availability_records = load_availability()
    factor_admissions = load_factor_admissions()
    two_round_profiles = load_two_round_profiles()

    def prepare_seeds(batch: list[dict], batch_date: str) -> None:
        apply_availability(batch, batch_date, availability_records)
        apply_intelligence(batch, load_daily_intelligence(batch_date, generated_at))
        apply_lineup_impacts(batch)
        apply_factor_admissions(batch, factor_admissions)
        apply_two_round_form(batch, batch_date, two_round_profiles)
        apply_current_tournament_context(batch, all_football_matches)

    prepare_seeds(seeds, target_date)

    future_parlay_seeds: list[dict] = []
    if not args.offline:
        target_day = datetime.fromisoformat(target_date).date()
        for offset in range(1, SETTINGS.parlay_lookahead_days + 1):
            future_date = (target_day + timedelta(days=offset)).isoformat()
            batch: list[dict] = []
            if football_client.enabled and all_football_matches is not None:
                try:
                    batch = football_data_seeds(football_client, future_date, all_football_matches)
                except Exception:  # noqa: BLE001 - future parlay pool is optional
                    batch = []
            if not batch and sporttery_live and all_markets:
                batch = _sporttery_fixture_seeds(all_markets, future_date)
            prepare_seeds(batch, future_date)
            future_parlay_seeds.extend(
                seed for seed in batch
                if match_seed_to_market(seed, all_markets) is not None
            )

    simulation_inputs = []
    simulation_seeds = seeds + future_parlay_seeds
    for seed in simulation_seeds:
        market = match_seed_to_market(seed, all_markets)
        if market is not None:
            apply_market_strength_calibration(seed, market.win_draw_loss)
        match_id = market.match_id if market else seed.get("sporttery_id") or f"{seed['home_team']} vs {seed['away_team']}"
        factors = seed.get("factors", default_factors())
        home_xg, away_xg = adjust_xg(float(seed["base_xg"][0]), float(seed["base_xg"][1]), factors)
        simulation_inputs.append(MatchSimulationInput(
            match_id=match_id,
            home_team=seed["home_team"],
            away_team=seed["away_team"],
            home_xg=home_xg,
            away_xg=away_xg,
            stage=seed.get("stage", "single"),
            group=seed.get("group"),
            stage_complete=bool(seed.get("stage_complete", False)),
            parameter_samples=tuple(tuple(sample) for sample in seed.get("parameter_samples", [])),
            home_late_attack_multiplier=float(
                (seed.get("current_tournament") or {}).get("homeLatePressure", {}).get("attackMultiplier", 1.0)
            ),
            away_late_attack_multiplier=float(
                (seed.get("current_tournament") or {}).get("awayLatePressure", {}).get("attackMultiplier", 1.0)
            ),
            home_late_defensive_risk_multiplier=float(
                (seed.get("current_tournament") or {}).get("homeLatePressure", {}).get("defensiveRiskMultiplier", 1.0)
            ),
            away_late_defensive_risk_multiplier=float(
                (seed.get("current_tournament") or {}).get("awayLatePressure", {}).get("defensiveRiskMultiplier", 1.0)
            ),
        ))
    simulation = simulate_tournament(
        simulation_inputs,
        paths=SETTINGS.simulations,
        seed=SETTINGS.random_seed,
    ) if simulation_inputs else None

    built_matches = []
    for seed in seeds:
        market = match_seed_to_market(seed, all_markets)
        if market is None:
            degraded_reasons.append(f"{seed['home_team']} vs {seed['away_team']} 未匹配到体彩赔率")
        built_matches.append(build_match(seed, market, generated_at, simulation))

    future_parlay_matches = [
        build_match(seed, match_seed_to_market(seed, all_markets), generated_at, simulation)
        for seed in future_parlay_seeds
    ]
    published_parlay_matches, cached_parlay_count = preserve_parlay_matches(
        future_parlay_matches,
        args.output.parent / "parlay-cache.json",
        target_date,
        generated_at,
    )
    all_quotes = [quote for match in built_matches for quote in match["quotes"]]
    parlay_quotes = all_quotes + [
        quote for match in future_parlay_matches for quote in match["quotes"]
    ]

    # Compute per-strategy rolling bankrolls from settled history.
    # When a strategy is underwater (bankroll < initial), drawdown protection
    # shrinks stakes and raises edge thresholds inside build_portfolios().
    strategy_bankrolls = _load_strategy_bankrolls(OUTPUT_DIR / "strategy-history.json", SETTINGS.initial_bankroll)

    portfolios = build_portfolios(all_quotes, SETTINGS.initial_bankroll, simulation=simulation, parlay_quotes=parlay_quotes, strategy_bankrolls=strategy_bankrolls)
    coverage = sum(match["coverage"] for match in built_matches) / len(built_matches) if built_matches else 0
    weather_live = team_data_live and bool(built_matches) and all(
        any(factor["label"] == "温湿度与风" and factor["active"] for factor in match["factors"])
        for match in built_matches
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "targetDate": target_date,
        "timezone": SETTINGS.timezone,
        "modelVersion": get_model_version(),
        "pipelineVersion": PIPELINE_VERSION,
        "dataSnapshot": build_snapshot_manifest(local_snapshot_paths(), generated_at),
        "reproducibility": {
            "baselineFrozen": True,
            "randomSeed": SETTINGS.random_seed,
        },
        "simulations": simulation.paths if simulation else 0,
        "simulationQuality": {
            "actualPaths": simulation.paths if simulation else 0,
            "seed": simulation.seed if simulation else SETTINGS.random_seed,
            "parameterUncertainty": simulation.parameter_uncertainty if simulation else "unavailable",
            "groupRankProbabilities": simulation.group_rank_probabilities if simulation else {},
        },
        "bankroll": SETTINGS.initial_bankroll,
        "oddsFreshMinutes": 0,
        "overallCoverage": round(coverage, 4),
        "status": "degraded" if degraded_reasons else "ready",
        "statusMessage": "；".join(degraded_reasons) if degraded_reasons else "实时数据管线正常",
        "matches": built_matches,
        "portfolios": portfolios,
        "parlayLookaheadDays": SETTINGS.parlay_lookahead_days,
        "parlayMatches": published_parlay_matches,
        "cachedParlayMatchCount": cached_parlay_count,
        "parlayCandidateMatches": [
            {
                "id": match["id"],
                "lotteryCode": match["lotteryCode"],
                "kickoffBeijing": match["kickoffBeijing"],
                "homeTeam": match["homeTeam"],
                "awayTeam": match["awayTeam"],
                "coverage": match["coverage"],
            }
            for match in published_parlay_matches
        ],
        "evidence": [
            {"source": "中国体育彩票", "field": "固定奖金/单关资格", "observedAt": generated_at, "confidence": 1.0, "status": "fresh" if sporttery_live else "manual"},
            {"source": "football-data.org 免费档", "field": "2026 世界杯赛程/赛果", "observedAt": generated_at, "confidence": 0.9, "status": "fresh" if football_data_live else "missing"},
            {"source": "World Football Elo Ratings", "field": "国家队基础实力", "observedAt": generated_at, "confidence": 0.72, "status": "fresh" if elo_live else "missing"},
            {"source": "API-Football 免费档", "field": "预计首发/伤停/球员数据", "observedAt": generated_at, "confidence": 0.0, "status": "missing"},
            {"source": "Open-Meteo", "field": "开球时刻天气", "observedAt": generated_at, "confidence": 0.8, "status": "fresh" if weather_live else "manual"},
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
        history_dates = []
        for history_path in sorted(archive.parent.glob("*.json")):
            try:
                historical_payload = json.loads(history_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if historical_payload.get("matches"):
                history_dates.append(historical_payload.get("targetDate", history_path.stem))
        history_index = {
            "generatedAt": generated_at,
            "dates": sorted(set(history_dates)),
        }
        (args.output.parent / "history-index.json").write_text(
            json.dumps(history_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"Wrote {args.output} with {len(built_matches)} matches; status={payload['status']}")

    # Auto-switch production model if total-goals adoption gates pass
    if check_and_apply_adoption():
        active = get_model_version()
        print(f"[model] production model is now: {active}")


if __name__ == "__main__":
    main()
