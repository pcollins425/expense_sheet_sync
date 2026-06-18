"""Enqueue inbound payloads from webhook or CLI."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


def enqueue_payload(conn, payload: dict[str, Any]) -> str:
    payload_raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    conn.execute(
        text("EXEC finance.usp_enqueue_expense_sheet_in @payload = :payload"),
        {"payload": payload_raw},
    )
    source = (payload.get("source") or "root").strip()
    if source == "root":
        hub = payload.get("hub_reference_key")
        if not hub:
            raise ValueError("root payload requires hub_reference_key")
        return str(hub)
    gl_code = payload.get("gl_code")
    if not gl_code and payload.get("full_label"):
        from apply import _parse_account_select_label

        gl_code, _ = _parse_account_select_label(str(payload["full_label"]))
    if not gl_code:
        raise ValueError("account_select payload requires gl_code")
    return f"GL-{gl_code}"
