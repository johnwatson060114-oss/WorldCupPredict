from pipeline.factor_gate import apply_factor_admissions, evaluate_factor
from pipeline.model import adjust_xg


def records(candidate_home: float, windows: int = 4) -> list[dict]:
    result = []
    for window in range(windows):
        for index in range(12):
            actual = "home" if index < 8 else "draw" if index < 10 else "away"
            candidate = {
                "home": candidate_home,
                "draw": (1 - candidate_home) * 0.6,
                "away": (1 - candidate_home) * 0.4,
            }
            result.append({
                "window": f"w{window}",
                "block": f"w{window}-b{index // 3}",
                "actual": actual,
                "baseline": {"home": 0.45, "draw": 0.30, "away": 0.25},
                "candidate": candidate,
            })
    return result


def test_factor_is_enabled_only_after_multi_window_stable_improvement():
    admission = evaluate_factor("weather", records(0.62), bootstrap_samples=100)

    assert admission.enabled is True
    assert admission.status == "enabled"
    assert admission.stable_windows == admission.total_windows == 4
    assert admission.bootstrap_improvement_share >= 0.8


def test_insufficient_windows_remain_observation_only():
    admission = evaluate_factor("referee", records(0.62, windows=2), bootstrap_samples=20)

    assert admission.enabled is False
    assert admission.status == "observation_only"
    assert "insufficient" in admission.reason


def test_unapproved_active_factor_cannot_change_mean_xg():
    seeds = [{
        "factors": [{"label": "天气", "active": True, "direction": "home", "value": 0.4, "note": "hot"}],
    }]
    apply_factor_admissions(seeds, {})
    home, away = adjust_xg(1.5, 1.0, seeds[0]["factors"])

    assert (home, away) == (1.5, 1.0)
    assert seeds[0]["factors"][0]["uncertaintyOnly"] is True


def test_approved_factor_changes_mean_and_keeps_audit_reason():
    seeds = [{
        "factors": [{"label": "天气", "active": True, "direction": "home", "value": 0.2, "note": "hot"}],
    }]
    apply_factor_admissions(seeds, {"天气": {"status": "enabled", "enabled": True, "reason": "four-window test"}})
    home, away = adjust_xg(1.5, 1.0, seeds[0]["factors"])

    assert (home, away) == (1.7, 0.95)
    assert seeds[0]["factors"][0]["admissionReason"] == "four-window test"


def test_core_team_strength_is_not_disabled_by_candidate_factor_gate():
    seeds = [{
        "factors": [{
            "label": "球队实力", "active": True, "direction": "neutral", "value": 0.0,
            "admissionStatus": "core", "note": "Elo",
        }],
    }]

    apply_factor_admissions(seeds, {})

    assert seeds[0]["factors"][0]["active"] is True
    assert seeds[0]["factors"][0]["uncertaintyOnly"] is False
