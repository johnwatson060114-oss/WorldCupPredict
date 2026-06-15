import json
import math
from pathlib import Path

from pipeline.config import LEGACY_MODEL_VERSION
from pipeline.model import outcome_probabilities, score_matrix, top_scores
from pipeline.provenance import build_snapshot_manifest


def test_legacy_model_matches_frozen_baseline():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "model-baseline-v1.json").read_text(encoding="utf-8")
    )
    matrix = score_matrix(fixture["home_xg"], fixture["away_xg"])

    assert fixture["model_version"] == LEGACY_MODEL_VERSION
    for key, expected in fixture["outcomes"].items():
        assert math.isclose(outcome_probabilities(matrix)[key], expected, abs_tol=1e-12)
    for actual, expected in zip(top_scores(matrix, 3), fixture["top_scores"], strict=True):
        assert actual["score"] == expected["score"]
        assert math.isclose(actual["probability"], expected["probability"], abs_tol=1e-12)


def test_snapshot_manifest_is_stable_and_content_addressed(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('{"value": 1}', encoding="utf-8")
    first = build_snapshot_manifest([source], "2026-06-14T18:00:00+08:00")
    second = build_snapshot_manifest([source], "2026-06-14T18:00:00+08:00")

    assert first == second
    source.write_text('{"value": 2}', encoding="utf-8")
    assert build_snapshot_manifest([source], first["cutoff"])["id"] != first["id"]
