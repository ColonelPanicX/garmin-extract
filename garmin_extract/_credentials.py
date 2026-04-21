"""Credential storage — keyring-first, .env fallback, runtime as last resort."""

from __future__ import annotations

import os

from garmin_extract._paths import app_root

_SERVICE = "garmin-extract"
_EMAIL_KEY = "email"
_PASSWORD_KEY = "password"
_PROBE_KEY = "_probe"
ROOT = app_root()
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
        _scrub_env()
        return True, "Saved to keyring"
    except Exception as exc:
        return False, str(exc)


def save_to_env(email: str, password: str) -> None:
    """Write credentials to .env (plaintext). Sets 0600 perms on POSIX."""
    lines = [
        "# Garmin Connect credentials",
        f"GARMIN_EMAIL={email}",
        f"GARMIN_PASSWORD={password}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    _lock_down_env(ENV_FILE)


def _lock_down_env(path) -> None:
    """chmod 600 on POSIX so the .env is only readable by the owning user."""
    if os.name != "posix":
        return
    try:
        path.chmod(0o600)
    except OSError:
        pass


def check_credentials() -> tuple[bool, str]:
    """
    Returns (ok, detail) for status display in SetupScreen.
    Shows where creds came from, or surfaces keyring errors if lookup fails.
    """
    keyring_error: str | None = None
    try:
        import keyring  # noqa: PLC0415

        email = keyring.get_password(_SERVICE, _EMAIL_KEY) or ""
        password = keyring.get_password(_SERVICE, _PASSWORD_KEY) or ""
        if email and password:
            return True, f"{email}  [dim](keyring)[/]"
        if email:
            return False, f"{email}  [dim](no password in keyring)[/]"
    except Exception as exc:
        keyring_error = str(exc)

    email, password = _load_from_env()
    if email and password:
        return True, f"{email}  [dim](.env)[/]"
    if email:
        return False, f"{email}  [dim](no password in .env)[/]"

    if keyring_error:
        return False, f"Keyring error: {keyring_error}"
    return False, "Not configured"


def clear_credentials() -> tuple[bool, str]:
    """Remove credentials from keyring and .env. Returns (ok, detail)."""
    errors: list[str] = []

    try:
        import keyring  # noqa: PLC0415

        for key in (_EMAIL_KEY, _PASSWORD_KEY):
            try:
                keyring.delete_password(_SERVICE, key)
            except Exception:
                pass  # not stored there — fine
    except ImportError:
        pass
    except Exception as exc:
        errors.append(str(exc))

    _scrub_env()

    if errors:
        return False, f"Errors: {', '.join(errors)}"
    return True, "Credentials cleared"


def _scrub_env() -> None:
    """Remove Garmin credentials from .env after a successful keyring save."""
    if not ENV_FILE.exists():
        return
    kept = []
    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(("GARMIN_EMAIL=", "GARMIN_PASSWORD=")):
            continue
        kept.append(line)
    # If nothing meaningful remains, delete the file entirely
    if all(not ln.strip() or ln.strip().startswith("#") for ln in kept):
        ENV_FILE.unlink()
    else:
        ENV_FILE.write_text("\n".join(kept) + "\n")
        _lock_down_env(ENV_FILE)


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
