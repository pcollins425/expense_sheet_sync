"""Diff reference tabs and apply SQL + queue fan-out."""
from __future__ import annotations

from sheets_io import parse_gl_account_label, read_tab, root_expense_map
from snapshot import load_snapshot, save_snapshot
from sql_sync import (
    sync_account_select_change,
    sync_casino_change,
    sync_root_expense_change,
    sync_state_change,
    sync_tribe_change,
)


def _row_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, h in enumerate(headers):
        key = h.strip()
        if not key:
            continue
        out[key] = row[i].strip() if i < len(row) else ""
    return out


def _diff_table(
    tab: str, rows: list[list[str]], key_col: str
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    if not rows:
        return {}, {}
    headers = rows[0]
    current: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        d = _row_dict(headers, row)
        key = d.get(key_col, "").strip()
        if key and key != key_col:
            current[key] = d
    previous = load_snapshot(tab)
    prev_rows = previous.get("rows", {})
    return current, prev_rows


def _save_table(tab: str, rows: dict[str, dict[str, str]]) -> None:
    save_snapshot(tab, {"rows": rows})


def poll_account_select(engine, service) -> list[str]:
    rows = read_tab(service, "account_select", "A:E")
    current, previous = _diff_table("account_select", rows, "gl_code")
    # rebuild keyed by gl_code from column A
    current = {}
    for row in rows[1:]:
        if not row:
            continue
        parsed = parse_gl_account_label(row[0] if row else "")
        if not parsed:
            continue
        code, name = parsed
        current[code] = {
            "gl_code": code,
            "display_name": name,
            "account_label": row[0],
        }

    previous_rows = load_snapshot("account_select").get("rows", {})
    if not previous_rows:
        _save_table("account_select", current)
        return []

    logs: list[str] = []
    for code, data in current.items():
        prev = previous_rows.get(code)
        if prev and prev.get("display_name") == data["display_name"]:
            continue
        n = sync_account_select_change(
            engine,
            service,
            code,
            data["display_name"],
            data["account_label"],
        )
        logs.append(f"account_select {code} -> queued ~{n} ESL row(s)")

    _save_table("account_select", current)
    return logs


def poll_states(engine, service) -> list[str]:
    rows = read_tab(service, "States", "A:C")
    current, previous = _diff_table("States", rows, "reference_key")
    if not previous:
        _save_table("States", current)
        return []
    logs: list[str] = []
    for ref, data in current.items():
        prev = previous.get(ref)
        if prev == data:
            continue
        n = sync_state_change(
            engine,
            ref,
            data.get("state_abbreviation", ""),
            data.get("state", ""),
        )
        logs.append(f"States {ref} -> queued ~{n} ESL row(s)")
    _save_table("States", current)
    return logs


def poll_tribes(engine, service) -> list[str]:
    rows = read_tab(service, "Tribes", "A:E")
    current, previous = _diff_table("Tribes", rows, "reference_key")
    if not previous:
        _save_table("Tribes", current)
        return []
    logs: list[str] = []
    for ref, data in current.items():
        prev = previous.get(ref)
        if prev == data:
            continue
        n = sync_tribe_change(
            engine,
            ref,
            data.get("tribe_name", ""),
            data.get("tribe_short", ""),
            data.get("state_id", ""),
        )
        logs.append(f"Tribes {ref} -> queued ~{n} ESL row(s)")
    _save_table("Tribes", current)
    return logs


def poll_casinos(engine, service) -> list[str]:
    rows = read_tab(service, "Casinos", "A:G")
    current, previous = _diff_table("Casinos", rows, "reference_key")
    if not previous:
        _save_table("Casinos", current)
        return []
    logs: list[str] = []
    for ref, data in current.items():
        prev = previous.get(ref)
        # Ignore denormalized tribe_name / state_abbreviation drift from SQL export
        cmp_prev = dict(prev) if prev else None
        cmp_data = {
            k: data.get(k, "")
            for k in (
                "reference_key",
                "casino_name",
                "casino_short",
                "tribe_id",
                "state_id",
            )
        }
        if cmp_prev:
            cmp_prev = {k: cmp_prev.get(k, "") for k in cmp_data}
        if cmp_prev == cmp_data:
            continue
        n = sync_casino_change(
            engine,
            ref,
            data.get("casino_name", ""),
            data.get("casino_short", ""),
            data.get("tribe_id", ""),
            data.get("state_id", ""),
        )
        logs.append(f"Casinos {ref} -> queued ~{n} ESL row(s)")
    _save_table("Casinos", current)
    return logs


def poll_root_expense_accounts(engine, service, root_tab: str) -> list[str]:
    rows = read_tab(service, root_tab, "A:K")
    current = root_expense_map(rows)
    previous = load_snapshot("root_expense").get("rows", {})
    if not previous:
        save_snapshot("root_expense", {"rows": current})
        return []
    logs: list[str] = []

    for esl_key, label in current.items():
        if previous.get(esl_key) == label:
            continue
        if not label:
            continue
        if sync_root_expense_change(engine, service, esl_key, label):
            logs.append(f"root {esl_key} expense_account updated")
        else:
            logs.append(f"root {esl_key} expense_account skipped (invalid or no expense)")

    save_snapshot("root_expense", {"rows": current})
    return logs


def poll_all(engine, service, root_tab: str) -> list[str]:
    logs: list[str] = []
    logs.extend(poll_account_select(engine, service))
    logs.extend(poll_states(engine, service))
    logs.extend(poll_tribes(engine, service))
    logs.extend(poll_casinos(engine, service))
    logs.extend(poll_root_expense_accounts(engine, service, root_tab))
    return logs
