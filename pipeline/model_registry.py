"""Persistent production model spec registry.

Reads and writes the active goal-model specification so that the daily
pipeline can automatically switch when adoption gates pass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT, LEGACY_MODEL_VERSION

PRODUCTION_SPEC_PATH = ROOT / "pipeline" / "data" / "production_model.json"


@dataclass(frozen=True)
class ModelSpec:
    family: str
    parameters: dict[str, float]

    @property
    def key(self) -> str:
        if not self.parameters:
            return self.family
        params = ",".join(f"{k}={v}" for k, v in sorted(self.parameters.items()))
        return f"{self.family}[{params}]"

    @classmethod
    def from_spec_string(cls, spec: str) -> "ModelSpec":
        """Parse a spec string like 'dixon_coles[half_life_days=730,rho=-0.08,shrinkage=6]'."""
        if "[" not in spec:
            return cls(family=spec, parameters={})
        family, rest = spec.split("[", 1)
        rest = rest.rstrip("]")
        params: dict[str, float] = {}
        for part in rest.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            try:
                params[k.strip()] = float(v.strip())
            except ValueError:
                params[k.strip()] = 0.0
        return cls(family=family.strip(), parameters=params)

    @classmethod
    def legacy(cls) -> "ModelSpec":
        return cls(family="legacy", parameters={})


def get_production_spec() -> ModelSpec:
    """Return the current production goal model spec, falling back to legacy."""
    try:
        if PRODUCTION_SPEC_PATH.exists():
            data = json.loads(PRODUCTION_SPEC_PATH.read_text(encoding="utf-8"))
            return ModelSpec(
                family=data.get("family", "legacy"),
                parameters=data.get("parameters", {}),
            )
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return ModelSpec.legacy()


def set_production_spec(spec: ModelSpec) -> None:
    """Persist a new production model spec atomically."""
    PRODUCTION_SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "family": spec.family,
        "parameters": spec.parameters,
        "key": spec.key,
        "updatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
    }
    PRODUCTION_SPEC_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def check_and_apply_adoption() -> bool:
    """Read the total-goals model review and auto-switch if adoption gates pass.

    Returns True if a switch occurred.
    """
    review_path = ROOT / "public" / "data" / "total-goals-model-review.json"
    if not review_path.exists():
        return False

    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    decision = review.get("adoptionDecision", {})
    if not decision.get("should_switch_model"):
        return False

    shadow = review.get("shadowModel", {})
    spec_string = shadow.get("spec", "")
    if not spec_string:
        return False

    new_spec = ModelSpec.from_spec_string(spec_string)
    current = get_production_spec()

    if new_spec.key == current.key:
        return False

    set_production_spec(new_spec)
    print(f"[model] auto-switched production model from {current.key} to {new_spec.key}")
    print(f"[model] reason: {decision.get('reason', 'adoption gates passed')}")
    return True


def get_model_version() -> str:
    """Return the current model version string for forecast metadata."""
    spec = get_production_spec()
    if spec.family == "legacy":
        return LEGACY_MODEL_VERSION
    return spec.key
