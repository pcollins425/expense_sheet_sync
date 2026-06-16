"""Persist tab snapshots for diff-based polling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import state_dir


def _path(name: str) -> Path:
    safe = name.replace("/", "_")
    return state_dir() / f"{safe}.json"


def load_snapshot(name: str) -> dict[str, Any]:
    p = _path(name)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_snapshot(name: str, data: dict[str, Any]) -> None:
    p = _path(name)
    p.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
