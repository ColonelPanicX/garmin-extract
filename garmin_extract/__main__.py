"""Package entry point — routes to the CLI, or executes a script if frozen.

The frozen Windows exe bundles the app itself, but subprocess-invoked scripts
(pullers/garmin.py, reports/build_garmin_csvs.py, etc.) still need to run.
In a PyInstaller bundle `sys.executable` is garmin-extract.exe (not python.exe),
so a plain `subprocess.Popen([sys.executable, "-u", script, ...])` would just
re-launch the CLI with the wrong args.

To keep the subprocess pattern working, we intercept `-u <script>` here and
execute that script via `runpy` — mimicking what `python -u script` does.
This path only fires when `sys.frozen` is True, so regular installs are
unaffected.
"""

from __future__ import annotations

import sys


def _run_script_if_frozen() -> None:
    """If invoked as `garmin-extract.exe -u <script> [args...]`, run the script."""
    if not getattr(sys, "frozen", False):
        return
    if len(sys.argv) < 3 or sys.argv[1] != "-u":
        return

    script = sys.argv[2]
    sys.argv = [script] + sys.argv[3:]

    # Add the script's directory to sys.path so sibling imports work
    # (e.g. pullers/garmin.py does `from _gmail_mfa import ...`)
    from pathlib import Path

    script_dir = str(Path(script).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Unbuffered line output so the GUI sees progress in real time
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass

    import runpy

    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        sys.exit(e.code if e.code is not None else 0)
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)


_run_script_if_frozen()

from garmin_extract.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
