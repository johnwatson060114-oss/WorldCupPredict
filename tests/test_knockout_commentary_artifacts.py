import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_current_knockout_corpus_archives_every_completed_match_and_extra_time_process():
    payload = load_json("public/data/knockout-match-timelines.json")
    matches = payload["matches"]

    assert len(matches) == 28
    assert all(match["source"]["commentaryLinesRead"] >= 80 for match in matches)
    assert all(match["processSummary"]["narrative"] for match in matches)
    assert all(match["source"]["url"].startswith("https://www.espn.com/soccer/commentary/") for match in matches)

    extra_time_matches = [match for match in matches if match["score"]["wentToExtraTime"]]
    assert len(extra_time_matches) >= 6
    for match in extra_time_matches:
        for team in (match["homeTeam"], match["awayTeam"]):
            process = match["processSummary"]["teamProcess"][team]
            assert process["post90LoadSeverity"] > 0
            assert process["extraTimeProcess"]["proxyOnly"]


def test_historical_stage_policy_is_commentary_trained_and_safety_gated():
    corpus = load_json("public/data/final-four-commentary-corpus.json")
    policy = load_json("pipeline/data/final-four-policy.json")
    evidence = load_json("pipeline/data/knockout-commentary-evidence.json")

    assert len(corpus["matches"]) == 22
    assert len({match["tournament"] for match in corpus["matches"]}) == 6
    assert policy["stageProfiles"]["SEMI_FINAL"]["trainingMatches"] == 12
    assert policy["stageProfiles"]["FINAL"]["trainingMatches"] == 6
    assert policy["stageProfiles"]["THIRD_PLACE"]["trainingMatches"] == 4
    assert policy["stageProfiles"]["FINAL"]["activeMatrixBlend"] == 0.0
    assert evidence["validation"]["protocol"] == "walk_forward_next_round_only"
    assert evidence["validation"]["safetyGatePassed"]
    assert evidence["scoreResidualsDirectlyAdjustStrength"] is False
