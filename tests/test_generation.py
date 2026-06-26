import json
import subprocess
import sys

from pipeline import generate


def test_parlay_cache_keeps_future_matches_when_refresh_is_empty(tmp_path):
    cached_match = {
        "id": "future-1",
        "kickoffBeijing": "2026-06-20T03:00:00+08:00",
        "quotes": [{"odds": 1.88}],
    }
    expired_match = {
        "id": "today-1",
        "kickoffBeijing": "2026-06-19T03:00:00+08:00",
        "quotes": [{"odds": 2.1}],
    }
    cache_path = tmp_path / "parlay-cache.json"
    cache_path.write_text(
        json.dumps({"generatedAt": "old", "matches": [cached_match, expired_match]}),
        encoding="utf-8",
    )

    matches, fallback_count = generate.preserve_parlay_matches(
        [],
        cache_path,
        "2026-06-19",
        "2026-06-18T18:00:00+08:00",
    )

    assert matches == [cached_match]
    assert fallback_count == 1


def test_fresh_parlay_match_replaces_cached_version(tmp_path):
    cache_path = tmp_path / "parlay-cache.json"
    cache_path.write_text(json.dumps({
        "generatedAt": "old",
        "matches": [{
            "id": "future-1",
            "kickoffBeijing": "2026-06-20T03:00:00+08:00",
            "quotes": [{"odds": 1.88}],
        }],
    }), encoding="utf-8")
    fresh_match = {
        "id": "future-1",
        "kickoffBeijing": "2026-06-20T03:00:00+08:00",
        "quotes": [{"odds": 1.95}],
    }

    matches, fallback_count = generate.preserve_parlay_matches(
        [fresh_match],
        cache_path,
        "2026-06-19",
        "2026-06-18T18:00:00+08:00",
    )

    assert matches == [fresh_match]
    assert fallback_count == 0


def test_offline_generation(tmp_path):
    output = tmp_path / "forecast.json"
    subprocess.run([
        sys.executable, "-m", "pipeline.generate", "--offline",
        "--target-date", "2026-06-15", "--now", "2026-06-14T18:00:00+08:00",
        "--output", str(output),
    ], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["targetDate"] == "2026-06-15"
    assert payload["modelVersion"].startswith("hierarchical_poisson[")
    assert payload["reproducibility"] == {"baselineFrozen": True, "randomSeed": 20260615}
    assert payload["simulationQuality"]["actualPaths"] == 100000
    assert payload["simulationQuality"]["seed"] == 20260615
    assert all(match["simulation"]["actualPaths"] == 100000 for match in payload["matches"])
    assert len(payload["dataSnapshot"]["id"]) == 64
    assert payload["dataSnapshot"]["files"]
    assert len(payload["matches"]) == 4
    assert all(abs(sum(match["outcomeProbabilities"].values()) - 1) < 0.0001 for match in payload["matches"])
    assert all(portfolio["stake"] <= 200 for portfolio in payload["portfolios"])
    assert all(item["status"] != "fresh" for item in payload["evidence"])


def test_live_fetch_error_is_not_exposed(monkeypatch, tmp_path):
    output = tmp_path / "forecast.json"

    def fail_with_internal_detail():
        raise RuntimeError("567 Server Error for url: https://internal.example/path")

    monkeypatch.setattr(generate, "fetch_sporttery", fail_with_internal_detail)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "pipeline.generate",
        "--target-date", "2026-06-15",
        "--now", "2026-06-14T18:00:00+08:00",
        "--output", str(output),
    ])

    generate.main()
    payload = json.loads(output.read_text(encoding="utf-8"))
    message = payload["statusMessage"]

    assert "体彩实时赔率暂时不可用" in message
    assert "http" not in message
    assert "567" not in message
    assert "Server Error" not in message
    assert next(item for item in payload["evidence"] if item["source"] == "Open-Meteo")["status"] == "manual"


