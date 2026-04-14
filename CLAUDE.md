# garmin-extract

Automated Garmin Connect data pipeline — bypasses Cloudflare via real Chrome browser, automating MFA via Gmail API.

## Tech Stack

- Python 3.12
- SeleniumBase (UC mode) — browser automation, Cloudflare bypass
- Xvfb — virtual display for headless Chrome on Linux
- Google Gmail API — automatic MFA code extraction
- Rich — terminal output styling

## Key Entry Points

| Command | Purpose |
|---------|---------|
| `uv run python -m garmin_extract` | TUI (default) |
| `uv run python -m garmin_extract --no-tui` | Print menu (headless / cron) |
| `uv run python garmin_extract.py` | Shim — calls the package (backward compat) |
| `garmin-extract` | Installed script (`uv pip install -e .`) |
| `python pullers/garmin.py --date YYYY-MM-DD --days N` | Direct data pull |
| `python reports/build_garmin_csvs.py` | Rebuild CSV reports |
| `scripts/pull-garmin.sh` | Cron wrapper (pull + rebuild CSVs) |

## Dev Setup

```bash
uv venv
uv sync --dev
uv run ruff check .
uv run black --check .
uv run python garmin_extract.py
```

## Key Files

- `garmin_extract.py` — interactive menu entry point
- `pullers/garmin.py` — daily data pull logic
- `pullers/_gmail_mfa.py` — Gmail MFA automation
- `pullers/garmin_import_export.py` — historical bulk import
- `reports/build_garmin_csvs.py` — CSV builder
- `scripts/setup_gmail_auth.py` — Google OAuth setup

## Build Phase

Currently **Phase 1** (package scaffold + print menu + Textual TUI stub).
- `garmin_extract/` package with `__main__.py`, `cli.py`, `app.py` (TUI stub), `menu.py` (print menu)
- Phase 2: full Textual TUI screens (main menu, data pull, config wizard)
- Phase 3: config wizard screen
- Phase 4: automation wizard (Gmail, cron, Drive/Sheets)

## Agent Rules

- Never commit `.env`, `google_credentials.json`, `.google_token.json`, or `data/`
- Never delete `.garmin_browser_profile/` — it persists the Chrome session
- Run `ruff check . && black --check .` before staging any changes
- Read `.collab/kanban-board.md` before starting work
- Write session summary to `.collab/session-summaries/MM.DD.YYYY-claude-summary.md` at end of non-trivial sessions
