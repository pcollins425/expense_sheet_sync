"""Write reference tabs on Google Sheets (batched, 429-aware)."""
from __future__ import annotations

import os
import time

from googleapiclient.errors import HttpError

from config import sheet_id


def escape_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _retry_sleep(attempt: int) -> None:
    base = float(os.environ.get("EXPENSE_SHEET_REF_RETRY_SECONDS", "15"))
    time.sleep(base * (2**attempt))


def _execute_with_retry(fn, *, what: str):
    max_attempts = int(os.environ.get("EXPENSE_SHEET_REF_MAX_RETRIES", "6"))
    for attempt in range(max_attempts):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status == 429 and attempt < max_attempts - 1:
                wait = float(os.environ.get("EXPENSE_SHEET_REF_RETRY_SECONDS", "15")) * (
                    2**attempt
                )
                print(
                    f"Sheets 429 on {what}; retry {attempt + 1}/{max_attempts - 1} "
                    f"in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            raise


def write_tab(service, tab: str, values: list[list[str]], *, clear_first: bool = False) -> None:
    """Write one tab. Prefer batch_write_tabs when updating multiple tabs."""
    sid = sheet_id()

    def _do() -> None:
        if clear_first:
            service.spreadsheets().values().clear(
                spreadsheetId=sid,
                range=f"{escape_tab(tab)}!A:Z",
            ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"{escape_tab(tab)}!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

    _execute_with_retry(_do, what=f"write {tab}")


def batch_write_tabs(service, tabs: dict[str, list[list[str]]]) -> None:
    """One Sheets API call for all tab updates (counts as one write request)."""
    if not tabs:
        return
    sid = sheet_id()
    data = [
        {"range": f"{escape_tab(tab)}!A1", "values": values}
        for tab, values in tabs.items()
    ]

    def _do() -> None:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=sid,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

    _execute_with_retry(_do, what=f"batch write {len(tabs)} tab(s)")
