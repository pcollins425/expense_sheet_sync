"""Fetch reference rows from SQL."""
from __future__ import annotations

from sqlalchemy import text


def _cell(val) -> str:
    if val is None:
        return ""
    return str(val)


def fetch_states(engine) -> tuple[list[list[str]], dict[str, tuple[str, ...]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT reference_key, state_abbreviation, state
                FROM clients.states
                ORDER BY state_abbreviation, state
                """
            )
        ).mappings().all()
    values = [["reference_key", "state_abbreviation", "state"]]
    index: dict[str, tuple[str, ...]] = {}
    for r in rows:
        key = _cell(r["reference_key"])
        row = (_cell(r["state_abbreviation"]), _cell(r["state"]))
        values.append([key, row[0], row[1]])
        index[key] = row
    return values, index


def fetch_tribes(engine) -> tuple[list[list[str]], dict[str, tuple[str, ...]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    t.reference_key,
                    t.tribe_name,
                    t.tribe_short,
                    t.state_id,
                    s.state_abbreviation
                FROM clients.tribes t
                LEFT JOIN clients.states s ON s.reference_key = t.state_id
                ORDER BY t.tribe_name
                """
            )
        ).mappings().all()
    values = [["reference_key", "tribe_name", "tribe_short", "state_id", "state_abbreviation"]]
    index: dict[str, tuple[str, ...]] = {}
    for r in rows:
        key = _cell(r["reference_key"])
        row = (
            _cell(r["tribe_name"]),
            _cell(r["tribe_short"]),
            _cell(r["state_id"]),
            _cell(r["state_abbreviation"]),
        )
        values.append([key, *row])
        index[key] = row
    return values, index


def fetch_casinos(engine) -> tuple[list[list[str]], dict[str, tuple[str, ...]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    c.reference_key,
                    c.casino_name,
                    c.casino_short,
                    c.tribe_id,
                    t.tribe_name,
                    c.state_id,
                    s.state_abbreviation
                FROM clients.casinos c
                LEFT JOIN clients.tribes t ON t.reference_key = c.tribe_id
                LEFT JOIN clients.states s ON s.reference_key = c.state_id
                ORDER BY c.casino_name
                """
            )
        ).mappings().all()
    headers = [
        "reference_key",
        "casino_name",
        "casino_short",
        "tribe_id",
        "tribe_name",
        "state_id",
        "state_abbreviation",
    ]
    values = [headers]
    index: dict[str, tuple[str, ...]] = {}
    for r in rows:
        key = _cell(r["reference_key"])
        row = (
            _cell(r["casino_name"]),
            _cell(r["casino_short"]),
            _cell(r["tribe_id"]),
            _cell(r["tribe_name"]),
            _cell(r["state_id"]),
            _cell(r["state_abbreviation"]),
        )
        values.append([key, *row])
        index[key] = row
    return values, index


def fetch_account_select(engine) -> tuple[list[list[str]], dict[str, tuple[str, ...]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT gl_code, display_name
                FROM finance.expense_account_gl_display
                ORDER BY gl_code
                """
            )
        ).mappings().all()
    values = [["Expense Account"]]
    index: dict[str, tuple[str, ...]] = {}
    for r in rows:
        code = _cell(r["gl_code"])
        name = _cell(r["display_name"])
        label = f"{code} {name}".strip()
        values.append([label])
        index[code] = (name, label)
    return values, index
