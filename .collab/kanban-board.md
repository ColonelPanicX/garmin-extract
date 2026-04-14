# Kanban Board

<!--
Format:
- [ ] TASK-###: Description (@owner) [p?] [area:?] [type:?]
Examples:
- [ ] TASK-001: Draft project plan (@user) [p1] [area:planning] [type:doc]
- [ ] TASK-002: Implement exporter refactor (@claude) [p2] [area:exporters] [type:feature]
-->

## Working Rules
- The board is the source of truth.
- Don't move items to **Done** unless there is a tangible artifact (merged code / written doc / completed checklist).
- Keep **In Progress** to ~3 items max (soft WIP limit).
- If blocked, move to **Blocked** and add a short reason.
- Track one active sprint at a time (optional). Move committed sprint work into **Sprint Backlog**.
- Only move items to **To Do** if they are in the active sprint scope.

## Active Sprint (optional)
- Sprint ID: `SPRINT-YYYYMMDD`
- Dates: `MM.DD.YYYY` -> `MM.DD.YYYY`
- Goal: _one sentence_
- Exit criteria: _what must be true at sprint end_

---

## Inbox (untriaged)

## Backlog (approved, not scheduled)

- [ ] TASK-009: Debug Gmail MFA automation — token likely authorized for wrong Google account (@user) [p2] [area:auth] [type:fix]
  <!-- During 04.13.2026 live test, Gmail automation ran but did not find the MFA email.
       Likely cause: OAuth token was authorized against a different Google account than the inbox
       receiving the Garmin MFA code. MFA modal in TUI now handles fallback gracefully. -->
- [ ] TASK-010: Phase 3 — Initial Setup screen (credentials config wizard) (@claude) [p1] [area:tui] [type:feature]
  <!-- TUI stub currently shows "Coming in Phase 3". Needs: GARMIN_EMAIL/PASSWORD input,
       .env file write, Gmail OAuth setup flow, prerequisite checks (Chrome, Xvfb) -->
- [ ] TASK-012: Research remaining Garmin endpoints via DevTools network capture (@user) [p3] [area:data] [type:research]
  <!-- garminconnect audit covered 77 methods. DevTools session on Garmin Connect web app
       may reveal additional endpoints not in the library (device solar, menstrual detail, etc.) -->

- [ ] TASK-001: Write smoke tests for CSV builder (`reports/build_garmin_csvs.py`) (@user) [p2] [area:testing] [type:test]
- [ ] TASK-002: Write smoke tests for export importer (`pullers/garmin_import_export.py`) (@user) [p2] [area:testing] [type:test]
- [ ] TASK-003: Add `--output-dir` flag to `garmin.py` for configurable data directory (@user) [p3] [area:cli] [type:feature]
- [ ] TASK-004: Add Docker / docker-compose setup for reproducible environment (@user) [p3] [area:infra] [type:feature]
- [ ] TASK-005: Set up GitHub Actions CI workflow (lint + unit tests) (@user) [p3] [area:ci] [type:infra]
- [ ] TASK-006: Add SQLite export option to `build_garmin_csvs.py` (@user) [p4] [area:reports] [type:feature]
- [ ] TASK-007: Add Parquet export option to `build_garmin_csvs.py` (@user) [p4] [area:reports] [type:feature]

## Sprint Backlog (committed scope for active sprint)

## To Do (next up)

## In Progress (doing now)

## Blocked

## In Review (awaiting user/PR review)

## Done

