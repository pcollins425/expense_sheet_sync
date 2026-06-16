#!/usr/bin/env python3
"""
Poll finance.expense_sheet_out_queue → upsert/delete rows on Google Sheet.

Default: ``quickbooks_export`` spreadsheet tab ``root`` (override EXPENSE_SHEET_ID / EXPENSE_SHEET_TAB).

  python -u run.py
  python -u run.py --once
  python -u run.py --bootstrap   # full refresh from finance.vw_expense_supervisor_sheet
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import text

from config import load_env, sheet_id, sheet_tab
from db import get_engine
from google_creds import sheets_service
from sheets_publish import (
    bootstrap_all,
    delete_row,
    ensure_tab_and_headers,
    parse_payload,
    upsert_row,
)

CLAIM_SQL = """
;WITH picks AS (
    SELECT TOP (:n) queue_id
    FROM finance.expense_sheet_out_queue WITH (ROWLOCK, UPDLOCK, READPAST)
    WHERE status = N'pending'
    ORDER BY queue_id
)
UPDATE q
SET
    status = N'processing',
    updated_at = SYSUTCDATETIME()
OUTPUT
    inserted.queue_id,
    inserted.hub_reference_key,
    inserted.payload,
    inserted.attempt_count
FROM finance.expense_sheet_out_queue AS q
INNER JOIN picks AS p ON p.queue_id = q.queue_id;
"""


def _int_env(key: str, default: int) -> int:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else int(raw)


def _float_env(key: str, default: float) -> float:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else float(raw)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claim_batch(engine, batch_size: int) -> list[dict]:
    with engine.begin() as conn:
        r = conn.execute(text(CLAIM_SQL), {"n": batch_size})
        return [dict(row._mapping) for row in r]


def delete_done(engine, queue_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM finance.expense_sheet_out_queue "
                "WHERE queue_id = :q AND status = N'processing'"
            ),
            {"q": queue_id},
        )


def backoff_fail(engine, queue_id: int, err: str, max_attempts: int) -> None:
    truncated = err[:3890]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE finance.expense_sheet_out_queue
                SET
                    updated_at = SYSUTCDATETIME(),
                    last_error = :last_err,
                    attempt_count = attempt_count + 1,
                    status = CASE
                        WHEN attempt_count + 1 >= :mx THEN N'dead'
                        ELSE N'pending'
                    END
                WHERE queue_id = :q
                  AND status = N'processing'
                """
            ),
            {"q": queue_id, "last_err": truncated, "mx": max_attempts},
        )


def process_one(engine, service, row: dict, *, max_attempts: int, index_cache: dict) -> None:
    qid = int(row["queue_id"])
    hub_key = (row["hub_reference_key"] or "").strip()
    payload_raw = row["payload"] or "{}"
    try:
        payload = parse_payload(payload_raw if isinstance(payload_raw, str) else str(payload_raw))
        op = (payload.get("op") or "update").strip().lower()
        if op == "delete":
            delete_row(service, hub_key, index_cache=index_cache)
        else:
            upsert_row(service, engine, hub_key, index_cache=index_cache)
        delete_done(engine, qid)
        print(f"{_utc_stamp()} queue_id={qid} hub={hub_key!r} op={op} ok")
    except Exception as e:
        backoff_fail(engine, qid, f"{type(e).__name__}: {e}", max_attempts)
        print(f"{_utc_stamp()} queue_id={qid} hub={hub_key!r} FAILED: {e}")
        print(traceback.format_exc())
        cd = _float_env("EXPENSE_SHEET_FAIL_COOLDOWN_SECONDS", 5.0)
        if cd > 0:
            time.sleep(cd)


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="expense_sheet_out_queue → Google Sheets")
    p.add_argument("--once", action="store_true", help="Process one batch then exit")
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Full sheet refresh from vw_expense_supervisor_sheet (ignores queue)",
    )
    args = p.parse_args()

    poll = _float_env("EXPENSE_SHEET_POLL_SECONDS", 15.0)
    batch = _int_env("EXPENSE_SHEET_BATCH_SIZE", 20)
    max_attempts = _int_env("EXPENSE_SHEET_MAX_ATTEMPTS", 10)

    engine = get_engine()
    service = sheets_service()
    ensure_tab_and_headers(service)

    if args.bootstrap:
        n = bootstrap_all(engine, service)
        print(
            f"{_utc_stamp()} bootstrap complete: {n} rows → "
            f"sheet={sheet_id()} tab={sheet_tab()!r}"
        )
        return

    print(
        f"{_utc_stamp()} expense_sheet_out_watcher poll={poll}s batch={batch} "
        f"sheet={sheet_id()} tab={sheet_tab()!r} max_attempts={max_attempts}"
    )

    while True:
        try:
            rows = claim_batch(engine, batch)
            if not rows:
                if args.once:
                    break
                time.sleep(poll)
                continue
            print(f"{_utc_stamp()} claimed {len(rows)} row(s)")
            for row in rows:
                process_one(
                    engine,
                    service,
                    row,
                    max_attempts=max_attempts,
                    index_cache=None,
                )
            if args.once:
                break
        except KeyboardInterrupt:
            print(f"{_utc_stamp()} exiting (KeyboardInterrupt)")
            sys.exit(0)
        except Exception as e:
            print(f"{_utc_stamp()} loop error: {e}")
            print(traceback.format_exc())
            if args.once:
                sys.exit(1)
            time.sleep(min(poll, 5.0))


if __name__ == "__main__":
    main()
