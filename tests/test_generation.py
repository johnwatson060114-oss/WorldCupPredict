import json
import subprocess
import sys


def test_offline_generation(tmp_path):
    output = tmp_path / "forecast.json"
    subprocess.run([
        sys.executable, "-m", "pipeline.generate", "--offline",
        "--target-date", "2026-06-15", "--now", "2026-06-14T18:00:00+08:00",
        "--output", str(output),
    ], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["targetDate"] == "2026-06-15"
    assert len(payload["matches"]) == 4
    assert all(abs(sum(match["outcomeProbabilities"].values()) - 1) < 0.0001 for match in payload["matches"])
    assert all(portfolio["stake"] <= 200 for portfolio in payload["portfolios"])
