# PyInstaller spec for the Windows build.
#
# Produces a `dist/garmin-extract/` onedir bundle containing garmin-extract.exe
# and all its dependencies. ChromeDriver is NOT bundled — SeleniumBase downloads
# a matching driver at runtime.
#
# Build locally with:
#   pyinstaller garmin-extract-windows.spec
#
# CI builds this on a Windows runner in .github/workflows/build-windows.yml.

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Hidden imports ───────────────────────────────────────────────────────────
# PyInstaller's static analysis scans the main entry point, but several modules
# are only imported by subprocess-invoked scripts (pullers/garmin.py,
# scripts/setup_gmail_auth.py, etc.) — those imports need to be listed here so
# they get packaged in the bundle.
hiddenimports = [
    "dotenv",  # pullers/garmin.py — loads .env credentials
    "requests_oauthlib",  # scripts/setup_gmail_auth.py — Gmail OAuth flow
    # Windows keyring backend dependencies — keyring.backends.Windows uses
    # pywin32-ctypes to call win32cred (Windows Credential Manager).
    # PyInstaller's static analysis often misses these since they're imported
    # dynamically by keyring's backend auto-selection.
    "win32ctypes",
    "win32ctypes.pywin32",
    "win32ctypes.pywin32.win32cred",
    "win32ctypes.pywin32.pywintypes",
]
hiddenimports += collect_submodules("seleniumbase")
hiddenimports += collect_submodules("google.auth")
hiddenimports += collect_submodules("google.oauth2")  # pullers/_gmail_mfa.py
hiddenimports += collect_submodules("googleapiclient")
hiddenimports += collect_submodules("google_auth_oauthlib")
hiddenimports += collect_submodules("keyring")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("win32ctypes")

# ── Data files ───────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files("seleniumbase")
datas += collect_data_files("google_auth_oauthlib")

# Project-local scripts the app invokes via subprocess
datas += [
    ("pullers", "pullers"),
    ("reports", "reports"),
    ("scripts", "scripts"),
]


a = Analysis(
    ["garmin_extract/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="garmin-extract",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed app (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="garmin-extract",
)
