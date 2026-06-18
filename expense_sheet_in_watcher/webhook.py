"""HTTP webhook: Apps Script → finance.expense_sheet_in_queue."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from config import load_env
from db import get_engine
from enqueue import enqueue_payload


def _secret() -> str:
    return (os.environ.get("EXPENSE_SHEET_INBOUND_SECRET") or "").strip()


def _int_env(key: str, default: int) -> int:
    raw = (os.environ.get(key) or "").strip()
    return default if raw == "" else int(raw)


def _authorized(headers) -> bool:
    secret = _secret()
    if not secret:
        return False
    auth = (headers.get("Authorization") or "").strip()
    if auth == f"Bearer {secret}":
        return True
    header = (headers.get("X-Expense-Sheet-Secret") or "").strip()
    return header == secret


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class InboundHandler(BaseHTTPRequestHandler):
    server_version = "expense-sheet-inbound/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"inbound_webhook {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/health", "/api/expense-sheet/inbound/health"):
            _json_response(self, 200, {"ok": True})
            return
        _json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/inbound", "/api/expense-sheet/inbound"):
            _json_response(self, 404, {"ok": False, "error": "not found"})
            return

        if not _authorized(self.headers):
            _json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return

        try:
            body = _read_json(self)
            items = body.get("items")
            if items is None:
                items = [body]
            if not isinstance(items, list) or not items:
                raise ValueError("payload requires an object or non-empty items[]")

            engine = get_engine()
            keys: list[str] = []
            with engine.begin() as conn:
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("each items[] entry must be an object")
                    keys.append(enqueue_payload(conn, item))

            _json_response(
                self,
                202,
                {"ok": True, "queued": len(keys), "hub_reference_keys": keys},
            )
        except Exception as exc:
            _json_response(self, 400, {"ok": False, "error": str(exc)})


def serve_webhook(block: bool = True) -> ThreadingHTTPServer | None:
    load_env()
    if not _secret():
        raise SystemExit("EXPENSE_SHEET_INBOUND_SECRET is required for webhook")

    host = (os.environ.get("EXPENSE_SHEET_INBOUND_HOST") or "0.0.0.0").strip()
    port = _int_env("EXPENSE_SHEET_INBOUND_PORT", 9020)
    httpd = ThreadingHTTPServer((host, port), InboundHandler)
    print(f"inbound_webhook listening on http://{host}:{port}")

    if block:
        httpd.serve_forever()
        return None

    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="inbound-webhook")
    thread.start()
    return httpd
