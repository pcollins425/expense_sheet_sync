#!/usr/bin/env python3
"""
Poll SQL reference tables → push quickbooks_export validation tabs → enqueue ESL refresh.

Sources:
  clients.states   → States
  clients.tribes   → Tribes
  clients.casinos  → Casinos
  finance.expense_account_gl_display → account_select

  python -u run.py
  python -u run.py --once
  python -u run.py --bootstrap   # force full tab write from SQL (no fan-out)
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
from poll import poll_account_select, poll_casinos, poll_states, poll_tribes
from sheets_write import write_tab
from snapshot import save_snapshot
from sql_fetch import fetch_account_select, fetch_casinos, fetch_states, fetch_tribes


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
        ("account_select", fetch_account_select, "sql_account_select"),
    ]
    for tab, fn, snap in jobs:
        values, index = fn(engine)
        write_tab(service, tab, values)
        save_snapshot(snap, {"rows": index})
        print(f"{_utc()} bootstrap {tab}: {len(values) - 1} row(s)")
    print(f"{_utc()} bootstrap complete")


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="SQL → Sheet reference tab watcher")
    p.add_argument("--once", action="store_true")
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Write all reference tabs from SQL and seed snapshots",
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
        f"SQL→Sheet: clients.states, clients.tribes, clients.casinos, expense_account_gl_display"
    )

    while True:
        try:
            logs: list[str] = []
            logs.extend(poll_states(engine, service))
            logs.extend(poll_tribes(engine, service))
            logs.extend(poll_casinos(engine, service))
            logs.extend(poll_account_select(engine, service))
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
            time.sleep(min(poll_sec, 10.0))


if __name__ == "__main__":
    main()
