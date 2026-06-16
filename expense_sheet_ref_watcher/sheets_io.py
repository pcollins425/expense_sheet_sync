"""Read/write Google Sheet tabs for reference sync."""
from __future__ import annotations

import re
from typing import Any

from config import root_tab, sheet_id

_GL_ROW_RE = re.compile(r"^(\d{4})\s+(.*)$", re.DOTALL)


def escape_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def read_tab(service, tab: str, col_range: str = "A:Z") -> list[list[str]]:
    sid = sheet_id()
    rng = f"{escape_tab(tab)}!{col_range}"
    result = (
        service.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute()
    )
    rows = result.get("values", [])
    out: list[list[str]] = []
    for row in rows:
        out.append([str(c).strip() if c is not None else "" for c in row])
    return out


def parse_gl_account_label(raw: str) -> tuple[str, str] | None:
    text = (raw or "").strip()
    if not text or text.lower() == "expense account":
        return None
    m = _GL_ROW_RE.match(text)
    if not m:
        return None
    code, name = m.group(1), m.group(2).strip()
    if not name:
        return None
    return code, name


def sheet_label(gl_code: str, display_name: str) -> str:
    return f"{gl_code} {display_name}".strip()


def update_account_select_row(service, gl_code: str, label: str) -> None:
    sid = sheet_id()
    rows = read_tab(service, "account_select", "A:A")
    row_num = None
    for i, row in enumerate(rows, start=1):
        if not row:
            continue
        parsed = parse_gl_account_label(row[0])
        if parsed and parsed[0] == gl_code:
            row_num = i
            break
    if row_num is None:
        return
    rng = f"{escape_tab('account_select')}!A{row_num}"
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=rng,
        valueInputOption="RAW",
        body={"values": [[label]]},
    ).execute()


def root_expense_map(rows: list[list[str]]) -> dict[str, str]:
    """ESL reference_key -> Expense Account cell (column J / index 9)."""
    out: dict[str, str] = {}
    for row in rows[1:]:
        if not row:
            continue
        key = row[0].strip() if len(row) > 0 else ""
        if not key or key == "reference_key" or not key.startswith("ESL-"):
            continue
        expense = row[9].strip() if len(row) > 9 else ""
        out[key] = expense
    return out
