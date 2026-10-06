"""Solve control, run folders, background jobs, and the app page (smoke test)."""

import shutil
import threading
import time
from pathlib import Path

import pytest

from test_solver import DOUBLE_RR, R, make_run
from wildflyer.jobs import start_job
from wildflyer.loader import load
from wildflyer.runs import list_runs, new_run_folder
from wildflyer.solver import SolveControl, solve

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ausl_2027.xlsx"
APP = Path(__file__).resolve().parent.parent / "src" / "wildflyer" / "app.py"


class TestSolveControl:
    def test_reports_progress(self):
        control = SolveControl()
        rules = [DOUBLE_RR, R("DATE_PREFERENCE", hard=False, weight=1, option="prefer", days={5, 6})]
        result = solve(make_run(rules, n_days=28), time_limit=20, control=control)
        assert result.has_schedule
        assert control.solutions >= 1 and control.best_cost == result.soft_cost
        assert control.phase == "done" and not control.stopped

    def test_stop_keeps_best_schedule(self):
        run = load(EXAMPLE).run
        control = SolveControl()
        out = {}
        worker = threading.Thread(target=lambda: out.setdefault("r", solve(run, time_limit=300, control=control)))
        worker.start()
        deadline = time.monotonic() + 120
        while control.solutions == 0 and time.monotonic() < deadline:
            time.sleep(0.5)
        control.stop()
        worker.join(30)
        assert not worker.is_alive()
        result = out["r"]
        assert result.has_schedule and len(result.games) == 90
        assert result.wall_time < 150 and "Stopped early" in result.message

    def test_stop_before_start(self):
        control = SolveControl()
        control.stop()
        result = solve(make_run([DOUBLE_RR]), time_limit=20, control=control)
        assert result.status in ("unknown", "feasible", "optimal")


def test_run_folders(tmp_path):
    rules = tmp_path / "r.xlsx"
    shutil.copy(EXAMPLE, rules)
    a = new_run_folder(rules, "my run / v1", tmp_path / "runs")
    b = new_run_folder(rules, "my run / v1", tmp_path / "runs")
    assert a != b and a.name.endswith("my_run_v1") and (a / "rules.xlsx").exists()
    assert list_runs(tmp_path / "runs") == []  # no schedules yet
    (a / "schedule.xlsx").write_bytes(b"x")
    runs = list_runs(tmp_path / "runs")
    assert [r.folder for r in runs] == [a] and runs[0].name == "my_run_v1" and runs[0].created


def test_background_job(tmp_path):
    from wildflyer.template import write_template
    from test_solver import START, day

    src = write_template(tmp_path / "rules.xlsx", settings={"Season start": START, "Season end": day(13)},
                         teams=[("T1", "One", ""), ("T2", "Two", ""), ("T3", "Three", "")],
                         rules=[{"ID": "R1", "Type": "MATCHUP_GAMES", "Role": "home", "Min": 1, "Max": 1}])
    job = start_job(src, load(src).run, 10, tmp_path / "runs")
    job.wait(60)
    assert job.finished and job.error is None and job.result.has_schedule
    assert job.output.exists() and (job.folder / "rules.xlsx").exists()
    assert list_runs(tmp_path / "runs")[0].folder == job.folder


def test_app_page_checks_selected_file(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    shutil.copy(EXAMPLE, tmp_path / "season.xlsx")
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert at.selectbox[0].value == "season.xlsx"
    assert any("Ready to solve" in s.value for s in at.success)
    assert any(b.label == "▶ Solve" for b in at.button)


def test_app_page_stops_on_errors(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from wildflyer.template import write_template

    write_template(tmp_path / "broken.xlsx", settings={}, teams=[], rules=[])
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert any("must be fixed" in e.value for e in at.error)
    assert not any(b.label == "▶ Solve" for b in at.button)
