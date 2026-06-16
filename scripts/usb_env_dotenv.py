"""
Master credentials on USB: try **Windows E: / WSL `/mnt/e` first**, then **G: / `/mnt/g`** as fallback.

**Why both:** Work setups often expose the credential USB as **E:**. On the **personal (home)** machine,
the same USB frequently appears as **G:** while **E:** may hold something unrelated—see
`agents/knowledge/credential_management.md` (**Machine-specific WSL layouts**). Use **`MASTER_CREDENTIALS_ENV`**
when you want to force one path regardless of scans.

- **First existing path wins** — one-shot scripts, `work_order_sync`, watchers.
- **Merge order** — `load_master_env.py` loads every path that exists; **later overrides earlier**
  (so **G** overrides **E** when both `.env` files exist—explicit override scenario).
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# First hit wins: work-style paths first; G/mnt/g supports home when USB is not on E.
MASTER_DOTENV_FIRST_WIN_RAW: tuple[str, ...] = (
    "/mnt/e/master_credentials/.env",
    "E:/master_credentials/.env",
    r"E:\master_credentials\.env",
    "/mnt/g/master_credentials/.env",
    "G:/master_credentials/.env",
    r"G:\master_credentials\.env",
)

# All existing files are loaded in this order; later entries override (G after E).
MASTER_DOTENV_MERGE_ORDER_RAW: tuple[str, ...] = (
    "/mnt/e/master_credentials/.env",
    "E:/master_credentials/.env",
    r"E:\master_credentials\.env",
    "/mnt/g/master_credentials/.env",
    "G:/master_credentials/.env",
    r"G:\master_credentials\.env",
)

# Directories — same ordering as MASTER_DOTENV_FIRST_WIN (G after E fallback).
MASTER_CREDENTIALS_DIRS_FIRST_WIN: tuple[Path, ...] = (
    Path("/mnt/e/master_credentials"),
    Path("E:/master_credentials"),
    Path(r"E:\master_credentials"),
    Path("/mnt/g/master_credentials"),
    Path("G:/master_credentials"),
    Path(r"G:\master_credentials"),
)


def _is_env_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def load_usb_master_dotenv(*, override: bool = True) -> bool:
    """Load the first existing master_credentials .env from standard locations."""
    for raw in MASTER_DOTENV_FIRST_WIN_RAW:
        p = Path(raw)
        if _is_env_file(p):
            load_dotenv(p, override=override)
            return True
    return False


def resolve_first_master_credentials_dir() -> Path | None:
    """First directory that exists and contains a .env file (typical USB layout)."""
    for d in MASTER_CREDENTIALS_DIRS_FIRST_WIN:
        try:
            if d.is_dir() and _is_env_file(d / ".env"):
                return d
        except OSError:
            continue
    return None


def resolve_master_credentials_refresh_json(
    filename: str = "google-gmail-refresh.credentials.json",
) -> Path | None:
    """First existing Gmail refresh JSON under a standard master_credentials directory."""
    for d in MASTER_CREDENTIALS_DIRS_FIRST_WIN:
        p = d / filename
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None
