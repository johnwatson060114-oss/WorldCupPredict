from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ROOT


DEFAULT_POLICY_PATH = ROOT / "pipeline" / "data" / "final-sprint-policy.json"

DEFAULT_POLICY: dict[str, Any] = {
    "policy": "world_cup_final_sprint_v1",
    "validationWeight": {"worldCup2026": 0.70, "worldCup2018And2022": 0.30},
    "historicalDegradationLimit": 0.02,
    "tournamentEvidence": {
        "halfLifeMatches": 2.0,
        "shrinkage": 5.0,
        "maxSideXgShift": 0.15,
    },
    "marketAnchor": {
        "strengthBlend": 0.35,
        "totalGoalsBlend": 0.25,
        "maxSideXgShift": 0.20,
        "maxTotalXgShift": 0.25,
    },
    "scoreCalibration": {
        "candidateIntensities": [0.0, 0.10, 0.15, 0.20, 0.25],
        "selectedIntensity": 0.0,
        "selectionReason": "validation_gate_fallback",
        "totalGoalsLossWeight": 0.60,
        "exactScoreLossWeight": 0.40,
    },
}


def load_final_sprint_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_POLICY))
    payload = json.loads(path.read_text(encoding="utf-8"))
    merged = json.loads(json.dumps(DEFAULT_POLICY))
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged
