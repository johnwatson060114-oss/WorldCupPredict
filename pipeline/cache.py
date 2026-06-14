from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class JsonCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        folder = self.root / namespace
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}.json"

    def get(self, namespace: str, key: str, max_age: timedelta) -> Any | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(payload["created_at"])
        if datetime.now(UTC) - created > max_age:
            return None
        return payload["value"]

    def set(self, namespace: str, key: str, value: Any) -> None:
        path = self._path(namespace, key)
        payload = {"created_at": datetime.now(UTC).isoformat(), "value": value}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
