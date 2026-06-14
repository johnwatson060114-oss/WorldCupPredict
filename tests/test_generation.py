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
    assert len(payload["matches"]) == 4
    assert all(abs(sum(match["outcomeProbabilities"].values()) - 1) < 0.0001 for match in payload["matches"])
    assert all(portfolio["stake"] <= 200 for portfolio in payload["portfolios"])


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
    message = json.loads(output.read_text(encoding="utf-8"))["statusMessage"]

    assert "体彩实时赔率暂时不可用" in message
    assert "http" not in message
    assert "567" not in message
    assert "Server Error" not in message
