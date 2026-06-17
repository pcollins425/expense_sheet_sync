#!/usr/bin/env python3
"""
Poll SQL reference tables → push validation tabs → find/replace on root when labels change.

Sources (SQL → Sheet only):
  clients.states   → States   → root column H (state abbrev) on rename
  clients.tribes   → Tribes   → root column G (tribe name) on rename
  clients.casinos  → Casinos  → root column I (casino name) on rename

account_select is supervisor-owned on the sheet (not synced from SQL).

  python -u run.py
  python -u run.py --once
  python -u run.py --bootstrap   # seed States/Tribes/Casinos from SQL
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from config import load_env
from db import get_engine
from google_creds import sheets_service
from poll import poll_all
from sheets_write import batch_write_tabs
from snapshot import save_snapshot
from sql_fetch import fetch_casinos, fetch_states, fetch_tribes


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_env(key: str, default: float) -> float:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else float(raw)


def bootstrap(engine, service) -> None:
    jobs = [
        ("States", fetch_states, "sql_states"),
        ("Tribes", fetch_tribes, "sql_tribes"),
        ("Casinos", fetch_casinos, "sql_casinos"),
    ]
    batch: dict[str, list[list[str]]] = {}
    for tab, fn, snap in jobs:
        values, index = fn(engine)
        batch[tab] = values
        save_snapshot(snap, {"rows": index})
        print(f"{_utc()} bootstrap {tab}: {len(values) - 1} row(s)")

    batch_write_tabs(service, batch)
    print(f"{_utc()} bootstrap complete ({len(batch)} tab(s), 1 batch write)")


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="SQL → Sheet reference tab watcher")
    p.add_argument("--once", action="store_true")
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Write States/Tribes/Casinos from SQL and seed snapshots",
    )
    args = p.parse_args()

    poll_sec = _float_env("EXPENSE_SHEET_REF_POLL_SECONDS", 30.0)
    engine = get_engine()
    service = sheets_service()

    if args.bootstrap:
        bootstrap(engine, service)
        return

    print(
        f"{_utc()} expense_sheet_ref_watcher poll={poll_sec}s "
        f"SQL→Sheet: clients.states, clients.tribes, clients.casinos "
        f"(renames → root findReplace; no ESL queue fan-out)"
    )

    while True:
        try:
            logs = poll_all(engine, service)
            if logs:
                for line in logs:
                    print(f"{_utc()} {line}")
            elif args.once:
                print(f"{_utc()} no SQL reference changes")
            if args.once:
                break
            time.sleep(poll_sec)
        except KeyboardInterrupt:
            print(f"{_utc()} exiting")
            sys.exit(0)
        except Exception as e:
            print(f"{_utc()} error: {e}")
            print(traceback.format_exc())
            if args.once:
                sys.exit(1)
            backoff = _float_env("EXPENSE_SHEET_REF_ERROR_BACKOFF_SECONDS", 60.0)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
