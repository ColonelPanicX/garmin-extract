"""
Gmail-based MFA code retrieval for Garmin Connect login.

Called by garmin.py's wait_for_mfa() when Google credentials are present.
Polls the Gmail inbox for a Garmin security code email and returns the code.
Falls back gracefully if credentials are missing or the API call fails.
"""

import base64
import re
import sys
import time
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path(__file__).parent.parent
CREDENTIALS_FILE = ROOT / "google_credentials.json"
TOKEN_FILE = ROOT / ".google_token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _build_gmail_service():
    """Return an authenticated Gmail API service, or None if not configured."""
    if not TOKEN_FILE.exists():
        return None
    if not CREDENTIALS_FILE.exists():
        return None

    try:
        import json as _json  # noqa: I001
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        # Read all fields from token file directly — preserves all scopes (gmail + sheets + drive)
        # rather than locking to the hardcoded SCOPES constant on refresh.
        tok = _json.loads(TOKEN_FILE.read_text())
        creds = Credentials(
            token=tok.get("token"),
            refresh_token=tok.get("refresh_token"),
            token_uri=tok.get("token_uri"),
            client_id=tok.get("client_id"),
            client_secret=tok.get("client_secret"),
            scopes=tok.get("scopes", SCOPES),
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tok["token"] = creds.token
            TOKEN_FILE.write_text(_json.dumps(tok, indent=2))

        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"  [gmail] Failed to build service: {e}")
        return None


def _extract_code_from_text(text: str) -> str | None:
    """Find a 6-digit Garmin security code in email body text.

    Prefers plain-text context patterns. The bare 6-digit fallback uses a
    negative lookbehind for '#' to avoid matching CSS hex colors like #000000.
    Also rejects all-zero and all-same-digit codes which are never real codes.
    """
    patterns = [
        r"security code[^\d]*(\d{6})",
        r"verification code[^\d]*(\d{6})",
        r"your code[^\d]*(\d{6})",
        r"code[:\s]+(\d{6})",
        r"(?<!#)\b(\d{6})\b",  # fallback — excludes CSS hex colors like #000000
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            code = match.group(1)
            # Reject obviously invalid codes
            if len(set(code)) == 1:  # all same digit: 000000, 111111, etc.
                continue
            return code
    return None


def _get_message_text(service, msg_id: str) -> str:
    """Decode a Gmail message body, preferring plain text over HTML."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

    payload = msg.get("payload", {})
    parts = payload.get("parts", [payload])

    # Prefer text/plain to avoid matching CSS hex colors in HTML bodies
    plain = html = ""
    for part in parts:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if not data:
            continue
        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if mime == "text/plain":
            plain = decoded
        elif mime == "text/html" and not html:
            html = decoded

    return plain or html


def wait_for_mfa_gmail(timeout: int = 300, poll_start: float | None = None) -> str | None:
    """
    Poll Gmail for a Garmin MFA code. Returns the code string, or None
    if credentials are unavailable or the poll times out.

    Tracks seen message IDs so the same email is never processed twice,
    preventing stale emails from being resubmitted on repeated poll loops.

    Args:
        timeout: seconds to poll before giving up (default 5 minutes)
        poll_start: epoch seconds to use as the internalDate anchor instead of
            now. Pass the script's import-time timestamp so emails sent during
            browser startup (before this function is called) are not excluded.
    """
    service = _build_gmail_service()
    if not service:
        return None

    print("  [gmail] Polling inbox for Garmin MFA code...")

    # Anchor to poll_start (script import time) rather than now. Garmin sends
    # the MFA email during the login sequence — 60–120s before this function is
    # called on a typical headless VM. Using time.time() here sets start_ms in
    # the future relative to the email's internalDate, causing the strict filter
    # below to exclude the very email we're looking for.
    start_epoch_s = int(poll_start) if poll_start is not None else int(time.time())
    start_ms = start_epoch_s * 1000
    poll_interval = 5  # seconds between checks
    elapsed = 0
    seen_ids = set()  # never re-process the same email

    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval

        try:
            # Search for Garmin MFA emails received since script start.
            # Garmin currently sends from alerts@account.garmin.com with subject
            # "Your Security Passcode"; older runs used noreply@garmin.com.
            # Gmail tokenizes on word boundaries, so "passcode" must be listed
            # explicitly — "code" does not match "Passcode".
            query = (
                f"from:(noreply@garmin.com OR alerts@account.garmin.com) "
                f"after:{start_epoch_s} "
                f"subject:(security code OR passcode OR verification OR sign-in)"
            )
            result = service.users().messages().list(userId="me", q=query, maxResults=5).execute()

            messages = result.get("messages", [])
            if not messages:
                # Broader fallback — any recent email from a garmin.com domain.
                query2 = f"from:(garmin.com OR account.garmin.com) after:{start_epoch_s}"
                result2 = (
                    service.users().messages().list(userId="me", q=query2, maxResults=5).execute()
                )
                messages = result2.get("messages", [])

            # Enrich with internalDate, drop any email not strictly newer than start,
            # and process newest-first so a fresh code always wins over a stale one.
            fresh: list[tuple[str, int]] = []
            for m in messages:
                meta = (
                    service.users()
                    .messages()
                    .get(userId="me", id=m["id"], format="minimal")
                    .execute()
                )
                idate = int(meta.get("internalDate", 0))
                if idate > start_ms:
                    fresh.append((m["id"], idate))
            fresh.sort(key=lambda pair: pair[1], reverse=True)

            for msg_id, _ in fresh:
                if msg_id in seen_ids:
                    continue  # already tried this email
                seen_ids.add(msg_id)

                text = _get_message_text(service, msg_id)
                code = _extract_code_from_text(text)
                if code:
                    print(f"  [gmail] Found MFA code in email (msg {msg_id[:8]}...).")
                    return code
                else:
                    print(
                        f"  [gmail] Email found but no valid code extracted (msg {msg_id[:8]}...)."
                    )

            print(f"  [gmail] No code yet ({elapsed}s elapsed)...")

        except Exception as e:
            print(f"  [gmail] Poll error: {e}")

    print("  [gmail] Timed out waiting for MFA email.")
    return None


def is_configured() -> bool:
    """Return True if Gmail credentials are present and the token has the Gmail scope."""
    if not TOKEN_FILE.exists() or not CREDENTIALS_FILE.exists():
        return False
    try:
        import json as _json

        tok = _json.loads(TOKEN_FILE.read_text())
        scopes = tok.get("scopes") or []
        return any("gmail" in s for s in scopes)
    except Exception:
        return False
