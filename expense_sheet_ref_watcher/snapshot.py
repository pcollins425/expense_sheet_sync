"""Persist SQL row snapshots for diff-based polling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import state_dir


def _path(name: str) -> Path:
    safe = name.replace("/", "_")
    return state_dir() / f"{safe}.json"


def _normalize_row(row: tuple[str, ...] | list[str]) -> list[str]:
    return list(row)


def normalize_rows(rows: dict[str, tuple[str, ...] | list[str]]) -> dict[str, list[str]]:
    return {k: _normalize_row(v) for k, v in rows.items()}


def load_snapshot(name: str) -> dict[str, Any]:
    p = _path(name)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_snapshot(name: str, data: dict[str, Any]) -> None:
    p = _path(name)
    payload = dict(data)
    if "rows" in payload:
        payload["rows"] = normalize_rows(payload["rows"])
    p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
