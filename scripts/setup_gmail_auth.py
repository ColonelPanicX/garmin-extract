#!/usr/bin/env python3
"""
One-time Gmail OAuth setup for automated Garmin MFA retrieval.

Uses requests_oauthlib directly to avoid PKCE complications with the
OOB (out-of-band) flow on headless servers.

Usage:
    python scripts/setup_gmail_auth.py
"""

import json
import sys
import time
from pathlib import Path

ROOT             = Path(__file__).parent.parent
CREDENTIALS_FILE = ROOT / "google_credentials.json"
TOKEN_FILE       = ROOT / ".google_token.json"
CODE_FILE        = ROOT / ".gmail_auth_code"

if not CREDENTIALS_FILE.exists():
    print(f"ERROR: {CREDENTIALS_FILE} not found.")
    sys.exit(1)

with open(CREDENTIALS_FILE) as f:
    creds_data = json.load(f)["installed"]

CLIENT_ID     = creds_data["client_id"]
CLIENT_SECRET = creds_data["client_secret"]
AUTH_URI      = creds_data["auth_uri"]
TOKEN_URI     = creds_data["token_uri"]
REDIRECT_URI  = "urn:ietf:wg:oauth:2.0:oob"
SCOPES        = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SCOPE         = " ".join(SCOPES)

from requests_oauthlib import OAuth2Session

oauth = OAuth2Session(CLIENT_ID, scope=SCOPE, redirect_uri=REDIRECT_URI)
auth_url, state = oauth.authorization_url(
    AUTH_URI,
    access_type="offline",
    prompt="consent",
)

print("Open this URL in any browser (phone, desktop, anywhere):")
print()
print(auth_url)
print()
print(f"Then run:  echo YOUR_CODE > {CODE_FILE}")
print("Waiting up to 5 minutes...")

CODE_FILE.unlink(missing_ok=True)
for _ in range(300):
    if CODE_FILE.exists():
        code = CODE_FILE.read_text().strip()
        CODE_FILE.unlink(missing_ok=True)
        break
    time.sleep(1)
else:
    print("ERROR: Timed out.")
    sys.exit(1)

# Exchange code for tokens (no PKCE verifier needed)
import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # not needed but suppresses warnings

token = oauth.fetch_token(
    TOKEN_URI,
    code=code,
    client_secret=CLIENT_SECRET,
    include_client_id=True,
)

# Save in google-auth Credentials format
token_data = {
    "token":         token.get("access_token"),
    "refresh_token": token.get("refresh_token"),
    "token_uri":     TOKEN_URI,
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scopes":        SCOPES,
    "expiry":        None,
}
TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
print(f"\nToken saved to {TOKEN_FILE}")
print("Gmail MFA automation is now active.")
