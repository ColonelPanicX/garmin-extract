"""Credential storage — keyring-first, .env fallback, runtime as last resort."""

from __future__ import annotations

from pathlib import Path

_SERVICE = "garmin-extract"
_EMAIL_KEY = "email"
_PASSWORD_KEY = "password"
_PROBE_KEY = "_probe"
ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".env"


def detect_keyring() -> tuple[bool, str]:
    """
    Returns (available, detail).
    Performs a write/read/delete smoke-test to confirm the backend actually works.
    """
    try:
        import keyring  # noqa: PLC0415

        backend = keyring.get_keyring()
        name = type(backend).__name__

        # Backends that can never store a secret
        if any(x in name for x in ("Fail", "Null", "PlainText")):
            return False, f"No secure backend ({name})"

        # Smoke-test: write, read, delete
        keyring.set_password(_SERVICE, _PROBE_KEY, "1")
        val = keyring.get_password(_SERVICE, _PROBE_KEY)
        try:
            keyring.delete_password(_SERVICE, _PROBE_KEY)
        except Exception:
            pass
        if val == "1":
            return True, name
        return False, "Keyring probe failed"

    except ImportError:
        return False, "keyring package not installed"
    except Exception as exc:
        return False, str(exc)


def load_credentials() -> tuple[str, str]:
    """
    Returns (email, password).  Either may be empty string.
    Priority: keyring → .env → ('', '').
    """
    try:
        import keyring  # noqa: PLC0415

        email = keyring.get_password(_SERVICE, _EMAIL_KEY) or ""
        password = keyring.get_password(_SERVICE, _PASSWORD_KEY) or ""
        if email or password:
            return email, password
    except Exception:
        pass

    return _load_from_env()


def save_to_keyring(email: str, password: str) -> tuple[bool, str]:
    """Save credentials to OS keyring.  Returns (ok, detail)."""
    try:
        import keyring  # noqa: PLC0415

        keyring.set_password(_SERVICE, _EMAIL_KEY, email)
        keyring.set_password(_SERVICE, _PASSWORD_KEY, password)
        return True, "Saved to keyring"
    except Exception as exc:
        return False, str(exc)


def save_to_env(email: str, password: str) -> None:
    """Write credentials to .env (plaintext)."""
    lines = [
        "# Garmin Connect credentials",
        f"GARMIN_EMAIL={email}",
        f"GARMIN_PASSWORD={password}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n")


def check_credentials() -> tuple[bool, str]:
    """
    Returns (ok, detail) for status display in SetupScreen.
    Shows where creds came from.
    """
    try:
        import keyring  # noqa: PLC0415

        email = keyring.get_password(_SERVICE, _EMAIL_KEY) or ""
        password = keyring.get_password(_SERVICE, _PASSWORD_KEY) or ""
        if email and password:
            return True, f"{email}  [dim](keyring)[/]"
        if email:
            return False, f"{email}  [dim](no password in keyring)[/]"
    except Exception:
        pass

    email, password = _load_from_env()
    if email and password:
        return True, f"{email}  [dim](.env)[/]"
    if email:
        return False, f"{email}  [dim](no password in .env)[/]"

    return False, "Not configured"


def _load_from_env() -> tuple[str, str]:
    email = ""
    password = ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "GARMIN_EMAIL":
                email = v
            elif k == "GARMIN_PASSWORD":
                password = v
    return email, password
