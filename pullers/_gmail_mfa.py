"""
Gmail-based MFA code retrieval for Garmin Connect login.

Called by garmin.py's wait_for_mfa() when Google credentials are present.
Polls the Gmail inbox for a Garmin security code email and returns the code.
Falls back gracefully if credentials are missing or the API call fails.
"""

import base64
import json
import re
import time
from pathlib import Path

ROOT             = Path(__file__).parent.parent
CREDENTIALS_FILE = ROOT / "google_credentials.json"
TOKEN_FILE       = ROOT / ".google_token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _build_gmail_service():
    """Return an authenticated Gmail API service, or None if not configured."""
    if not TOKEN_FILE.exists():
        return None
    if not CREDENTIALS_FILE.exists():
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"  [gmail] Failed to build service: {e}")
        return None


def _extract_code_from_text(text: str) -> str | None:
    """Find a 6-digit Garmin security code in email body text."""
    # Garmin's email says something like "Your security code is 123456"
    # or just presents the code prominently
    patterns = [
        r"security code[^\d]*(\d{6})",
        r"verification code[^\d]*(\d{6})",
        r"your code[^\d]*(\d{6})",
        r"\b(\d{6})\b",  # fallback: any 6-digit number
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _get_message_text(service, msg_id: str) -> str:
    """Decode a Gmail message body to plain text."""
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    payload = msg.get("payload", {})
    parts   = payload.get("parts", [payload])

    for part in parts:
        mime = part.get("mimeType", "")
        if "text" in mime:
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def wait_for_mfa_gmail(timeout: int = 300) -> str | None:
    """
    Poll Gmail for a Garmin MFA code. Returns the code string, or None
    if credentials are unavailable or the poll times out.

    Args:
        timeout: seconds to poll before giving up (default 5 minutes)
    """
    service = _build_gmail_service()
    if not service:
        return None

    print("  [gmail] Polling inbox for Garmin MFA code...")

    # Record start time — only look at emails received after this point
    start_epoch_ms = int(time.time() * 1000)
    start_epoch_s  = int(time.time())
    poll_interval  = 5  # seconds between checks
    elapsed        = 0

    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval

        try:
            # Search for Garmin MFA emails received in the last few minutes
            query = (
                f"from:noreply@garmin.com "
                f"after:{start_epoch_s - 60} "
                f"subject:(security code OR verification OR sign-in)"
            )
            result = service.users().messages().list(
                userId="me", q=query, maxResults=5
            ).execute()

            messages = result.get("messages", [])
            if not messages:
                # Broader fallback — any recent garmin email
                query2 = f"from:garmin.com after:{start_epoch_s - 60}"
                result2 = service.users().messages().list(
                    userId="me", q=query2, maxResults=5
                ).execute()
                messages = result2.get("messages", [])

            for msg in messages:
                text = _get_message_text(service, msg["id"])
                code = _extract_code_from_text(text)
                if code:
                    print(f"  [gmail] Found MFA code in email.")
                    return code

            print(f"  [gmail] No code yet ({elapsed}s elapsed)...")

        except Exception as e:
            print(f"  [gmail] Poll error: {e}")

    print("  [gmail] Timed out waiting for MFA email.")
    return None


def is_configured() -> bool:
    """Return True if Gmail credentials are present and usable."""
    return TOKEN_FILE.exists() and CREDENTIALS_FILE.exists()
