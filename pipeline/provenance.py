from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from .config import ROOT


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot_manifest(paths: Iterable[Path], cutoff: str) -> dict:
    files = []
    for path in sorted({item.resolve() for item in paths if item.exists()}):
        try:
            relative = path.relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            relative = path.name
        files.append({
            "path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })

    manifest_digest = hashlib.sha256()
    for item in files:
        manifest_digest.update(f"{item['path']}:{item['sha256']}\n".encode("utf-8"))
    return {
        "id": manifest_digest.hexdigest(),
        "cutoff": cutoff,
        "files": files,
    }
