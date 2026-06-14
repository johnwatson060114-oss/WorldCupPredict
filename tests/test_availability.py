from pipeline.availability import apply_availability


def test_availability_record_lowers_coverage_without_inventing_xg_adjustment():
    seeds = [{
        "home_team": "巴西",
        "away_team": "海地",
        "coverage": 0.72,
        "factors": [{"label": "预计首发", "note": "未知", "active": False}],
        "missing_data": [],
    }]
    records = [{
        "team": "巴西",
        "player": "Neymar",
        "target_date": "2026-06-20",
        "status": "injured",
        "availability_probability": 0.05,
        "confidence": 0.75,
        "source_url": "https://example.com/report",
        "observed_at": "2026-06-15T05:30:00+08:00",
        "note": "reported injury",
    }]

    apply_availability(seeds, "2026-06-20", records)

    assert seeds[0]["coverage"] == 0.705
    assert seeds[0]["factors"][0]["active"] is False
    assert "Neymar" in seeds[0]["factors"][0]["note"]
    assert seeds[0]["availability"][0]["availability_probability"] == 0.05


def test_availability_only_applies_to_matching_date_and_team():
    seeds = [{"home_team": "巴西", "away_team": "海地", "coverage": 0.72, "factors": [], "missing_data": []}]
    records = [{
        "team": "巴西", "player": "Neymar", "target_date": "2026-06-25",
        "status": "doubtful", "availability_probability": 0.3, "confidence": 0.5,
        "source_url": "https://example.com", "observed_at": "2026-06-15T05:30:00+08:00", "note": "",
    }]

    apply_availability(seeds, "2026-06-20", records)

    assert seeds[0]["coverage"] == 0.72
    assert "availability" not in seeds[0]


def test_multiple_suspensions_accumulate_confidence_penalty():
    seeds = [{
        "home_team": "捷克",
        "away_team": "南非",
        "coverage": 0.74,
        "factors": [{"label": "预计首发", "note": "未知", "active": False}],
        "missing_data": [],
    }]
    records = [
        {
            "team": "南非", "player": player, "target_date": "2026-06-19",
            "status": "suspended", "availability_probability": 0.0, "confidence": 0.95,
            "source_url": "https://example.com", "observed_at": "2026-06-15T06:00:00+08:00", "note": "",
        }
        for player in ("Sphephelo Sithole", "Themba Zwane")
    ]

    apply_availability(seeds, "2026-06-19", records)

    assert seeds[0]["coverage"] == 0.702
    assert "Sphephelo Sithole" in seeds[0]["factors"][0]["note"]
    assert "Themba Zwane" in seeds[0]["factors"][0]["note"]
