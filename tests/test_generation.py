import json
import subprocess
import sys

from pipeline import generate


def test_offline_generation(tmp_path):
    output = tmp_path / "forecast.json"
    subprocess.run([
        sys.executable, "-m", "pipeline.generate", "--offline",
        "--target-date", "2026-06-15", "--now", "2026-06-14T18:00:00+08:00",
        "--output", str(output),
    ], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["targetDate"] == "2026-06-15"
    assert payload["modelVersion"] == "legacy-dixon-coles-v1"
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

    assert seed["base_xg"][0] >= 2.3
    assert seed["base_xg"][1] <= 0.25
    assert seed["coverage"] == 0.8
    assert len(seed["missing_data"]) == 1
    assert seed["factors"][0]["admissionStatus"] == "core"


def test_outcome_recommendation_requires_sixty_percent_confidence():
    watch = generate.outcome_recommendation_decision({"home": 0.59, "draw": 0.26, "away": 0.15})
    recommended = generate.outcome_recommendation_decision({"home": 0.60, "draw": 0.25, "away": 0.15})

    assert watch == {"threshold": 0.60, "maxProbability": 0.59, "selection": "home", "status": "watch"}
    assert recommended["status"] == "recommended"


def test_low_confidence_outcome_quote_is_downgraded_to_watch():
    quote = generate.make_quote(
        "m1", "A vs B", "胜平负", "胜", 3.0, 0.40, 0.34, 0.90, True,
        "2026-06-15T12:00:00+08:00",
        recommendation_gate=(False, "胜平负最高概率 59.0% 低于 60% 门槛"),
    )

    assert quote["recommendation"] == "观察"
    assert quote["reason"] == "胜平负最高概率 59.0% 低于 60% 门槛"
