import math
import random
from datetime import UTC, datetime, timedelta

from pipeline.backtest import blend_probabilities, learn_blend_alpha, learn_elo_allocation_weight, rolling_backtest, score_predictions


def poisson(randomizer: random.Random, mean: float) -> int:
    threshold = math.exp(-mean)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= randomizer.random()
    return count - 1


def synthetic_matches(count: int = 80) -> list[dict]:
    randomizer = random.Random(20260615)
    teams = ["A", "B", "C", "D"]
    attack = {"A": 1.7, "B": 1.35, "C": 0.85, "D": 0.55}
    start = datetime(2020, 1, 1, tzinfo=UTC)
    matches = []
    for index in range(count):
        home = teams[index % 4]
        away = teams[(index * 3 + 1) % 4]
        if home == away:
            away = teams[(teams.index(away) + 1) % 4]
        home_mean = 1.15 * attack[home] / attack[away] ** 0.35
        away_mean = 1.00 * attack[away] / attack[home] ** 0.35
        matches.append({
            "match_id": f"m{index}",
            "kickoff_utc": (start + timedelta(days=index * 12)).isoformat(),
            "home_team_id": home,
            "away_team_id": away,
            "home_goals_90": poisson(randomizer, home_mean),
            "away_goals_90": poisson(randomizer, away_mean),
            "neutral": True,
            "odds": {},
        })
    return matches


def test_probability_metrics_are_zero_for_perfect_predictions():
    metrics = score_predictions([({"home": 1.0, "draw": 0.0, "away": 0.0}, "home")])

    assert metrics["log_loss"] == 0
    assert metrics["rps"] == 0
    assert metrics["brier"] == 0


def test_nested_rolling_backtest_selects_only_on_past_data():
    report = rolling_backtest(synthetic_matches())

    assert report["test_matches"] > 0
    assert report["selected_model"] in {*report["candidates"], "legacy"}
    assert all(fold["train_end"] < fold["validation_end"] < fold["test_end"] for fold in report["folds"])
    assert all(result["log_loss"] < math.inf for result in report["candidates"].values())


def test_stronger_team_model_beats_global_legacy_baseline_on_synthetic_data():
    report = rolling_backtest(synthetic_matches(96))

    assert report["promote"] is True
    assert report["selected_model"] != "legacy"
    assert report["candidates"][report["selected_model"]]["log_loss"] < report["baseline"]["log_loss"]


def test_market_blend_weight_is_learned_from_validation_records():
    records = [
        {
            "statistical": {"home": 0.7, "draw": 0.2, "away": 0.1},
            "market": {"home": 0.2, "draw": 0.3, "away": 0.5},
            "actual": "home",
        }
        for _ in range(8)
    ]
    alpha = learn_blend_alpha(records)
    blended = blend_probabilities(records[0]["statistical"], records[0]["market"], alpha)

    assert alpha == 1.0
    assert math.isclose(sum(blended.values()), 1.0)


def test_elo_allocation_weight_excludes_2026_from_selection():
    matches = synthetic_matches(130)
    for index, match in enumerate(matches):
        year = 2017 + index // 40
        match["kickoff_utc"] = f"{year}-06-{index % 28 + 1:02d}T12:00:00+00:00"
        match["tournament"] = "FIFA World Cup" if year in {2018, 2019} else "Friendly"
    matches[-1]["kickoff_utc"] = "2026-06-20T12:00:00+00:00"
    report = learn_elo_allocation_weight(
        matches,
        validation_years={"2018", "2019"},
        candidates=(0.0, 1.0),
        min_history=20,
    )
    assert report["validationYears"] == ["2018", "2019"]
    assert report["validationTournament"] == "FIFA World Cup"
    assert report["excludedYears"] == ["2026"]
    assert report["validationMatches"] > 0
