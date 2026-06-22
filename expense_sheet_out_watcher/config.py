"""Load MSSQL + Google credentials for expense sheet outbound watcher."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_WATCHER_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _WATCHER_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.usb_env_dotenv import MASTER_DOTENV_FIRST_WIN_RAW as _DEFAULT_MASTER_PATHS

_LOCAL_ENV = _WATCHER_DIR / ".env"


def load_env() -> None:
    env_override = (os.environ.get("MASTER_CREDENTIALS_ENV") or "").strip()
    loaded_master = False
    if env_override:
        p = Path(env_override)
        if p.is_file():
            load_dotenv(p, override=False)
            loaded_master = True
    if not loaded_master:
        for raw in _DEFAULT_MASTER_PATHS:
            p = Path(raw)
            if p.is_file():
                load_dotenv(p, override=False)
                break
    repo_env = _REPO_ROOT / ".env"
    if repo_env.is_file():
        load_dotenv(repo_env, override=True)
    if _LOCAL_ENV.is_file():
        load_dotenv(_LOCAL_ENV, override=True)


def sheet_id() -> str:
    sid = (
        os.environ.get("EXPENSE_SHEET_ID")
        or "1cfdOzzAtiQYVLSaFtiZLYLKcqyD07ANkIsgEV5lGqXM"
    ).strip()
    if not sid:
        raise SystemExit("EXPENSE_SHEET_ID is required")
    return sid


def sheet_tab() -> str:
    return (os.environ.get("EXPENSE_SHEET_TAB") or "root").strip()


def google_scopes() -> list[str]:
    return ["https://www.googleapis.com/auth/spreadsheets"]
