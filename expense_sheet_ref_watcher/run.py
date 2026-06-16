#!/usr/bin/env python3
"""
Poll quickbooks_export reference tabs → SQL catalog / clients.* → enqueue ESL sheet refresh.

Tabs: account_select, States, Tribes, Casinos, and Expense Account column on root.

  python -u run.py
  python -u run.py --once
  python -u run.py --seed-snapshots   # baseline without applying changes
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from config import load_env, root_tab
from db import get_engine
from google_creds import sheets_service
from poll import (
    poll_account_select,
    poll_casinos,
    poll_root_expense_accounts,
    poll_states,
    poll_tribes,
)
from sheets_io import parse_gl_account_label, read_tab, root_expense_map
from snapshot import save_snapshot


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_env(key: str, default: float) -> float:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else float(raw)


def seed_snapshots(service, tab_root: str) -> None:
    # account_select
    rows = read_tab(service, "account_select", "A:A")
    acct: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        if not row:
            continue
        parsed = parse_gl_account_label(row[0])
        if not parsed:
            continue
        code, name = parsed
        acct[code] = {"gl_code": code, "display_name": name, "account_label": row[0]}
    save_snapshot("account_select", {"rows": acct})

    for tab, key in [("States", "reference_key"), ("Tribes", "reference_key"), ("Casinos", "reference_key")]:
        data = read_tab(service, tab)
        if not data:
            save_snapshot(tab, {"rows": {}})
            continue
        headers = data[0]
        out: dict[str, dict[str, str]] = {}
        for row in data[1:]:
            d = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
            k = d.get(key, "").strip()
            if k:
                out[k] = d
        save_snapshot(tab, {"rows": out})

    root_rows = read_tab(service, tab_root, "A:K")
    save_snapshot("root_expense", {"rows": root_expense_map(root_rows)})
    print(f"{_utc()} seeded reference snapshots")


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="Reference tab sheet watcher")
    p.add_argument("--once", action="store_true")
    p.add_argument(
        "--seed-snapshots",
        action="store_true",
        help="Save current sheet state as baseline (no SQL writes)",
    )
    args = p.parse_args()

    poll_sec = _float_env("EXPENSE_SHEET_REF_POLL_SECONDS", 30.0)
    engine = get_engine()
    service = sheets_service()
    tab_root = root_tab()

    if args.seed_snapshots:
        seed_snapshots(service, tab_root)
        return

    print(
        f"{_utc()} expense_sheet_ref_watcher poll={poll_sec}s "
        f"tabs=account_select,States,Tribes,Casinos,root:{tab_root!r}"
    )

    while True:
        try:
            logs: list[str] = []
            logs.extend(poll_account_select(engine, service))
            logs.extend(poll_states(engine, service))
            logs.extend(poll_tribes(engine, service))
            logs.extend(poll_casinos(engine, service))
            logs.extend(poll_root_expense_accounts(engine, service, tab_root))
            if logs:
                for line in logs:
                    print(f"{_utc()} {line}")
            elif args.once:
                print(f"{_utc()} no reference changes")
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