def test_spain_cape_verde_uses_elo_gap_instead_of_neutral_fallback(monkeypatch):
    class Client:
        def world_cup_matches(self):
            return [{
                "id": 1,
                "utcDate": "2026-06-15T16:00:00Z",
                "status": "TIMED",
                "homeTeam": {"id": 10, "name": "Spain", "tla": "ESP"},
                "awayTeam": {"id": 20, "name": "Cape Verde Islands", "tla": "CPV"},
                "venue": "Demo Stadium",
            }]

        def matches_on_beijing_date(self, target_date, matches):
            return matches

    monkeypatch.setattr(generate.EloRatingsClient, "ratings", lambda _self: {"西班牙": 2157, "佛得角": 1578})
    monkeypatch.setattr(generate.OpenMeteoClient, "forecast_at", lambda *_args: {"status": "missing"})

    seed = generate.football_data_seeds(Client(), "2026-06-16")[0]

    # Goal model (when CSV present) or Elo fallback — both should give plausible xG
    assert seed["base_xg"][0] > 0.5
    assert seed["base_xg"][1] > 0.0
    # Strong favourite should have edge
    assert seed["base_xg"][0] > seed["base_xg"][1]
    assert seed["coverage"] == 0.8
    assert len(seed["missing_data"]) == 1
    assert seed["factors"][0]["admissionStatus"] == "core"


def test_sporttery_seed_uses_model_policy_for_strength_allocation(monkeypatch):
    monkeypatch.setattr(generate, "goal_model_xg", lambda *_args: (1.4, 1.0))
    monkeypatch.setattr(generate, "_cn_to_en_team_name", lambda name: name)

    home, away, provider = generate._compute_xg_for_sporttery_seed(
        "Home",
        "Away",
        "2026-06-19",
        {"Home": 1800, "Away": 1400},
        0.0,
    )
    elo_home, elo_away, _ = generate._compute_xg_for_sporttery_seed(
        "Home",
        "Away",
        "2026-06-19",
        {"Home": 1800, "Away": 1400},
        1.0,
    )

    assert provider == "hierarchical_goal_model"
    assert (home, away) == (1.4, 1.0)
    assert elo_home + elo_away == home + away
    assert elo_home > home
    assert elo_away < away


def test_outcome_recommendation_requires_sixty_percent_confidence():
    watch = generate.outcome_recommendation_decision({"home": 0.59, "draw": 0.26, "away": 0.15})
    recommended = generate.outcome_recommendation_decision({"home": 0.60, "draw": 0.25, "away": 0.15})

    assert watch == {"threshold": 0.60, "maxProbability": 0.59, "selection": "home", "status": "watch"}
    assert recommended["status"] == "recommended"


def test_mutual_draw_guard_moves_near_tie_selection_to_draw_watch():
    decision = generate.outcome_recommendation_decision({"home": 0.345, "draw": 0.315, "away": 0.340})

    guarded = generate.apply_mutual_draw_outcome_guard(
        decision,
        {"home": 0.345, "draw": 0.315, "away": 0.340},
        {"current_tournament": {"mutualDrawUtility": True}},
    )

    assert guarded["selection"] == "draw"
    assert guarded["status"] == "watch"
    assert guarded["guard"] == "third_round_mutual_draw_utility"


def test_mutual_draw_guard_downgrades_clear_favorite_recommendation():
    decision = generate.outcome_recommendation_decision({"home": 0.66, "draw": 0.22, "away": 0.12})

    guarded = generate.apply_mutual_draw_outcome_guard(
        decision,
        {"home": 0.66, "draw": 0.22, "away": 0.12},
        {"current_tournament": {"mutualDrawUtility": True}},
    )

    assert guarded["selection"] == "home"
    assert guarded["status"] == "watch"
    assert guarded["guard"] == "third_round_mutual_draw_utility"


