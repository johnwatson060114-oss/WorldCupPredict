from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ROOT


MODEL_POLICY_PATH = ROOT / "pipeline" / "data" / "model-policy.json"


def load_model_policy(path: Path = MODEL_POLICY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "eloAllocationWeight": 1.0,
            "status": "fallback",
            "validationSet": "unavailable",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "eloAllocationWeight": 1.0,
            "status": "fallback",
            "validationSet": "unavailable",
        }
    weight = max(0.0, min(1.0, float(payload.get("eloAllocationWeight", 1.0))))
    return {**payload, "eloAllocationWeight": weight}
