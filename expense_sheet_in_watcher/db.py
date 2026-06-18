"""SQL connectivity for expense sheet inbound watcher."""
from __future__ import annotations

import os
import urllib.parse

from sqlalchemy import create_engine

from config import load_env


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def get_engine():
    load_env()
    server = _env("MSSQL_SERVER") or _env("MSSQL_HOST")
    port = _env("MSSQL_PORT") or "1433"
    user = _env("MSSQL_USER")
    password = os.environ.get("MSSQL_PASSWORD") or ""
    database = _env("MSSQL_DATABASE") or "dgs_application_db"
    if not server or not user or not password:
        raise SystemExit("Missing MSSQL_SERVER/MSSQL_HOST, MSSQL_USER, or MSSQL_PASSWORD")

    drv = (_env("QUEUE_SQL_DRIVER") or "").lower()
    if drv == "pymssql":
        pw = urllib.parse.quote_plus(password)
        u = urllib.parse.quote_plus(user)
        return create_engine(
            f"mssql+pymssql://{u}:{pw}@{server}:{port}/{database}?charset=utf8"
        )

    try:
        import pyodbc  # noqa: F401
    except ImportError:
        pw = urllib.parse.quote_plus(password)
        u = urllib.parse.quote_plus(user)
        return create_engine(
            f"mssql+pymssql://{u}:{pw}@{server}:{port}/{database}?charset=utf8"
        )

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password}"
    )
    params = urllib.parse.quote_plus(conn_str)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")
