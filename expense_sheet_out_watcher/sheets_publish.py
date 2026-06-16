"""Publish finance.expense_supervisor_line rows to Google Sheets."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from googleapiclient.errors import HttpError
from sqlalchemy import text

from config import sheet_id, sheet_tab
from db import get_engine
from google_creds import sheets_service

HEADERS = [
    "reference_key",
    "Date",
    "Card Member",
    "Amount",
    "Comments",
    "Description",
    "Tribe/Dynamic location",
    "State",
    "Casino/Dynamic location",
    "Expense Account",
    "Receipt",
]

LAST_COL = "K"

ROW_SQL = text(
    """
    SELECT
        esl_reference_key,
        [date],
        card_member,
        amount,
        comments,
        description,
        tribe_dynamic_location,
        [state],
        casino_dynamic_location,
        expense_account,
        receipt
    FROM finance.vw_expense_supervisor_sheet
    WHERE esl_reference_key = :hub_key
    """
)


def _escape_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _cell_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, Decimal):
        return format(val, "f")
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


def _row_values(mapping: dict[str, Any]) -> list[str]:
    return [
        _cell_str(mapping.get("esl_reference_key")),
        _cell_str(mapping.get("date")),
        _cell_str(mapping.get("card_member")),
        _cell_str(mapping.get("amount")),
        _cell_str(mapping.get("comments")),
        _cell_str(mapping.get("description")),
        _cell_str(mapping.get("tribe_dynamic_location")),
        _cell_str(mapping.get("state")),
        _cell_str(mapping.get("casino_dynamic_location")),
        _cell_str(mapping.get("expense_account")),
        _cell_str(mapping.get("receipt")),
    ]


def fetch_row(engine, hub_key: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        r = conn.execute(ROW_SQL, {"hub_key": hub_key}).mappings().first()
        return dict(r) if r else None


def ensure_tab_and_headers(service) -> None:
    sid = sheet_id()
    tab = sheet_tab()
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    sheet_meta = None
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == tab:
            sheet_meta = s["properties"]
            break
    if sheet_meta is None:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={
                "requests": [
                    {"addSheet": {"properties": {"title": tab}}}
                ]
            },
        ).execute()
        sheet_id_internal = None
    else:
        sheet_id_internal = sheet_meta["sheetId"]

    rng = f"{_escape_tab(tab)}!A1:{LAST_COL}1"
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=rng,
        valueInputOption="RAW",
        body={"values": [HEADERS]},
    ).execute()
    return sheet_id_internal


def ensure_grid_rows(service, min_rows: int) -> None:
    """Expand the target tab so bootstrap fits (default new sheets are often 1000 rows)."""
    sid = sheet_id()
    tab = sheet_tab()
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta.get("sheets", []):
        props = s["properties"]
        if props["title"] != tab:
            continue
        current = int((props.get("gridProperties") or {}).get("rowCount") or 1000)
        needed = max(current, min_rows + 10)
        if needed <= current:
            return
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": props["sheetId"],
                                "gridProperties": {"rowCount": needed},
                            },
                            "fields": "gridProperties.rowCount",
                        }
                    }
                ]
            },
        ).execute()
        return


def _col_a_index(service) -> dict[str, int]:
    sid = sheet_id()
    tab = sheet_tab()
    rng = f"{_escape_tab(tab)}!A:A"
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sid, range=rng)
        .execute()
    )
    out: dict[str, int] = {}
    for i, row in enumerate(result.get("values", []), start=1):
        if not row:
            continue
        key = str(row[0]).strip()
        if key and key != HEADERS[0]:
            out[key] = i
    return out


def upsert_row(service, engine, hub_key: str, index_cache: dict[str, int] | None = None) -> None:
    row = fetch_row(engine, hub_key)
    if row is None:
        raise ValueError(f"ESL row not found in database: {hub_key}")

    sid = sheet_id()
    tab = sheet_tab()
    values = [_row_values(row)]
    cache = index_cache if index_cache is not None else _col_a_index(service)
    row_num = cache.get(hub_key)

    if row_num is None:
        append_rng = f"{_escape_tab(tab)}!A:{LAST_COL}"
        service.spreadsheets().values().append(
            spreadsheetId=sid,
            range=append_rng,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        return

    update_rng = f"{_escape_tab(tab)}!A{row_num}:{LAST_COL}{row_num}"
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=update_rng,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def delete_row(service, hub_key: str, index_cache: dict[str, int] | None = None) -> None:
    cache = index_cache if index_cache is not None else _col_a_index(service)
    row_num = cache.get(hub_key)
    if row_num is None:
        return
    sid = sheet_id()
    tab = sheet_tab()
    update_rng = f"{_escape_tab(tab)}!A{row_num}:{LAST_COL}{row_num}"
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=update_rng,
        valueInputOption="RAW",
        body={"values": [[""] * len(HEADERS)]},
    ).execute()


def bootstrap_all(engine, service) -> int:
    ensure_tab_and_headers(service)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    esl_reference_key,
                    [date],
                    card_member,
                    amount,
                    comments,
                    description,
                    tribe_dynamic_location,
                    [state],
                    casino_dynamic_location,
                    expense_account,
                    receipt
                FROM finance.vw_expense_supervisor_sheet
                ORDER BY [date] DESC, esl_reference_key DESC
                """
            )
        ).mappings().all()

    values = [_row_values(dict(r)) for r in rows]
    if not values:
        return 0

    ensure_grid_rows(service, len(values) + 1)

    sid = sheet_id()
    tab = sheet_tab()
    chunk = int(os.environ.get("EXPENSE_SHEET_BOOTSTRAP_CHUNK", "500"))
    start_row = 2
    for i in range(0, len(values), chunk):
        block = values[i : i + chunk]
        row_start = start_row + i
        row_end = row_start + len(block) - 1
        rng = f"{_escape_tab(tab)}!A{row_start}:{LAST_COL}{row_end}"
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=rng,
            valueInputOption="RAW",
            body={"values": block},
        ).execute()
    # Drop legacy 12th column from prior layout (expense Reference Key / shifted receipt).
    service.spreadsheets().values().clear(
        spreadsheetId=sid,
        range=f"{_escape_tab(tab)}!L:L",
        body={},
    ).execute()
    return len(values)


def parse_payload(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid queue payload JSON: {e}") from e
