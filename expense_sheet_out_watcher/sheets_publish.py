"""Publish finance.expense_supervisor_line rows to Google Sheets."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from googleapiclient.errors import HttpError
from sqlalchemy import text

from config import sheet_id, sheet_tab

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
    "Override Receipt",
]

LAST_COL = "K"
HEADER_LAST_COL = "L"
OVERRIDE_RECEIPT_COL = "L"
_BLANK_ROW = [[""] * len(HEADERS)]
_UPDATED_RANGE_RE = re.compile(r"!A(\d+)", re.IGNORECASE)

_SHEET_ROW_SELECT = """
    SELECT
        v.esl_reference_key,
        v.[date],
        v.card_member,
        v.amount,
        v.comments,
        v.description,
        v.tribe_dynamic_location,
        v.[state],
        v.casino_dynamic_location,
        v.expense_account,
        v.receipt,
        CAST(COALESCE(ex.override_receipt, esl.override_receipt, 0) AS bit) AS override_receipt
    FROM finance.vw_expense_supervisor_sheet v
    INNER JOIN finance.expense_supervisor_line esl
        ON esl.reference_key = v.esl_reference_key
    LEFT JOIN finance.expenses ex
        ON ex.reference_key = esl.expense_id
"""

ROW_SQL = text(
    _SHEET_ROW_SELECT
    + """
    WHERE v.esl_reference_key = :hub_key
    """
)


@dataclass
class PreparedItem:
    queue_id: int
    hub_key: str
    op: str
    row_data: dict[str, Any] | None = None


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


def _override_receipt_bool(mapping: dict[str, Any]) -> bool:
    val = mapping.get("override_receipt")
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, Decimal)):
        return bool(int(val))
    return str(val).strip().upper() in ("1", "TRUE", "YES", "Y")


def _override_receipt_batch_data(
    tab: str, row_num: int, mapping: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "range": f"{tab}!{OVERRIDE_RECEIPT_COL}{row_num}",
        "values": [[_override_receipt_bool(mapping or {})]],
    }


def _batch_override_receipt_update(
    service, data: list[dict[str, Any]], *, what: str
) -> None:
    if not data:
        return
    sid = sheet_id()
    _execute_with_retry(
        lambda: service.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=sid,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        )
        .execute(),
        what=what,
    )


def _retry_seconds() -> float:
    return float(os.environ.get("EXPENSE_SHEET_RETRY_SECONDS", "15"))


def _max_retries() -> int:
    return int(os.environ.get("EXPENSE_SHEET_MAX_RETRIES", "6"))


def _execute_with_retry(fn, *, what: str):
    max_attempts = _max_retries()
    for attempt in range(max_attempts):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status == 429 and attempt < max_attempts - 1:
                wait = _retry_seconds() * (2**attempt)
                print(
                    f"Sheets 429 on {what}; retry {attempt + 1}/{max_attempts - 1} "
                    f"in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            raise


def fetch_row(engine, hub_key: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        r = conn.execute(ROW_SQL, {"hub_key": hub_key}).mappings().first()
        return dict(r) if r else None


def ensure_tab_and_headers(service) -> None:
    sid = sheet_id()
    tab = sheet_tab()
    meta = _execute_with_retry(
        lambda: service.spreadsheets().get(spreadsheetId=sid).execute(),
        what="spreadsheet metadata",
    )
    sheet_meta = None
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == tab:
            sheet_meta = s["properties"]
            break
    if sheet_meta is None:
        _execute_with_retry(
            lambda: service.spreadsheets()
            .batchUpdate(
                spreadsheetId=sid,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
            )
            .execute(),
            what=f"add tab {tab}",
        )

    rng = f"{_escape_tab(tab)}!A1:{HEADER_LAST_COL}1"
    _execute_with_retry(
        lambda: service.spreadsheets()
        .values()
        .update(
            spreadsheetId=sid,
            range=rng,
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        )
        .execute(),
        what=f"write headers on {tab}",
    )


def ensure_grid_rows(service, min_rows: int) -> None:
    """Expand the target tab so bootstrap fits (default new sheets are often 1000 rows)."""
    sid = sheet_id()
    tab = sheet_tab()
    meta = _execute_with_retry(
        lambda: service.spreadsheets().get(spreadsheetId=sid).execute(),
        what="spreadsheet metadata",
    )
    for s in meta.get("sheets", []):
        props = s["properties"]
        if props["title"] != tab:
            continue
        current = int((props.get("gridProperties") or {}).get("rowCount") or 1000)
        needed = max(current, min_rows + 10)
        if needed <= current:
            return
        _execute_with_retry(
            lambda: service.spreadsheets()
            .batchUpdate(
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
            )
            .execute(),
            what=f"expand {tab} rows",
        )
        return


def col_a_index(service) -> dict[str, int]:
    """One read of column A per batch — maps ESL reference_key -> sheet row number."""
    sid = sheet_id()
    tab = sheet_tab()
    rng = f"{_escape_tab(tab)}!A:A"
    result = _execute_with_retry(
        lambda: service.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute(),
        what=f"read {tab} column A",
    )
    out: dict[str, int] = {}
    for i, row in enumerate(result.get("values", []), start=1):
        if not row:
            continue
        key = str(row[0]).strip()
        if key and key != HEADERS[0]:
            out[key] = i
    return out


def _first_row_from_updated_range(updated_range: str) -> int:
    m = _UPDATED_RANGE_RE.search(updated_range.replace("'", ""))
    if not m:
        raise ValueError(f"cannot parse updatedRange: {updated_range!r}")
    return int(m.group(1))


def _batch_values_update(service, data: list[dict[str, Any]]) -> None:
    if not data:
        return
    sid = sheet_id()
    _execute_with_retry(
        lambda: service.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=sid,
            body={"valueInputOption": "RAW", "data": data},
        )
        .execute(),
        what=f"batch update {len(data)} range(s)",
    )


def publish_batch(
    service,
    engine,
    rows: list[dict],
    index_cache: dict[str, int],
) -> list[tuple[PreparedItem, Exception | None]]:
    """Apply a claimed queue batch with one column-A read and batched writes."""
    tab = _escape_tab(sheet_tab())
    prepared: list[PreparedItem] = []
    prep_errors: list[tuple[PreparedItem, Exception]] = []

    for row in rows:
        qid = int(row["queue_id"])
        hub_key = (row["hub_reference_key"] or "").strip()
        payload_raw = row["payload"] or "{}"
        try:
            payload = parse_payload(
                payload_raw if isinstance(payload_raw, str) else str(payload_raw)
            )
            op = (payload.get("op") or "update").strip().lower()
            row_data = None
            if op != "delete":
                row_data = fetch_row(engine, hub_key)
                if row_data is None:
                    raise ValueError(f"ESL row not found in database: {hub_key}")
            prepared.append(
                PreparedItem(queue_id=qid, hub_key=hub_key, op=op, row_data=row_data)
            )
        except Exception as e:
            prep_errors.append(
                (PreparedItem(queue_id=qid, hub_key=hub_key, op="error"), e)
            )

    results: list[tuple[PreparedItem, Exception | None]] = list(prep_errors)
    if not prepared:
        return results

    batch_data: list[dict[str, Any]] = []
    override_data: list[dict[str, Any]] = []
    append_values: list[list[str]] = []
    append_items: list[PreparedItem] = []

    for item in prepared:
        if item.op == "delete":
            row_num = index_cache.get(item.hub_key)
            if row_num is not None:
                batch_data.append(
                    {
                        "range": f"{tab}!A{row_num}:{LAST_COL}{row_num}",
                        "values": _BLANK_ROW,
                    }
                )
                override_data.append(_override_receipt_batch_data(tab, row_num, None))
            continue

        assert item.row_data is not None
        values = [_row_values(item.row_data)]
        row_num = index_cache.get(item.hub_key)
        if row_num is None:
            append_values.extend(values)
            append_items.append(item)
        else:
            batch_data.append(
                {
                    "range": f"{tab}!A{row_num}:{LAST_COL}{row_num}",
                    "values": values,
                }
            )
            override_data.append(
                _override_receipt_batch_data(tab, row_num, item.row_data)
            )

    try:
        _batch_values_update(service, batch_data)
        if append_values:
            sid = sheet_id()
            sheet_tab_name = sheet_tab()
            append_rng = f"{_escape_tab(sheet_tab_name)}!A:{LAST_COL}"
            result = _execute_with_retry(
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sid,
                    range=append_rng,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": append_values},
                )
                .execute(),
                what=f"append {len(append_values)} row(s)",
            )
            updated_range = (result.get("updates") or {}).get("updatedRange") or ""
            start_row = _first_row_from_updated_range(updated_range)
            for offset, item in enumerate(append_items):
                row_num = start_row + offset
                index_cache[item.hub_key] = row_num
                assert item.row_data is not None
                override_data.append(
                    _override_receipt_batch_data(tab, row_num, item.row_data)
                )

        _batch_override_receipt_update(
            service,
            override_data,
            what=f"override receipt {len(override_data)} cell(s)",
        )

        results.extend((item, None) for item in prepared)
    except Exception as e:
        results.extend((item, e) for item in prepared)

    return results


def upsert_row(service, engine, hub_key: str, index_cache: dict[str, int] | None = None) -> None:
    row = fetch_row(engine, hub_key)
    if row is None:
        raise ValueError(f"ESL row not found in database: {hub_key}")

    cache = index_cache if index_cache is not None else col_a_index(service)
    tab = _escape_tab(sheet_tab())
    row_num = cache.get(hub_key)
    values = [_row_values(row)]
    if row_num is None:
        sid = sheet_id()
        append_rng = f"{tab}!A:{LAST_COL}"
        result = _execute_with_retry(
            lambda: service.spreadsheets()
            .values()
            .append(
                spreadsheetId=sid,
                range=append_rng,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute(),
            what=f"append {hub_key}",
        )
        updated_range = (result.get("updates") or {}).get("updatedRange") or ""
        row_num = _first_row_from_updated_range(updated_range)
        cache[hub_key] = row_num
        _batch_override_receipt_update(
            service,
            [_override_receipt_batch_data(tab, row_num, row)],
            what=f"override receipt {hub_key}",
        )
        return

    _batch_values_update(
        service,
        [{"range": f"{tab}!A{row_num}:{LAST_COL}{row_num}", "values": values}],
    )
    _batch_override_receipt_update(
        service,
        [_override_receipt_batch_data(tab, row_num, row)],
        what=f"override receipt {hub_key}",
    )


def delete_row(service, hub_key: str, index_cache: dict[str, int] | None = None) -> None:
    cache = index_cache if index_cache is not None else col_a_index(service)
    row_num = cache.get(hub_key)
    if row_num is None:
        return
    tab = _escape_tab(sheet_tab())
    _batch_values_update(
        service,
        [{"range": f"{tab}!A{row_num}:{LAST_COL}{row_num}", "values": _BLANK_ROW}],
    )
    _batch_override_receipt_update(
        service,
        [_override_receipt_batch_data(tab, row_num, None)],
        what=f"clear override receipt {hub_key}",
    )


def bootstrap_all(engine, service) -> int:
    ensure_tab_and_headers(service)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                _SHEET_ROW_SELECT
                + """
                ORDER BY v.[date] DESC, v.esl_reference_key DESC
                """
            )
        ).mappings().all()

    values = [_row_values(dict(r)) for r in rows]
    if not values:
        return 0

    ensure_grid_rows(service, len(values) + 1)

    sid = sheet_id()
    tab = sheet_tab()
    tab_escaped = _escape_tab(tab)
    chunk = int(os.environ.get("EXPENSE_SHEET_BOOTSTRAP_CHUNK", "500"))
    start_row = 2
    for i in range(0, len(values), chunk):
        block = values[i : i + chunk]
        row_dicts = [dict(r) for r in rows[i : i + chunk]]
        row_start = start_row + i
        row_end = row_start + len(block) - 1
        rng = f"{tab_escaped}!A{row_start}:{LAST_COL}{row_end}"
        _execute_with_retry(
            lambda block=block, rng=rng: service.spreadsheets()
            .values()
            .update(
                spreadsheetId=sid,
                range=rng,
                valueInputOption="RAW",
                body={"values": block},
            )
            .execute(),
            what=f"bootstrap chunk rows {row_start}-{row_end}",
        )
        override_data = [
            _override_receipt_batch_data(tab_escaped, row_start + offset, row_dict)
            for offset, row_dict in enumerate(row_dicts)
        ]
        _batch_override_receipt_update(
            service,
            override_data,
            what=f"bootstrap override rows {row_start}-{row_end}",
        )
    return len(values)


def parse_payload(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid queue payload JSON: {e}") from e