- [x] TASK-100: Port and scrub all source files from private project (@user) [p1] [area:setup] [type:chore]
- [x] TASK-101: Audit project for personal information (emails, IDs, paths) (@claude) [p1] [area:setup] [type:chore]
- [x] TASK-102: Write public README.md (@claude) [p1] [area:docs] [type:doc]
- [x] TASK-103: Populate kanban board with backlog items (@claude) [p2] [area:planning] [type:chore]
- [x] TASK-104: Create interactive menu entry point (`garmin_extract.py`) (@claude) [p1] [area:ux] [type:feature]
- [x] TASK-105: Make Xvfb conditional for OS-agnostic operation (Windows/macOS/Linux) (@claude) [p1] [area:compat] [type:fix]
- [x] TASK-106: Align project to coding playbook Phase 1 standards (@claude) [p1] [area:setup] [type:chore]
  <!-- pyproject.toml + uv, dependency-groups, CLAUDE.md, tests/ scaffolding, logs/ + output/ dirs,
       .gitignore updates, signal-based navigation (BackSignal/ExitToMainSignal/QuitSignal),
       x key + prompt_with_navigation(), type hints on all garmin_extract.py functions,
       Rich for colored status output, ruff + black + mypy all passing clean -->
- [x] TASK-008: Fix `datetime.utcfromtimestamp()` / `utcnow()` deprecation warnings (@claude) [p3] [area:reports] [type:fix]
  <!-- Fixed in build_garmin_csvs.py (2 occurrences) and pullers/garmin.py (1 occurrence).
       Replaced with timezone-aware datetime.fromtimestamp(..., tz=timezone.utc) and
       datetime.now(timezone.utc). Output format preserved via strftime. -->
- [x] TASK-016: Phase 2 — Full Textual TUI screen hierarchy (@claude) [p1] [area:tui] [type:feature]
  <!-- MainMenuScreen, DataPullScreen, PullProgressScreen (split log + metric/day panel + MFA modal),
       StubScreens for Phase 3/4. Merged via PRs #3, #4, #8 on 04.14.2026. -->
- [x] TASK-017: Dynamic metric parsing — drop hardcoded _METRICS from TUI (@claude) [p2] [area:tui] [type:refactor]
  <!-- Three display modes (day/metric/simple) driven by days param. Progress bar total from
       parsed output. Closed GitHub issue #5 and #6. Merged in PR #8 on 04.14.2026. -->
- [x] TASK-018: Expand puller to full Garmin Connect API surface (@claude) [p2] [area:data] [type:feature]
  <!-- Added nutrition, menstrual cycle per-date; per-activity detail (8 endpoints/activity);
       static profile data once per session → profile.json. Closed GitHub issue #7. PR #8. -->
- [x] TASK-015: Evaluate `garminconnect` mobile SSO OAuth as browser stack replacement (@user) [p2] [area:auth] [type:spike]
  <!-- Evaluated 04.11.2026. garminconnect v0.3.2 (released same day) uses curl_cffi TLS fingerprint
       impersonation — no real browser. Auth appears to clear Cloudflare as of evaluation date.
       Decision: keep garmin-extract entirely separate. garminconnect is a lightweight API wrapper;
       garmin-extract is a full pipeline (auto-pull, Gmail MFA, raw + normalized CSVs, Sheets/Drive).
       Integration rejected — would inherit garminconnect's frequent breaking changes as maintenance
       burden. Natural positioning: garmin-extract is the alternative when garminconnect fails.
       Optional --fast-mode flag (try garminconnect if installed) left as future consideration only. -->
- [x] TASK-010: Phase 3 — Initial Setup screen (credentials config wizard) (@claude) [p1] [area:tui] [type:feature]
  <!-- PrereqScreen (4 checks + Linux install), CredentialsScreen (.env r/w), GmailSetupScreen
       (3 states: no creds / authorized / needs auth + URL-in-modal fix). PRs #9, #10, #11. -->
- [x] TASK-011: Phase 4 — Automation screen (Gmail MFA, cron, Drive/Sheets stub) (@claude) [p1] [area:tui] [type:feature]
  <!-- AutomationScreen landing, GmailMfaScreen (live status check), CronScreen (install/edit/remove
       via crontab with # garmin-extract marker), Drive/Sheets Phase 5 stub. PRs #12, #13. -->
