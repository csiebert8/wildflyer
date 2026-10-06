"""Wildflyer local web app (Streamlit).

Start it with `wildflyer app` (or the Wildflyer.command launcher). It serves on
localhost only: rules, schedules and runs never leave this computer.
"""

from __future__ import annotations

import io
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from wildflyer import analysis
from wildflyer.jobs import Job, start_job
from wildflyer.loader import LoadResult, load, read_schedule
from wildflyer.model import Game, Level, RunInput
from wildflyer.output import text_color
from wildflyer.runs import RUNS_DIR, list_runs
from wildflyer.template import build_workbook

WORKDIR = Path.cwd()
ON_MAC = sys.platform == "darwin"
DAY_ABBR = ("M", "Tu", "W", "Th", "F", "Sa", "Su")
STATUS_TEXT = {
    "optimal": "Best possible schedule under your rules",
    "feasible": "Valid schedule (time ran out before proving it's the best possible)",
    "infeasible": "No schedule possible",
    "unknown": "No schedule found",
    "invalid": "Internal error",
}

st.set_page_config(page_title="Wildflyer", page_icon="📅", layout="wide")


@st.cache_resource
def _store() -> dict:
    """Process-wide state, so a running solve survives a page refresh."""
    return {"job": None}


STORE = _store()


# --- helpers -------------------------------------------------------------------------------


