"""Google Sheets OAuth from master .env refresh token."""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import google_scopes, load_env


def _credentials() -> Credentials:
    load_env()
    refresh = (os.environ.get("GMAIL_REFRESH_TOKEN") or "").strip()
    client_id = (os.environ.get("GMAIL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GMAIL_CLIENT_SECRET") or "").strip()
    token_uri = (os.environ.get("GMAIL_TOKEN_URI") or "https://oauth2.googleapis.com/token").strip()

    if refresh and client_id and client_secret:
        creds = Credentials(
            token=None,
            refresh_token=refresh,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=google_scopes(),
        )
        creds.refresh(Request())
        return creds

    explicit = (os.environ.get("GOOGLE_REFRESH_JSON") or "").strip()
    paths = []
    if explicit:
        paths.append(Path(explicit))
    paths.extend(
        Path(p) / "google-gmail-refresh.credentials.json"
        for p in (
            "/app/secrets",
            "/mnt/e/master_credentials",
            "/mnt/g/master_credentials",
        )
    )
    for path in paths:
        if path.is_file():
            data = json.loads(path.read_text())
            creds = Credentials(
                token=None,
                refresh_token=data["refresh_token"],
                token_uri=data.get("token_uri", token_uri),
                client_id=data["client_id"],
                client_secret=data["client_secret"],
                scopes=google_scopes(),
            )
            creds.refresh(Request())
            return creds

    raise SystemExit(
        "Google credentials missing: set GMAIL_REFRESH_TOKEN + GMAIL_CLIENT_ID + "
        "GMAIL_CLIENT_SECRET in secrets/.env"
    )


def sheets_service():
    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False)
