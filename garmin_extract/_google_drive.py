"""
Google Drive and Sheets helpers for Phase 5 export.

All functions are pure API calls with no Textual dependency — safe to call
from a worker thread. Credentials are loaded from .google_token.json (the
same token written by scripts/setup_gmail_auth.py).

State (folder_id, sheet_id, last_export) is persisted in .drive_config.json
at the project root so subsequent exports update the same resources.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
TOKEN_FILE = ROOT / ".google_token.json"
CREDENTIALS_FILE = ROOT / "google_credentials.json"
CONFIG_FILE = ROOT / ".drive_config.json"

REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
}

DAILY_CSV = ROOT / "reports" / "garmin_daily.csv"
ACTIVITIES_CSV = ROOT / "reports" / "garmin_activities.csv"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _load_credentials():
    """Return refreshed google.oauth2.credentials.Credentials, or raise."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_FILE.exists():
        raise FileNotFoundError("No OAuth token found — run Gmail OAuth setup first.")

    tok = json.loads(TOKEN_FILE.read_text())
    creds = Credentials(
        token=tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=tok.get("token_uri"),
        client_id=tok.get("client_id"),
        client_secret=tok.get("client_secret"),
        scopes=tok.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tok["token"] = creds.token
        TOKEN_FILE.write_text(json.dumps(tok, indent=2))

    return creds


def check_auth() -> tuple[str, str]:
    """Return (status, detail) — status is 'ok' | 'missing_scopes' | 'no_token' | 'error'."""
    if not TOKEN_FILE.exists():
        return "no_token", "No OAuth token — run Gmail OAuth setup first."

    try:
        tok = json.loads(TOKEN_FILE.read_text())
        token_scopes = set(tok.get("scopes") or [])
        missing = REQUIRED_SCOPES - token_scopes
        if missing:
            return (
                "missing_scopes",
                "Token lacks Drive/Sheets scopes — re-run Gmail OAuth setup to upgrade.",
            )
        creds = _load_credentials()
        if not creds.valid and not creds.refresh_token:
            return "error", "Token is expired and cannot be refreshed."
        return "ok", "Drive and Sheets access authorized."
    except Exception as exc:
        return "error", str(exc)


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    """Load .drive_config.json, returning {} if not found."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg: dict[str, Any]) -> None:
    """Write config dict to .drive_config.json."""
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------


def _drive_service(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sheets_service(creds):
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def get_or_create_folder(creds, name: str = "Garmin Extract") -> str:
    """Return the Drive folder ID for *name*, creating it if absent."""
    svc = _drive_service(creds)

    # Search for existing folder by name
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = svc.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create it
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    folder = svc.files().create(body=meta, fields="id").execute()
    return folder["id"]


def upload_csv(creds, csv_path: Path, folder_id: str) -> tuple[str, str]:
    """
    Upload *csv_path* to *folder_id*, updating in-place if it already exists.
    Returns (file_id, web_link).
    """
    from googleapiclient.http import MediaFileUpload

    svc = _drive_service(creds)
    name = csv_path.name
    mime = "text/csv"

    # Check if file already exists in folder
    q = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    results = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    existing = results.get("files", [])

    media = MediaFileUpload(str(csv_path), mimetype=mime, resumable=False)

    if existing:
        file_id = existing[0]["id"]
        svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        meta = {"name": name, "parents": [folder_id]}
        f = svc.files().create(body=meta, media_body=media, fields="id").execute()
        file_id = f["id"]

    # Make readable link
    link = f"https://drive.google.com/file/d/{file_id}/view"
    return file_id, link


def upload_csvs_to_drive() -> dict[str, Any]:
    """
    Upload garmin_daily.csv and garmin_activities.csv to Drive.
    Returns a result dict with keys: ok, folder_link, files, error.
    """
    missing = [p.name for p in (DAILY_CSV, ACTIVITIES_CSV) if not p.exists()]
    if missing:
        joined = ", ".join(missing)
        return {"ok": False, "error": f"CSVs not found: {joined}. Run 'Pull Data' first."}

    try:
        creds = _load_credentials()
        cfg = load_config()

        folder_id = cfg.get("folder_id") or get_or_create_folder(creds)
        cfg["folder_id"] = folder_id

        files = []
        for csv_path in (DAILY_CSV, ACTIVITIES_CSV):
            file_id, link = upload_csv(creds, csv_path, folder_id)
            files.append({"name": csv_path.name, "id": file_id, "link": link})

        cfg["last_export"] = datetime.now(timezone.utc).isoformat()
        save_config(cfg)

        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        return {"ok": True, "folder_link": folder_link, "files": files, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Sheets helpers
# ---------------------------------------------------------------------------


def _csv_to_values(csv_path: Path) -> list[list[str]]:
    """Read a CSV file and return it as a list-of-lists for the Sheets API."""
    with open(csv_path, newline="") as f:
        return [row for row in csv.reader(f)]


def _ensure_sheet_tab(sheets_svc, spreadsheet_id: str, tab_name: str) -> None:
    """Add a tab named *tab_name* if it doesn't already exist."""
    meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if tab_name not in existing:
        body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        sheets_svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()


def sync_to_sheets() -> dict[str, Any]:
    """
    Create or update a Google Sheet with Daily and Activities tabs.
    Returns a result dict with keys: ok, sheet_url, error.
    """
    missing = [p.name for p in (DAILY_CSV, ACTIVITIES_CSV) if not p.exists()]
    if missing:
        joined = ", ".join(missing)
        return {"ok": False, "error": f"CSVs not found: {joined}. Run 'Pull Data' first."}

    try:
        creds = _load_credentials()
        svc = _sheets_service(creds)
        cfg = load_config()

        sheet_id = cfg.get("sheet_id")

        if not sheet_id:
            # Create new spreadsheet
            body = {
                "properties": {"title": "Garmin Data"},
                "sheets": [
                    {"properties": {"title": "Daily"}},
                    {"properties": {"title": "Activities"}},
                ],
            }
            result = svc.spreadsheets().create(body=body, fields="spreadsheetId").execute()
            sheet_id = result["spreadsheetId"]
            cfg["sheet_id"] = sheet_id
        else:
            # Ensure both tabs exist
            _ensure_sheet_tab(svc, sheet_id, "Daily")
            _ensure_sheet_tab(svc, sheet_id, "Activities")

        tab_map = {"Daily": DAILY_CSV, "Activities": ACTIVITIES_CSV}
        data = []
        for tab, csv_path in tab_map.items():
            values = _csv_to_values(csv_path)
            data.append({"range": f"'{tab}'!A1", "values": values})

        # Clear existing data in both tabs first
        svc.spreadsheets().values().batchClear(
            spreadsheetId=sheet_id,
            body={"ranges": [f"'{t}'!A:ZZZ" for t in tab_map]},
        ).execute()

        # Write fresh data
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

        cfg["last_export"] = datetime.now(timezone.utc).isoformat()
        save_config(cfg)

        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        return {"ok": True, "sheet_url": sheet_url, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
