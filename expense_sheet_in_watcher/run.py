#!/usr/bin/env python3
"""
Poll finance.expense_sheet_in_queue → apply sheet edits to ESL / roots.

  python -u run.py
  python -u run.py --once
  python -u run.py --webhook-only
  python -u run.py --enqueue-json '{"source":"root",...}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import text

from apply import apply_payload
from config import load_env
from db import get_engine
from enqueue import enqueue_payload
from webhook import serve_webhook

CLAIM_SQL = """
;WITH picks AS (
    SELECT TOP (:n) queue_id
    FROM finance.expense_sheet_in_queue WITH (ROWLOCK, UPDLOCK, READPAST)
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
FROM finance.expense_sheet_in_queue AS q
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
                "DELETE FROM finance.expense_sheet_in_queue "
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
                UPDATE finance.expense_sheet_in_queue
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


def process_batch(engine, rows: list[dict], *, max_attempts: int) -> None:
    for row in rows:
        queue_id = int(row["queue_id"])
        hub_key = row["hub_reference_key"]
        payload = row["payload"]
        try:
            with engine.begin() as conn:
                apply_payload(conn, payload)
            delete_done(engine, queue_id)
            print(f"{_utc_stamp()} queue_id={queue_id} hub={hub_key!r} ok")
        except Exception as exc:
            backoff_fail(
                engine,
                queue_id,
                f"{type(exc).__name__}: {exc}",
                max_attempts,
            )
            print(f"{_utc_stamp()} queue_id={queue_id} hub={hub_key!r} FAILED: {exc}")
            print(traceback.format_exc())
            cd = _float_env("EXPENSE_SHEET_IN_FAIL_COOLDOWN_SECONDS", 5.0)
            if cd > 0:
                time.sleep(cd)


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="expense_sheet_in_queue → SQL apply")
    p.add_argument("--once", action="store_true", help="Process one batch then exit")
    p.add_argument("--webhook-only", action="store_true", help="Run HTTP enqueue server only")
    p.add_argument(
        "--enqueue-json",
        help="Enqueue one payload JSON (manual test) then exit unless --once loop also set",
    )
    args = p.parse_args()

    if args.enqueue_json:
        engine = get_engine()
        payload = json.loads(args.enqueue_json)
        with engine.begin() as conn:
            hub = enqueue_payload(conn, payload)
        print(f"{_utc_stamp()} enqueued hub={hub!r}")
        if not args.once and not args.webhook_only:
            return

    if args.webhook_only:
        serve_webhook(block=True)
        return

    poll = _float_env("EXPENSE_SHEET_IN_POLL_SECONDS", 15.0)
    batch = _int_env("EXPENSE_SHEET_IN_BATCH_SIZE", 20)
    max_attempts = _int_env("EXPENSE_SHEET_IN_MAX_ATTEMPTS", 10)
    webhook_enabled = (os.environ.get("EXPENSE_SHEET_INBOUND_WEBHOOK") or "1").strip() not in (
        "0",
        "false",
        "False",
    )

    engine = get_engine()
    if webhook_enabled:
        serve_webhook(block=False)

    print(
        f"{_utc_stamp()} expense_sheet_in_watcher poll={poll}s batch={batch} "
        f"max_attempts={max_attempts} webhook={webhook_enabled}"
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
            process_batch(engine, rows, max_attempts=max_attempts)
            if args.once:
                break
        except KeyboardInterrupt:
            print(f"{_utc_stamp()} exiting (KeyboardInterrupt)")
            sys.exit(0)
        except Exception as exc:
            print(f"{_utc_stamp()} loop error: {exc}")
            print(traceback.format_exc())
            if args.once:
                sys.exit(1)
            time.sleep(min(poll, 5.0))


if __name__ == "__main__":
    main()