def test_third_round_open_game_likely_score_can_align_with_outcome():
    scores = [
        {"score": "1:1", "probability": 0.10},
        {"score": "2:1", "probability": 0.08},
        {"score": "1:0", "probability": 0.07},
    ]
    seed = {
        "current_tournament": {
            "policy": "matchday_three_scenarios_annex_c_v3_open_game",
            "homeMotivation": "secured_top_two",
            "awayMotivation": "secured_top_two",
            "homeScenarios": {"firstPlacePathIncentive": True, "thirdScenarioShare": 0.0},
            "awayScenarios": {"firstPlacePathIncentive": True, "thirdScenarioShare": 0.0},
        }
    }

    score, source = generate.select_likely_score(
        scores,
        {"selection": "home", "status": "watch"},
        seed,
    )

    assert score == "2-1"
    assert source == "third_round_outcome_aligned_score"


def test_regular_likely_score_keeps_top_score_probability():
    scores = [
        {"score": "1:1", "probability": 0.10},
        {"score": "2:1", "probability": 0.08},
    ]

    score, source = generate.select_likely_score(
        scores,
        {"selection": "home", "status": "watch"},
        {"current_tournament": {"policy": "not_third_round"}},
    )

    assert score == "1-1"
    assert source == "top_score_probability"


def test_mutual_draw_utility_keeps_draw_likely_score():
    scores = [
        {"score": "2:1", "probability": 0.10},
        {"score": "1:1", "probability": 0.07},
    ]
    seed = {
        "current_tournament": {
            "policy": "matchday_three_scenarios_annex_c_v4_draw_utility",
            "homeMotivation": "draw_advances",
            "awayMotivation": "draw_advances",
            "mutualDrawUtility": True,
            "homeScenarios": {"firstPlacePathIncentive": True, "thirdScenarioShare": 0.33},
            "awayScenarios": {"firstPlacePathIncentive": True, "thirdScenarioShare": 0.60},
        }
    }

    score, source = generate.select_likely_score(
        scores,
        {"selection": "home", "status": "watch"},
        seed,
    )

    assert score == "1-1"
    assert source == "third_round_mutual_draw_score"


def test_simulated_handicap_gives_goals_to_the_weaker_home_team():
    assert generate.fallback_handicap(2.1, 1.0) == -1
    assert generate.fallback_handicap(0.6, 2.4) == 2


def test_low_confidence_outcome_quote_is_downgraded_to_watch():
    quote = generate.make_quote(
        "m1", "A vs B", "胜平负", "胜", 3.0, 0.40, 0.34, 0.90, True,
        "2026-06-15T12:00:00+08:00",
        recommendation_gate=(False, "胜平负最高概率 59.0% 低于 60% 门槛"),
    )

    assert quote["recommendation"] == "观察"
    assert quote["reason"] == "胜平负最高概率 59.0% 低于 60% 门槛"
    assert quote["formalEligible"] is False


def test_positive_official_quote_requires_clear_market_guard_for_formal_pool():
    clear = {
        "status": "clear", "blocked": False, "maxGap": 0.04,
        "modelFavorite": "胜", "marketFavorite": "胜", "reason": "未触发冲突",
    }
    quote = generate.make_quote(
        "m1", "A vs B", "胜平负", "胜", 2.0, 0.62, 0.58, 0.90, True,
        "2026-06-15T12:00:00+08:00",
        recommendation_gate=(True, ""),
        market_conflict=clear,
        odds_source="official",
    )
    assert quote["robustExpectedReturn"] > 0
    assert quote["formalEligible"] is True


def test_market_conflict_blocks_positive_edge_quote():
    conflict = {
        "status": "conflict", "blocked": True, "maxGap": 0.25,
        "modelFavorite": "胜", "marketFavorite": "负", "reason": "模型与市场最大概率差 25.0% 超过 15%",
    }
    quote = generate.make_quote(
        "m1", "A vs B", "让球胜平负", "-1 胜", 3.0, 0.50, 0.25, 0.90, True,
        "2026-06-15T12:00:00+08:00",
        market_conflict=conflict,
        odds_source="official",
    )
    assert quote["rawExpectedReturn"] > 0
    assert quote["recommendation"] == "观察"
    assert quote["formalEligible"] is False