def rules_files() -> list[Path]:
    """Excel files in the wildflyer folder and examples/, newest first."""
    files = [p for p in WORKDIR.glob("*.xlsx") if not p.name.startswith("~$")]
    files += sorted((WORKDIR / "examples").glob("*.xlsx"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def is_schedule(path: Path) -> bool:
    """Schedules written by wildflyer have a Grid sheet; rules workbooks have a Rules sheet first."""
    try:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True)
        names = wb.sheetnames
        wb.close()
        return "Grid" in names
    except Exception:
        return False


def open_in_mac(path: Path, reveal: bool = False) -> None:
    subprocess.run(["open", "-R", str(path)] if reveal else ["open", str(path)], check=False)


def issues_frame(result: LoadResult, level) -> pd.DataFrame:
    rows = [{"Sheet": i.sheet, "Row": i.row, "Rule": i.rule_id, "Column": i.field, "Problem": i.message}
            for i in result.issues if i.level is level]
    return pd.DataFrame(rows)


def grid_frame(run: RunInput | None, teams: list[str], games: list[Game], dates: list[date]):
    """Team x date grid, styled like the Excel Grid sheet."""
    colors = {t: run.teams[t].color for t in teams} if run else {}
    cols = [f"{DAY_ABBR[d.weekday()]} {d.month}/{d.day}" for d in dates]
    col_of = dict(zip(dates, cols))
    df = pd.DataFrame("", index=teams, columns=cols)
    style = pd.DataFrame("", index=teams, columns=cols)
    for g in games:
        if g.date not in col_of:
            continue
        c = col_of[g.date]
        df.loc[g.home, c] = g.away
        df.loc[g.away, c] = f"@{g.home}"
        fill = colors.get(g.home, "D9D9D9")
        style.loc[g.home, c] = f"background-color: #{fill}; color: #{text_color(fill)}; font-weight: 600"
    return df.style.apply(lambda _: style, axis=None)


def show_grid(run: RunInput | None, games: list[Game]) -> None:
    if not games:
        return
    teams = list(run.teams) if run else sorted({t for g in games for t in (g.home, g.away)})
    if run:
        dates = run.season_dates
    else:
        first, last = min(g.date for g in games), max(g.date for g in games)
        dates = [date.fromordinal(o) for o in range(first.toordinal(), last.toordinal() + 1)]
    st.dataframe(grid_frame(run, teams, games, dates), use_container_width=True)
    st.caption("Colored cell = home game vs that opponent (in the home team's color) · @XXX = away game at XXX")


# --- page ----------------------------------------------------------------------------------


st.title("📅 Wildflyer league scheduler")
st.caption(f"Working folder: `{WORKDIR}` · runs are saved in `{WORKDIR / RUNS_DIR}`")

job: Job | None = STORE["job"]
busy = job is not None and job.running

# 1. Rules file -------------------------------------------------------------------------------
st.header("1 · Rules file")
files = rules_files()
left, right = st.columns([3, 2])
with left:
    if files:
        labels = {str(p.relative_to(WORKDIR)): p for p in files}
        choice = st.selectbox("Choose a rules workbook from your wildflyer folder", list(labels), disabled=busy,
                              help="Newest first. After editing the file in Excel, save it and click Re-check.")
        rules_path = labels[choice]
    else:
        rules_path = None
        st.info("No Excel files in the wildflyer folder yet. Upload one or download a blank template.")
with right:
    uploaded = st.file_uploader("…or add a rules file to the folder", type=["xlsx"], disabled=busy)
    if uploaded is not None:
        target = WORKDIR / Path(uploaded.name).name
        if target.exists() and target.read_bytes() == uploaded.getvalue():
            pass
        else:
            stem, n = target.stem, 2
            while target.exists():
                target = WORKDIR / f"{stem}_{n}.xlsx"
                n += 1
            target.write_bytes(uploaded.getvalue())
            st.success(f"Saved as {target.name}; choose it in the list.")
    buf = io.BytesIO()
    build_workbook().save(buf)
    st.download_button("Download a blank rules template", buf.getvalue(), "blank_rules.xlsx")

if rules_path is None:
    st.stop()

b1, b2, _ = st.columns([1, 1, 4])
b1.button("🔄 Re-check file", disabled=busy, help="Re-read the file after saving changes in Excel")
if ON_MAC and b2.button("Open in Excel", disabled=busy):
    open_in_mac(rules_path)

# 2. Check ------------------------------------------------------------------------------------
st.header("2 · Check")
if is_schedule(rules_path):
    st.error("This looks like a schedule (output) file, not a rules file. Choose a rules workbook.")
    st.stop()
checked = load(rules_path)

if checked.errors:
    st.error(f"{len(checked.errors)} problem(s) must be fixed before solving. Fix them in Excel, save, "
             "then click **Re-check file**.")
    st.dataframe(issues_frame(checked, Level.ERROR), use_container_width=True, hide_index=True)
if checked.warnings:
    with st.expander(f"{len(checked.warnings)} warning(s) (these don't stop a run)"):
        st.dataframe(issues_frame(checked, Level.WARNING), use_container_width=True, hide_index=True)
run = checked.run
if run is None:
    st.stop()

hard = sum(r.hard for r in run.rules)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Teams", len(run.teams))
m2.metric("Season", f"{len(run.season_dates)} days", f"{run.settings.season_start:%b %d} – {run.settings.season_end:%b %d}",
          delta_color="off")
m3.metric("Rules", len(run.rules), f"{hard} hard · {len(run.rules) - hard} soft", delta_color="off")
m4.metric("Locked games", len(run.locks))
if not checked.errors:
    st.success("No problems found. Ready to solve.")

# 3. Solve ------------------------------------------------------------------------------------
st.header("3 · Solve")
c1, c2 = st.columns([1, 3])
time_limit = c1.number_input("Time limit (seconds)", min_value=10, max_value=3600, step=10,
                             value=int(run.settings.time_limit_seconds), disabled=busy,
                             help="Longer searches usually find better schedules. "
                                  "You can stop early and keep the best found so far.")
c2.write("")
c2.write("")
if c2.button("▶ Solve", type="primary", disabled=busy):
    STORE["job"] = start_job(rules_path, run, float(time_limit), WORKDIR / RUNS_DIR)
    st.rerun()


@st.fragment(run_every=1)
def progress_panel() -> None:
    job: Job | None = STORE["job"]
    if job is None:
        return
    if not job.running:
        st.rerun(scope="app")
    c = job.control
    if c.phase == "diagnosing":
        st.info("No schedule satisfies all hard rules. Working out which rules conflict…")
    else:
        elapsed = min(c.elapsed, job.time_limit)
        st.progress(elapsed / job.time_limit if job.time_limit else 0.0,
                    text=f"Solving **{job.rules_path.name}** · {int(job.time_limit - elapsed)} s left")
        p1, p2 = st.columns(2)
        p1.metric("Best soft cost so far", "—" if c.best_cost is None else f"{c.best_cost:g}",
                  help="Lower is better. It drops as the solver finds better schedules.")
        p2.metric("Schedules found", c.solutions)
        if c.solutions == 0:
            st.caption("Searching for a first schedule that meets every hard rule…")
    if st.button("⏹ Stop and keep the best so far", disabled=c.stopped):
        job.stop()


if busy:
    progress_panel()

# 4. Results ----------------------------------------------------------------------------------
if job is not None and job.finished:
    st.header("4 · Result")
    if job.error:
        st.error("Something went wrong while solving. Please send this to Claude:")
        st.code(job.error)
    elif job.result is not None:
        res = job.result
        text = STATUS_TEXT[res.status]
        (st.success if res.has_schedule and not res.penalties else st.warning if res.has_schedule
         else st.error)(f"**{text}** · {job.rules_path.name} → `{job.folder.relative_to(WORKDIR)}`")
        if res.message:
            st.write(res.message)
        if res.conflicts:
            st.write("**These hard rules can't all hold at once** (change, disable or soften one of them):")
            for conflict in res.conflicts:
                st.write(f"- {conflict}")
        if res.has_schedule:
            r1, r2, r3 = st.columns(3)
            r1.metric("Games", len(res.games))
            r2.metric("Soft cost", f"{res.soft_cost:g}")
            r3.metric("Solve time", f"{res.wall_time:.0f} s")
        if job.output and job.output.exists():
            d1, d2, _ = st.columns([1, 1, 3])
            d1.download_button("⬇ Download schedule", job.output.read_bytes(),
                               f"{job.folder.name}.xlsx", type="primary")
            if ON_MAC and d2.button("Show in Finder"):
                open_in_mac(job.output, reveal=True)
        if res.has_schedule:
            t_grid, t_soft, t_rules, t_teams = st.tabs(["Schedule", "Soft rule violations", "Rules", "Team checks"])
            with t_grid:
                show_grid(job.run, res.games)
            with t_soft:
                if res.penalties:
                    st.dataframe(pd.DataFrame([{"Rule": p.rule.id, "Type": p.rule.type, "Where": p.label,
                                                "Units": p.amount, "Cost": p.cost} for p in res.penalties]),
                                 use_container_width=True, hide_index=True)
                else:
                    st.write("Every soft rule was met.")
            with t_rules:
                units, cost = Counter(), Counter()
                for p in res.penalties:
                    units[p.rule.id] += p.amount
                    cost[p.rule.id] += p.cost
                st.dataframe(pd.DataFrame([{
                    "Rule": r.id, "Type": r.type, "Hard/Soft": "Hard" if r.hard else "Soft",
                    "Status": "Broken" if units[r.id] else "Met", "Units": units[r.id] or None,
                    "Cost": cost[r.id] or None, "Note": r.note} for r in res.rules]),
                    use_container_width=True, hide_index=True)
            with t_teams:
                st.dataframe(pd.DataFrame(analysis.team_summary(res.games, list(job.run.teams)),
                                          columns=analysis.TEAM_SUMMARY_COLUMNS),
                             use_container_width=True, hide_index=True)

# 5. Past runs --------------------------------------------------------------------------------
st.header("Past runs")
history = list_runs(WORKDIR / RUNS_DIR)
if not history:
    st.write("No runs yet.")
else:
    labels = {r.label: r for r in history}
    h1, h2 = st.columns([3, 2])
    with h1:
        pick = labels[st.selectbox("Open a past run", list(labels))]
    with h2:
        st.write("")
        st.write("")
        e1, e2 = st.columns(2)
        e1.download_button("⬇ Schedule", pick.schedule.read_bytes(), f"{pick.folder.name}.xlsx",
                           key="dl_past_schedule")
        if pick.rules.exists():
            e2.download_button("⬇ Rules used", pick.rules.read_bytes(), f"{pick.folder.name}_rules.xlsx",
                               key="dl_past_rules")
    with st.expander("Preview this run's schedule"):
        try:
            show_grid(None, read_schedule(pick.schedule))
        except ValueError as e:
            st.error(str(e))

    st.subheader("Compare two runs")
    if len(history) < 2:
        st.write("Make at least two runs to compare them.")
    else:
        k1, k2 = st.columns(2)
        old = labels[k1.selectbox("Earlier run", list(labels), index=1)]
        new = labels[k2.selectbox("Later run", list(labels), index=0)]
        try:
            removed, added = analysis.compare(read_schedule(old.schedule), read_schedule(new.schedule))
        except ValueError as e:
            st.error(str(e))
        else:
            st.write(f"**{len(removed)}** game(s) only in the earlier run · **{len(added)}** only in the later run")
            rows = [{"Date": g.date, "Day": DAY_ABBR[g.date.weekday()], "Matchup": f"{g.away} @ {g.home}",
                     "Change": "only in earlier run"} for g in removed]
            rows += [{"Date": g.date, "Day": DAY_ABBR[g.date.weekday()], "Matchup": f"{g.away} @ {g.home}",
                      "Change": "only in later run"} for g in added]
            if rows:
                st.dataframe(pd.DataFrame(rows).sort_values("Date"), use_container_width=True, hide_index=True)
