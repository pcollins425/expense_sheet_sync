"""
Expense sheet sync alerts — Resend event + shared health helpers.

Used by in/out watchers (dead events) and expense-sheet-alert-watcher (daily + reclaim).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_TO = "paulc@dynamicgamingsolutions.com"
DEFAULT_FROM = "DGS Expense Sheet Sync <noreply@collinsmediallc.com>"


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def alerts_enabled() -> bool:
    raw = _env("EXPENSE_SHEET_ALERTS", "1").lower()
    return raw not in ("0", "false", "no", "off")


def alert_to() -> str:
    return _env("EXPENSE_SHEET_ALERT_TO", DEFAULT_TO)


def send_resend(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    idempotency_key: str,
) -> str:
    api_key = _env("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is required for sheet sync alerts")

    from_address = (
        _env("EXPENSE_SHEET_ALERT_FROM")
        or _env("RESEND_FROM")
        or DEFAULT_FROM
    )
    payload = json.dumps(
        {
            "from": from_address,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        RESEND_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key[:256],
            "User-Agent": "dgs-expense-sheet-sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Resend HTTP {exc.code}: {body}") from exc
    resend_id = str(result.get("id") or "").strip()
    if not resend_id:
        raise RuntimeError(f"Resend returned no email id: {result!r}")
    return resend_id


def notify_queue_dead(
    *,
    direction: str,
    queue_id: int,
    hub_key: str | None,
    attempt_count: int,
    last_error: str,
) -> None:
    """Fire-and-forget style: caller should catch/log failures."""
    if not alerts_enabled():
        return
    to = alert_to()
    if not to:
        return
    hub = hub_key or "(none)"
    err = (last_error or "").strip() or "(no error text)"
    subject = f"[Expense sheet sync] {direction} queue dead #{queue_id} {hub}"
    text_body = (
        f"Expense sheet sync item went dead and will not retry.\n\n"
        f"Direction: {direction}\n"
        f"Queue id: {queue_id}\n"
        f"Hub key: {hub}\n"
        f"Attempts: {attempt_count}\n"
        f"Error:\n{err}\n"
    )
    html = (
        f"<p><b>Expense sheet sync</b> — {direction} queue item is <b>dead</b>.</p>"
        f"<ul>"
        f"<li>Queue id: {queue_id}</li>"
        f"<li>Hub: <code>{hub}</code></li>"
        f"<li>Attempts: {attempt_count}</li>"
        f"</ul>"
        f"<pre>{err[:3500]}</pre>"
    )
    send_resend(
        to=to,
        subject=subject,
        html=html,
        text=text_body,
        idempotency_key=f"expense-sheet-dead-{direction}-{queue_id}",
    )


def reclaim_stale_processing(
    engine,
    *,
    table: str,
    older_than_minutes: int,
) -> int:
    """Return abandoned processing rows to pending so they can retry."""
    if older_than_minutes <= 0:
        return 0
    if table not in (
        "finance.expense_sheet_in_queue",
        "finance.expense_sheet_out_queue",
    ):
        raise ValueError(f"unexpected table {table}")
    sql = f"""
    UPDATE {table}
    SET
        status = N'pending',
        updated_at = SYSUTCDATETIME(),
        last_error = COALESCE(last_error + N'; ', N'')
            + N'reclaimed from stale processing by alert watcher'
    WHERE status = N'processing'
      AND updated_at < DATEADD(minute, :mins_neg, SYSUTCDATETIME())
    """
    with engine.begin() as conn:
        r = conn.execute(text(sql), {"mins_neg": -int(older_than_minutes)})
        return int(r.rowcount or 0)


def queue_health(engine) -> dict[str, Any]:
    def _counts(table: str) -> dict[str, int]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT status, COUNT(*) AS n
                    FROM {table}
                    GROUP BY status
                    """
                )
            ).mappings().all()
        out = {"pending": 0, "processing": 0, "dead": 0}
        for row in rows:
            st = str(row["status"] or "").lower()
            out[st] = int(row["n"] or 0)
        return out

    def _stale(table: str, mins: int) -> int:
        with engine.connect() as conn:
            n = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS n
                    FROM {table}
                    WHERE status = N'processing'
                      AND updated_at < DATEADD(minute, :mins_neg, SYSUTCDATETIME())
                    """
                ),
                {"mins_neg": -int(mins)},
            ).scalar()
        return int(n or 0)

    stale_mins = int(_env("EXPENSE_SHEET_STALE_PROCESSING_MINUTES", "30") or "30")
    return {
        "in": _counts("finance.expense_sheet_in_queue"),
        "out": _counts("finance.expense_sheet_out_queue"),
        "in_stale_processing": _stale("finance.expense_sheet_in_queue", stale_mins),
        "out_stale_processing": _stale("finance.expense_sheet_out_queue", stale_mins),
        "stale_minutes": stale_mins,
    }


def sample_dead(engine, table: str, limit: int = 8) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 50))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT TOP ({lim}) queue_id, hub_reference_key, attempt_count,
                       LEFT(COALESCE(last_error, N''), 180) AS last_error,
                       updated_at
                FROM {table}
                WHERE status = N'dead'
                ORDER BY updated_at DESC
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def send_daily_digest(engine) -> str | None:
    if not alerts_enabled():
        return None
    to = alert_to()
    if not to:
        return None

    health = queue_health(engine)
    in_q, out_q = health["in"], health["out"]
    subject = (
        "[Expense sheet sync] daily — "
        f"in dead={in_q['dead']} pending={in_q['pending']} | "
        f"out dead={out_q['dead']} pending={out_q['pending']}"
    )
    lines = [
        "Expense sheet sync — daily health",
        "",
        f"Inbound:  pending={in_q['pending']} processing={in_q['processing']} "
        f"dead={in_q['dead']} stale_processing={health['in_stale_processing']}",
        f"Outbound: pending={out_q['pending']} processing={out_q['processing']} "
        f"dead={out_q['dead']} stale_processing={health['out_stale_processing']}",
        f"(stale = processing older than {health['stale_minutes']} minutes)",
        "",
    ]
    for label, table in (
        ("Inbound dead samples", "finance.expense_sheet_in_queue"),
        ("Outbound dead samples", "finance.expense_sheet_out_queue"),
    ):
        samples = sample_dead(engine, table)
        lines.append(label + ":")
        if not samples:
            lines.append("  (none)")
        for s in samples:
            lines.append(
                f"  #{s['queue_id']} {s.get('hub_reference_key')} "
                f"attempts={s.get('attempt_count')} err={s.get('last_error')}"
            )
        lines.append("")

    text_body = "\n".join(lines)
    html = "<pre>" + text_body.replace("<", "&lt;") + "</pre>"
    tz = ZoneInfo(_env("TZ", "America/Chicago") or "America/Chicago")
    day = datetime.now(tz).strftime("%Y-%m-%d")
    return send_resend(
        to=to,
        subject=subject,
        html=html,
        text=text_body,
        idempotency_key=f"expense-sheet-daily-{day}",
    )


def chicago_today() -> str:
    tz = ZoneInfo(_env("TZ", "America/Chicago") or "America/Chicago")
    return datetime.now(tz).strftime("%Y-%m-%d")


def chicago_hour() -> int:
    tz = ZoneInfo(_env("TZ", "America/Chicago") or "America/Chicago")
    return datetime.now(tz).hour


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
