"""Scoped find/replace on root display columns when SQL reference labels change."""
from __future__ import annotations

import os
from dataclasses import dataclass

from googleapiclient.errors import HttpError

from config import root_tab, sheet_id
from sheets_write import _execute_with_retry

# root tab columns (0-based): G tribe, H state abbrev, I casino, J expense account
ROOT_COL_TRIBE = 6
ROOT_COL_STATE = 7
ROOT_COL_CASINO = 8

_ROOT_SHEET_ID: int | None = None


@dataclass(frozen=True)
class LabelReplace:
    column_index: int
    old: str
    new: str


def _root_sheet_id(service) -> int:
    global _ROOT_SHEET_ID
    raw = (os.environ.get("EXPENSE_SHEET_ROOT_SHEET_ID") or "").strip()
    if raw:
        return int(raw)
    if _ROOT_SHEET_ID is not None:
        return _ROOT_SHEET_ID
    tab = root_tab()
    meta = _execute_with_retry(
        lambda: service.spreadsheets()
        .get(spreadsheetId=sheet_id(), fields="sheets.properties")
        .execute(),
        what="read sheet metadata",
    )
    for s in meta.get("sheets", []):
        props = s["properties"]
        if props["title"] == tab:
            _ROOT_SHEET_ID = int(props["sheetId"])
            return _ROOT_SHEET_ID
    raise SystemExit(f"root tab {tab!r} not found on spreadsheet")


def collect_renames(
    changed: set[str],
    previous: dict[str, tuple[str, ...]],
    current: dict[str, tuple[str, ...]],
    *,
    column_index: int,
    label_index: int,
) -> list[LabelReplace]:
    """Build find/replace pairs when a reference row's display label changed."""
    out: list[LabelReplace] = []
    for key in changed:
        if key not in current or key not in previous:
            continue
        prev_row = previous[key]
        cur_row = current[key]
        if label_index >= len(prev_row) or label_index >= len(cur_row):
            continue
        old = (prev_row[label_index] or "").strip()
        new = (cur_row[label_index] or "").strip()
        if old and new and old != new:
            out.append(LabelReplace(column_index=column_index, old=old, new=new))
    return out


def apply_root_label_replaces(service, replaces: list[LabelReplace]) -> list[str]:
    """One spreadsheets.batchUpdate with findReplace per label change (scoped column)."""
    if not replaces:
        return []

    sid_num = _root_sheet_id(service)
    sid = sheet_id()
    requests = [
        {
            "findReplace": {
                "find": r.old,
                "replacement": r.new,
                "matchCase": True,
                "matchEntireCell": True,
                "searchByRegex": False,
                "includeFormulas": False,
                "range": {
                    "sheetId": sid_num,
                    "startRowIndex": 1,
                    "startColumnIndex": r.column_index,
                    "endColumnIndex": r.column_index + 1,
                },
            }
        }
        for r in replaces
    ]

    def _do():
        return (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=sid, body={"requests": requests})
            .execute()
        )

    resp = _execute_with_retry(_do, what=f"root findReplace x{len(replaces)}")
    logs: list[str] = []
    for r, rep in zip(replaces, resp.get("replies", [])):
        n = int((rep.get("findReplace") or {}).get("occurrencesChanged") or 0)
        col_letter = chr(ord("A") + r.column_index)
        logs.append(f"root!{col_letter}: {r.old!r} -> {r.new!r} ({n} cell(s))")
    return logs
