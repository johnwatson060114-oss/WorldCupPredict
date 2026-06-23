from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import MANUAL_DIR
from .config import ROOT


STATUS_LABELS = {
    "out": "确认缺阵",
    "injured": "伤病",
    "doubtful": "出战成疑",
    "suspended": "停赛",
    "probable": "大概率出场",
}


TOURNAMENT_AVAILABILITY_PATH = ROOT / "pipeline" / "data" / "tournament-availability.json"


def load_availability(
    path: Path = MANUAL_DIR / "availability.csv",
    tournament_path: Path = TOURNAMENT_AVAILABILITY_PATH,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        pass
    else:
        with path.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                if not row.get("team") or not row.get("player") or not row.get("target_date"):
                    continue
                if not row.get("source_url") or not row.get("observed_at"):
                    continue
                records.append({
                    **row,
                    "availability_probability": min(1.0, max(0.0, float(row["availability_probability"]))),
                    "confidence": min(1.0, max(0.0, float(row.get("confidence") or 0.5))),
                })
    if tournament_path.exists():
        payload = json.loads(tournament_path.read_text(encoding="utf-8"))
        for item in payload.get("records", []):
            records.append({
                **item,
                "availability_probability": min(
                    1.0, max(0.0, float(item["availability_probability"]))
                ),
                "confidence": min(1.0, max(0.0, float(item.get("confidence") or 0.5))),
            })
    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (str(record["team"]), str(record["player"]), str(record["target_date"]))
        previous = deduplicated.get(key)
        if previous is None or float(record["confidence"]) > float(previous["confidence"]):
            deduplicated[key] = record
    return list(deduplicated.values())


def apply_availability(seeds: list[dict[str, Any]], target_date: str, records: list[dict[str, Any]]) -> None:
    relevant = [record for record in records if record["target_date"] == target_date]
    for seed in seeds:
        matched = [
            record for record in relevant
            if record["team"] in {seed["home_team"], seed["away_team"]}
        ]
        if not matched:
            continue
        notes = []
        uncertainty_penalty = 0.0
        for record in matched:
            probability = record["availability_probability"]
            label = STATUS_LABELS.get(record["status"], record["status"])
            notes.append(f"{record['team']} {record['player']}：{label}，估计出场概率 {probability:.0%}")
            if 0.1 < probability < 0.9:
                uncertainty_penalty += 0.04 * record["confidence"]
            else:
                uncertainty_penalty += 0.02 * record["confidence"]
        seed["coverage"] = round(max(0.0, float(seed.get("coverage", 0.7)) - min(0.08, uncertainty_penalty)), 3)
        factors = seed.get("factors", [])
        lineup_factor = next((factor for factor in factors if factor.get("label") == "预计首发"), None)
        if lineup_factor is not None:
            lineup_factor["note"] = "；".join(notes) + "。球员影响系数尚未通过时间顺序回测，仅降低置信度"
            lineup_factor["active"] = False
        missing = seed.setdefault("missing_data", [])
        missing.append("人员状态已记录，但球员级 xG 影响尚未完成回测，不进行人工加减分")
        seed["availability"] = matched
        seed["confirmed_absences"] = [
            record for record in matched
            if record["status"] in {"out", "suspended"} and record["availability_probability"] <= 0.05
        ]
