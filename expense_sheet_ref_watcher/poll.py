"""Poll SQL reference tables and push changes to Google Sheet tabs."""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.engine import Engine

from fan_out import enqueue_by_fk, enqueue_by_gl_code
from sheets_write import write_tab
from snapshot import load_snapshot, save_snapshot
from sql_fetch import fetch_account_select, fetch_casinos, fetch_states, fetch_tribes


def _changed_keys(
    current: dict[str, tuple[str, ...]], previous: dict[str, tuple[str, ...]]
) -> set[str]:
    keys = set(current) | set(previous)
    return {k for k in keys if current.get(k) != previous.get(k)}


def _sync_table(
    engine,
    service,
    *,
    snapshot_name: str,
    sheet_tab: str,
    fetch_fn,
    fan_out: Callable[[Engine, str], int] | None = None,
) -> list[str]:
    values, current = fetch_fn(engine)
    previous = load_snapshot(snapshot_name).get("rows", {})
    if not previous:
        save_snapshot(snapshot_name, {"rows": current})
        return []

    changed = _changed_keys(current, previous)
    if not changed:
        return []

    write_tab(service, sheet_tab, values)
    logs = [f"{sheet_tab}: SQL change -> wrote {len(values) - 1} row(s)"]

    if fan_out:
        for key in sorted(changed):
            if key not in current:
                continue
            n = fan_out(engine, key)
            logs.append(f"{sheet_tab} {key} -> queued ~{n} ESL row(s)")

    save_snapshot(snapshot_name, {"rows": current})
    return logs


def poll_states(engine: Engine, service) -> list[str]:
    return _sync_table(
        engine,
        service,
        snapshot_name="sql_states",
        sheet_tab="States",
        fetch_fn=fetch_states,
        fan_out=lambda eng, key: enqueue_by_fk(eng, "state", key),
    )


def poll_tribes(engine: Engine, service) -> list[str]:
    return _sync_table(
        engine,
        service,
        snapshot_name="sql_tribes",
        sheet_tab="Tribes",
        fetch_fn=fetch_tribes,
        fan_out=lambda eng, key: enqueue_by_fk(eng, "tribe", key),
    )


def poll_casinos(engine: Engine, service) -> list[str]:
    return _sync_table(
        engine,
        service,
        snapshot_name="sql_casinos",
        sheet_tab="Casinos",
        fetch_fn=fetch_casinos,
        fan_out=lambda eng, key: enqueue_by_fk(eng, "casino", key),
    )


def poll_account_select(engine: Engine, service) -> list[str]:
    return _sync_table(
        engine,
        service,
        snapshot_name="sql_account_select",
        sheet_tab="account_select",
        fetch_fn=fetch_account_select,
        fan_out=lambda eng, key: enqueue_by_gl_code(eng, key),
    )
