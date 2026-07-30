#!/usr/bin/env python3
"""
Expense sheet alert watcher — reclaim stale processing + daily Resend digest.

  python -u run.py
  python -u run.py --once
  python -u run.py --daily-now   # send digest immediately (still idempotent per day)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from expense_sheet_common.alerts import (  # noqa: E402
    chicago_hour,
    chicago_today,
    reclaim_stale_processing,
    send_daily_digest,
    utc_stamp,
)
from expense_sheet_out_watcher.config import load_env  # noqa: E402
from expense_sheet_out_watcher.db import get_engine  # noqa: E402


def _int_env(key: str, default: int) -> int:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else int(raw)


def _float_env(key: str, default: float) -> float:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else float(raw)


def _state_path() -> Path:
    raw = (os.environ.get("EXPENSE_SHEET_ALERT_STATE_DIR") or "").strip()
    base = Path(raw) if raw else Path(__file__).resolve().parent.parent / "state" / "alerts"
    base.mkdir(parents=True, exist_ok=True)
    return base / "last_daily.txt"


def _read_last_daily() -> str:
    p = _state_path()
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _write_last_daily(day: str) -> None:
    _state_path().write_text(day + "\n", encoding="utf-8")


def reclaim_all(engine) -> tuple[int, int]:
    mins = _int_env("EXPENSE_SHEET_STALE_PROCESSING_MINUTES", 30)
    inn = reclaim_stale_processing(
        engine,
        table="finance.expense_sheet_in_queue",
        older_than_minutes=mins,
    )
    out = reclaim_stale_processing(
        engine,
        table="finance.expense_sheet_out_queue",
        older_than_minutes=mins,
    )
    return inn, out


def maybe_daily(engine, *, force: bool = False) -> bool:
    hour = _int_env("EXPENSE_SHEET_ALERT_DAILY_HOUR", 8)
    today = chicago_today()
    last = _read_last_daily()
    if not force:
        if last == today:
            return False
        if chicago_hour() < hour:
            return False
    rid = send_daily_digest(engine)
    _write_last_daily(today)
    print(f"{utc_stamp()} daily digest sent resend_id={rid} day={today}", flush=True)
    return True


def process_once(engine, *, force_daily: bool = False) -> None:
    inn, out = reclaim_all(engine)
    if inn or out:
        print(
            f"{utc_stamp()} reclaimed stale processing in={inn} out={out}",
            flush=True,
        )
    maybe_daily(engine, force=force_daily)


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daily-now", action="store_true", help="Send daily digest now")
    args = parser.parse_args()

    engine = get_engine()
    poll = _float_env("EXPENSE_SHEET_ALERT_POLL_SECONDS", 60.0)

    print(
        f"{utc_stamp()} expense_sheet_alert starting poll={poll}s "
        f"daily_hour={_int_env('EXPENSE_SHEET_ALERT_DAILY_HOUR', 8)} "
        f"stale_mins={_int_env('EXPENSE_SHEET_STALE_PROCESSING_MINUTES', 30)}",
        flush=True,
    )

    if args.once or args.daily_now:
        process_once(engine, force_daily=args.daily_now)
        return 0

    while True:
        try:
            process_once(engine, force_daily=False)
        except Exception:
            traceback.print_exc()
        time.sleep(poll)


if __name__ == "__main__":
    raise SystemExit(main())
