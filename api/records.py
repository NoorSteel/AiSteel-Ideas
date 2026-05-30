"""
Vercel Serverless Function – /api/records
Fetches all records from the Google Sheet and returns them as JSON.
Credentials are loaded from the GOOGLE_CREDENTIALS_JSON environment variable
(set this in Vercel → Project → Settings → Environment Variables).
"""
from __future__ import annotations

import base64
import json
import os

# ── Try loading gspread/google-auth (available on Vercel via requirements.txt) ──
try:
    import gspread
    from google.oauth2.service_account import Credentials
    _GSPREAD_OK = True
except ImportError:
    _GSPREAD_OK = False

# ── Vercel Python runtime expects a BaseHTTPRequestHandler subclass named "handler" ──
from http.server import BaseHTTPRequestHandler

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
)
SHEET_NAME = "AllData"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_credentials() -> dict:
    """
    Load Google service-account credentials from environment.
    Set the env-var GOOGLE_CREDENTIALS_JSON in Vercel dashboard
    with the full JSON content of credentials.json.
    """
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not raw:
        raise EnvironmentError(
            "Environment variable GOOGLE_CREDENTIALS_JSON is not set. "
            "Add it in Vercel → Project → Settings → Environment Variables."
        )
    # Accept both plain JSON and base64-encoded JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(base64.b64decode(raw).decode())


def _fetch_records() -> list[dict]:
    if not _GSPREAD_OK:
        raise ImportError("gspread or google-auth is not installed.")
    creds_info = _load_credentials()
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
    return sheet.get_all_records()


class handler(BaseHTTPRequestHandler):
    """Vercel serverless handler for GET /api/records"""

    def do_GET(self):  # noqa: N802
        try:
            records = _fetch_records()
            body = json.dumps(records, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            error_body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)

    def log_message(self, *args):  # suppress default access log noise
        pass
