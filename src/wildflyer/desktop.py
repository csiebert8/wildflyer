"""Desktop entry point: what the packaged "AUSL Schedule Solver.app" runs.

Starts the app's local web server and opens it in the browser. Rules files and
runs live in ~/Documents/AUSL Schedule Solver. Launching again while it is
already running just reopens the browser tab.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "AUSL Schedule Solver"
PORT = 8501
DESKTOP_ENV = "AUSL_DESKTOP"  # tells app.py to show the Quit button
NO_BROWSER_ENV = "AUSL_NO_BROWSER"  # set by automated tests: don't open a browser


def data_folder() -> Path:
    """Where the user's rules files and runs are kept."""
    override = os.environ.get("AUSL_DATA_DIR")
    return Path(override) if override else Path.home() / "Documents" / APP_NAME


def bundle_dir() -> Path:
    """Folder holding the wildflyer package files (inside the .app when packaged)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "wildflyer"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def _running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _seed(folder: Path) -> None:
    """First launch: create the folder with an example rules file to start from."""
    folder.mkdir(parents=True, exist_ok=True)
    example = bundle_dir() / "examples" / "ausl_2027.xlsx"
    target = folder / "example_rules_2027.xlsx"
    if example.is_file() and not any(folder.glob("*.xlsx")):
        shutil.copy2(example, target)


def main() -> int:
    url = f"http://localhost:{PORT}"
    if _running(PORT):  # already open: just bring the page back
        if not os.environ.get(NO_BROWSER_ENV):
            webbrowser.open(url)
        return 0
    port = PORT
    while not _port_free(port):  # something else is using 8501
        port += 1

    folder = data_folder()
    _seed(folder)
    os.chdir(folder)
    os.environ[DESKTOP_ENV] = "1"
    if getattr(sys, "frozen", False):  # no terminal in the .app: keep a log for troubleshooting
        log = open(folder / "app.log", "w", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = log

    from streamlit.web import cli as stcli

    from .cli import APP_FLAGS

    headless = "true" if os.environ.get(NO_BROWSER_ENV) else "false"
    sys.argv = ["streamlit", "run", str(bundle_dir() / "app.py"), *APP_FLAGS,
                "--server.port", str(port), "--server.headless", headless,
                "--global.developmentMode", "false"]
    return stcli.main()


if __name__ == "__main__":
    sys.exit(main())
