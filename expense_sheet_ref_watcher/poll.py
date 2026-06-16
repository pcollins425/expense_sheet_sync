"""Poll SQL reference tables and push changes to Google Sheet tabs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from fan_out import enqueue_by_fk, enqueue_by_gl_code
from sheets_write import batch_write_tabs
from snapshot import load_snapshot, normalize_rows, save_snapshot
from sql_fetch import fetch_account_select, fetch_casinos, fetch_states, fetch_tribes


def _changed_keys(
    current: dict[str, tuple[str, ...]], previous: dict[str, tuple[str, ...] | list[str]]
) -> set[str]:
    prev = normalize_rows(previous) if previous else {}
    cur = normalize_rows(current)
    keys = set(cur) | set(prev)
    return {k for k in keys if cur.get(k) != prev.get(k)}


@dataclass
class TabChange:
    sheet_tab: str
    snapshot_name: str
    values: list[list[str]]
    current: dict[str, tuple[str, ...]]
    changed: set[str]
    fan_out: Callable[[Engine, str], int] | None = None


def _detect_table(
    engine: Engine,
    *,
    snapshot_name: str,
    sheet_tab: str,
    fetch_fn,
    fan_out: Callable[[Engine, str], int] | None = None,
) -> TabChange | None:
    values, current = fetch_fn(engine)
    previous = load_snapshot(snapshot_name).get("rows", {})
    if not previous:
        save_snapshot(snapshot_name, {"rows": current})
        return None

    changed = _changed_keys(current, previous)
    if not changed:
        return None

    return TabChange(
        sheet_tab=sheet_tab,
        snapshot_name=snapshot_name,
        values=values,
        current=current,
        changed=changed,
        fan_out=fan_out,
    )


def poll_all(engine: Engine, service) -> list[str]:
    pending = [
        _detect_table(
            engine,
            snapshot_name="sql_states",
            sheet_tab="States",
            fetch_fn=fetch_states,
            fan_out=lambda eng, key: enqueue_by_fk(eng, "state", key),
        ),
        _detect_table(
            engine,
            snapshot_name="sql_tribes",
            sheet_tab="Tribes",
            fetch_fn=fetch_tribes,
            fan_out=lambda eng, key: enqueue_by_fk(eng, "tribe", key),
        ),
        _detect_table(
            engine,
            snapshot_name="sql_casinos",
            sheet_tab="Casinos",
            fetch_fn=fetch_casinos,
            fan_out=lambda eng, key: enqueue_by_fk(eng, "casino", key),
        ),
        _detect_table(
            engine,
            snapshot_name="sql_account_select",
            sheet_tab="account_select",
            fetch_fn=fetch_account_select,
            fan_out=lambda eng, key: enqueue_by_gl_code(eng, key),
        ),
    ]
    changes = [c for c in pending if c is not None]
    if not changes:
        return []

    batch_write_tabs(service, {c.sheet_tab: c.values for c in changes})

    logs: list[str] = []
    for c in changes:
        logs.append(f"{c.sheet_tab}: SQL change -> wrote {len(c.values) - 1} row(s)")
        if c.fan_out:
            for key in sorted(c.changed):
                if key not in c.current:
                    continue
                n = c.fan_out(engine, key)
                logs.append(f"{c.sheet_tab} {key} -> queued ~{n} ESL row(s)")
        save_snapshot(c.snapshot_name, {"rows": c.current})

    return logs
