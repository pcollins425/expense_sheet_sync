"""Apply inbound queue payloads to SQL."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text

_GL_ROW_RE = re.compile(r"^(\d{4})\s+(.*)$", re.DOTALL)


def _parse_account_select_label(raw: str) -> tuple[str, str]:
    text_val = (raw or "").strip()
    if not text_val or text_val.lower() == "expense account":
        raise ValueError("empty account_select row")
    m = _GL_ROW_RE.match(text_val)
    if not m:
        raise ValueError(f"account_select label does not match GL pattern: {text_val!r}")
    code, name = m.group(1), m.group(2).strip()
    if not name:
        raise ValueError(f"account_select missing display name for {code}")
    return code, name


def apply_payload(conn, payload_raw: str) -> None:
    payload: dict[str, Any] = json.loads(payload_raw)
    source = (payload.get("source") or "root").strip()

    if source == "account_select":
        gl_code = (payload.get("gl_code") or "").strip()
        display_name = (payload.get("display_name") or "").strip()
        if not gl_code or not display_name:
            full_label = (payload.get("full_label") or "").strip()
            if full_label:
                gl_code, display_name = _parse_account_select_label(full_label)
        if not gl_code or not display_name:
            raise ValueError("account_select payload requires gl_code + display_name")
        conn.execute(
            text(
                "EXEC finance.usp_apply_expense_account_select_inbound "
                "@gl_code = :code, @display_name = :name"
            ),
            {"code": gl_code, "name": display_name},
        )
        return

    if source != "root":
        raise ValueError(f"unknown inbound source: {source!r}")

    conn.execute(
        text("EXEC finance.usp_apply_expense_sheet_inbound @payload = :payload"),
        {"payload": payload_raw},
    )
