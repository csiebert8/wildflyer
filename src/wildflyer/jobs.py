"""Run a solve in a background thread, so a user interface can show progress and stop it."""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from .model import RunInput
from .output import write_output
from .runs import RUNS_DIR, SCHEDULE_FILE, new_run_folder
from .solver import SolveControl, SolveResult, solve


@dataclass
class Job:
    rules_path: Path
    run: RunInput
    time_limit: float
    folder: Path
    control: SolveControl = field(default_factory=SolveControl)
    result: SolveResult | None = None
    output: Path | None = None
    error: str | None = None
    _thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def finished(self) -> bool:
        return self._thread is not None and not self._thread.is_alive()

    def stop(self) -> None:
        self.control.stop()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _work(self) -> None:
        try:
            self.result = solve(self.run, time_limit=self.time_limit, control=self.control)
            self.output = write_output(self.folder / SCHEDULE_FILE, self.run, self.result, self.rules_path)
        except Exception:  # surfaced in the UI instead of dying silently in the thread
            self.error = traceback.format_exc()
        finally:
            self.control.phase = "done"


def start_job(rules_path: str | Path, run: RunInput, time_limit: float, runs_dir: Path = RUNS_DIR) -> Job:
    rules_path = Path(rules_path)
    folder = new_run_folder(rules_path, run.settings.run_name or rules_path.stem, runs_dir)
    job = Job(rules_path, run, time_limit, folder)
    job._thread = threading.Thread(target=job._work, name=f"solve-{folder.name}", daemon=True)
    job._thread.start()
    return job
