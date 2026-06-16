"""Write reference tabs on Google Sheets."""
from __future__ import annotations

from config import sheet_id


def escape_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def write_tab(service, tab: str, values: list[list[str]]) -> None:
    sid = sheet_id()
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
