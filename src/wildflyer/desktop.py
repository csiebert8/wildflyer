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
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "AUSL Schedule Solver"
PORT = 8501
DESKTOP_ENV = "AUSL_DESKTOP"  # tells app.py to show the Quit button
NO_BROWSER_ENV = "AUSL_NO_BROWSER"  # set by automated tests: don't open a browser
IDLE_MINUTES = float(os.environ.get("AUSL_IDLE_MINUTES", "15"))  # quit after this long with no page open


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


def open_browser_when_ready(port: int, timeout: float = 120.0) -> threading.Thread:
    """Open the app page once its server answers.

    The server runs "headless" (Streamlit doesn't open a browser itself), because
    otherwise Streamlit asks a one-time email question on the first run on a
    computer, which an app without a terminal can never answer, so it would hang.
    """
    def wait_and_open() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _running(port):
                webbrowser.open(f"http://localhost:{port}")
                return
            time.sleep(0.5)

    thread = threading.Thread(target=wait_and_open, daemon=True, name="open-browser")
    thread.start()
    return thread


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


class IdleWatch:
    """Decides when the app has been unused long enough to shut itself down.

    "Unused" means no browser page connected to this app (other tabs and apps are
    never looked at) and no solve running.
    """

    def __init__(self, limit_seconds: float, now: float):
        self.limit = limit_seconds
        self.idle_since: float | None = now  # idle from the start until the first page connects

    def should_quit(self, open_pages: int | None, solving: bool, now: float) -> bool:
        if open_pages is None or open_pages > 0 or solving:  # unknown counts as in use
            self.idle_since = None
            return False
        if self.idle_since is None:
            self.idle_since = now
        return now - self.idle_since >= self.limit


def _open_pages() -> int | None:
    """Browser pages connected to this app right now, or None if it can't be told."""
    try:
        from streamlit import runtime

        if not runtime.exists():
            return None
        return runtime.get_instance()._session_mgr.num_active_sessions()
    except Exception:
        return None


def _watch_idle(limit_seconds: float, check_every: float = 30.0) -> None:
    from .jobs import any_running

    watch = IdleWatch(limit_seconds, time.monotonic())
    while True:
        time.sleep(check_every)
        if watch.should_quit(_open_pages(), any_running(), time.monotonic()):
            print(f"No page open for {limit_seconds / 60:g} minutes; shutting down.", flush=True)
            os._exit(0)


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

    if IDLE_MINUTES > 0:
        threading.Thread(target=_watch_idle, args=(IDLE_MINUTES * 60, min(30.0, IDLE_MINUTES * 30)),
                         daemon=True, name="idle-shutdown").start()

    from streamlit.web import cli as stcli

    from .cli import APP_FLAGS

    if not os.environ.get(NO_BROWSER_ENV):
        open_browser_when_ready(port)
    sys.argv = ["streamlit", "run", str(bundle_dir() / "app.py"), *APP_FLAGS,
                "--server.port", str(port), "--server.headless", "true",
                "--global.developmentMode", "false"]
    return stcli.main()


if __name__ == "__main__":
    sys.exit(main())
