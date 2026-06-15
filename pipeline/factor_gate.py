from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .backtest import score_predictions
from .config import ROOT


DEFAULT_ADMISSIONS_PATH = ROOT / "pipeline" / "data" / "factor-admissions.json"


@dataclass(frozen=True)
class FactorAdmission:
    factor: str
    status: str
    enabled: bool
    log_loss_delta: float
    rps_delta: float
    calibration_delta: float
    stable_windows: int
    total_windows: int
    bootstrap_improvement_share: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metrics(records: Iterable[dict[str, Any]], key: str) -> dict[str, float]:
    return score_predictions((record[key], record["actual"]) for record in records)


def evaluate_factor(
    factor: str,
    records: Iterable[dict[str, Any]],
    bootstrap_samples: int = 400,
    stability_threshold: float = 0.80,
    minimum_windows: int = 3,
    calibration_tolerance: float = 0.005,
    seed: int = 20_260_615,
) -> FactorAdmission:
    samples = list(records)
    windows = sorted({str(record["window"]) for record in samples})
    if len(windows) < minimum_windows:
        return FactorAdmission(factor, "observation_only", False, 0, 0, 0, 0, len(windows), 0, "insufficient rolling windows")
    baseline = _metrics(samples, "baseline")
    candidate = _metrics(samples, "candidate")
    log_delta = candidate["log_loss"] - baseline["log_loss"]
    rps_delta = candidate["rps"] - baseline["rps"]
    calibration_delta = candidate["calibration_error"] - baseline["calibration_error"]

    stable_windows = 0
    for window in windows:
        window_records = [record for record in samples if str(record["window"]) == window]
        base = _metrics(window_records, "baseline")
        test = _metrics(window_records, "candidate")
        if test["log_loss"] < base["log_loss"] and test["rps"] <= base["rps"]:
            stable_windows += 1

    by_block: dict[str, list[dict[str, Any]]] = {}
    for record in samples:
        by_block.setdefault(str(record["block"]), []).append(record)
    blocks = sorted(by_block)
    randomizer = random.Random(seed)
    improvements = 0
    for _ in range(bootstrap_samples):
        resampled = [record for _ in blocks for record in by_block[randomizer.choice(blocks)]]
        base = _metrics(resampled, "baseline")
        test = _metrics(resampled, "candidate")
        if test["log_loss"] < base["log_loss"] and test["rps"] <= base["rps"]:
            improvements += 1
    share = improvements / bootstrap_samples if bootstrap_samples else 0.0
    enabled = (
        log_delta < 0
        and rps_delta <= 0
        and calibration_delta <= calibration_tolerance
        and stable_windows == len(windows)
        and share >= stability_threshold
    )
    reason = (
        "stable sample-out improvement"
        if enabled
        else "failed stability, calibration, or multi-window admission threshold"
    )
    return FactorAdmission(
        factor=factor,
        status="enabled" if enabled else "observation_only",
        enabled=enabled,
        log_loss_delta=round(log_delta, 6),
        rps_delta=round(rps_delta, 6),
        calibration_delta=round(calibration_delta, 6),
        stable_windows=stable_windows,
        total_windows=len(windows),
        bootstrap_improvement_share=round(share, 4),
        reason=reason,
    )


def load_factor_admissions(path: Path = DEFAULT_ADMISSIONS_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("factors", {}))


def apply_factor_admissions(seeds: list[dict[str, Any]], admissions: dict[str, dict[str, Any]]) -> None:
    for seed in seeds:
        for factor in seed.get("factors", []):
            if factor.get("admissionStatus") == "core":
                factor["active"] = True
                factor["uncertaintyOnly"] = False
                factor["admissionReason"] = "基础实力是核心模型输入，不属于候选赛前修正"
                continue
            admission = admissions.get(str(factor.get("label")), {})
            enabled = admission.get("status") == "enabled" and admission.get("enabled") is True
            factor["admissionStatus"] = "enabled" if enabled else "observation_only"
            factor["active"] = bool(factor.get("active", False) and enabled)
            factor["uncertaintyOnly"] = not enabled
            factor["admissionReason"] = admission.get("reason", "尚无通过样本外消融回测的准入报告")
