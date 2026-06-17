"""Poll SQL reference tables and push changes to Google Sheet tabs."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from root_replace import (
    ROOT_COL_CASINO,
    ROOT_COL_STATE,
    ROOT_COL_TRIBE,
    LabelReplace,
    apply_root_label_replaces,
    collect_renames,
)
from sheets_write import batch_write_tabs
from snapshot import load_snapshot, normalize_rows, save_snapshot
from sql_fetch import fetch_casinos, fetch_states, fetch_tribes


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
    previous: dict[str, tuple[str, ...]]
    changed: set[str]
    root_column_index: int
    label_index: int


def _detect_table(
    engine: Engine,
    *,
    snapshot_name: str,
    sheet_tab: str,
    fetch_fn,
    root_column_index: int,
    label_index: int,
) -> TabChange | None:
    values, current = fetch_fn(engine)
    previous_raw = load_snapshot(snapshot_name).get("rows", {})
    previous = normalize_rows(previous_raw) if previous_raw else {}
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
        previous=previous,
        changed=changed,
        root_column_index=root_column_index,
        label_index=label_index,
    )


def poll_all(engine: Engine, service) -> list[str]:
    pending = [
        _detect_table(
            engine,
            snapshot_name="sql_states",
            sheet_tab="States",
            fetch_fn=fetch_states,
            root_column_index=ROOT_COL_STATE,
            label_index=0,
        ),
        _detect_table(
            engine,
            snapshot_name="sql_tribes",
            sheet_tab="Tribes",
            fetch_fn=fetch_tribes,
            root_column_index=ROOT_COL_TRIBE,
            label_index=0,
        ),
        _detect_table(
            engine,
            snapshot_name="sql_casinos",
            sheet_tab="Casinos",
            fetch_fn=fetch_casinos,
            root_column_index=ROOT_COL_CASINO,
            label_index=0,
        ),
    ]
    changes = [c for c in pending if c is not None]
    if not changes:
        return []

    batch_write_tabs(service, {c.sheet_tab: c.values for c in changes})

    replaces: list[LabelReplace] = []
    logs: list[str] = []
    for c in changes:
        logs.append(f"{c.sheet_tab}: SQL change -> wrote {len(c.values) - 1} row(s)")
        replaces.extend(
            collect_renames(
                c.changed,
                c.previous,
                c.current,
                column_index=c.root_column_index,
                label_index=c.label_index,
            )
        )

    if replaces:
        logs.extend(apply_root_label_replaces(service, replaces))

    for c in changes:
        save_snapshot(c.snapshot_name, {"rows": c.current})

    return logs
