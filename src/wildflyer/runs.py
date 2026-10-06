"""Run folders: runs/<date-time>_<run name>/ holding rules.xlsx and schedule.xlsx."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path("runs")
RULES_FILE = "rules.xlsx"
SCHEDULE_FILE = "schedule.xlsx"
_STAMP = "%Y-%m-%d_%H%M%S"


@dataclass(frozen=True)
class RunInfo:
    folder: Path
    name: str
    created: datetime | None

    @property
    def schedule(self) -> Path:
        return self.folder / SCHEDULE_FILE

    @property
    def rules(self) -> Path:
        return self.folder / RULES_FILE

    @property
    def label(self) -> str:
        when = self.created.strftime("%b %d %H:%M") if self.created else "?"
        return f"{when} · {self.name}"


def new_run_folder(rules_path: str | Path, run_name: str, base: Path = RUNS_DIR) -> Path:
    """Create a run folder and copy the rules workbook into it."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_name).strip("_") or "run"
    folder = base / f"{datetime.now():{_STAMP}}_{name}"
    suffix = 2
    while folder.exists():
        folder = base / f"{datetime.now():{_STAMP}}_{name}_{suffix}"
        suffix += 1
    folder.mkdir(parents=True)
    shutil.copy2(rules_path, folder / RULES_FILE)
    return folder


def list_runs(base: Path = RUNS_DIR) -> list[RunInfo]:
    """Run folders that hold a schedule, newest first."""
    if not base.is_dir():
        return []
    runs = []
    for folder in base.iterdir():
        if not (folder / SCHEDULE_FILE).is_file():
            continue
        m = re.match(r"(\d{4}-\d{2}-\d{2}_\d{6})_(.*)", folder.name)
        created = None
        if m:
            try:
                created = datetime.strptime(m.group(1), _STAMP)
            except ValueError:
                pass
        runs.append(RunInfo(folder, m.group(2) if m else folder.name, created))
    return sorted(runs, key=lambda r: (r.created or datetime.min, r.folder.name), reverse=True)
