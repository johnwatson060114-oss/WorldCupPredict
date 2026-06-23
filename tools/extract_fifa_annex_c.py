from __future__ import annotations

import io
import json
import re
import sys
import urllib.request
from itertools import combinations
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "pipeline" / "data" / "fifa-2026-annex-c.json"
SOURCE_URL = "https://digitalhub.fifa.com/m/636f5c9c6f29771f/original/FWC2026_regulations_EN.pdf"
WINNER_SLOTS = ("A", "B", "D", "E", "G", "I", "K", "L")


def extract_rows(pdf_bytes: bytes) -> dict[str, dict[str, str]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((reader.pages[index].extract_text() or "") for index in range(79, 97))
    rows: dict[str, dict[str, str]] = {}
    for match in re.finditer(
        r"(?m)^\s*(\d{1,3})\s+((?:3[A-L]\s+){7}3[A-L])\s*$",
        text,
    ):
        option = int(match.group(1))
        third_groups = [token[1:] for token in match.group(2).split()]
        if not 1 <= option <= 495 or len(third_groups) != 8:
            continue
        key = "".join(sorted(third_groups))
        assignment = dict(zip(WINNER_SLOTS, third_groups, strict=True))
        if key in rows and rows[key] != assignment:
            raise ValueError(f"Annex C combination {key} has conflicting assignments")
        rows[key] = assignment
    expected = {"".join(group_set) for group_set in combinations("ABCDEFGHIJKL", 8)}
    missing = expected - set(rows)
    extra = set(rows) - expected
    if missing or extra or len(rows) != 495:
        raise ValueError(
            f"Annex C extraction incomplete: rows={len(rows)} missing={sorted(missing)[:5]} extra={sorted(extra)[:5]}"
        )
    return dict(sorted(rows.items()))


def main() -> None:
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
        rows = extract_rows(response.read())
    payload = {
        "schemaVersion": 1,
        "sourceUrl": SOURCE_URL,
        "sourcePages": "80-97",
        "winnerSlots": list(WINNER_SLOTS),
        "combinationCount": len(rows),
        "combinations": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(rows)} Annex C combinations")


if __name__ == "__main__":
    sys.exit(main())
