"""AUSL Schedule Solver: local web app (Streamlit) on top of the wildflyer engine.

Start it with `wildflyer app` (or the "AUSL Schedule Solver.command" launcher). It
serves on localhost only: rules, schedules and runs never leave this computer.
"""

from __future__ import annotations

import base64
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

APP_NAME = "AUSL Schedule Solver"
ORANGE = "#F5831F"
LOGO = Path(__file__).with_name("assets") / "ausl_logo.png"
WORKDIR = Path.cwd()
ON_MAC = sys.platform == "darwin"
DAY_ABBR = ("M", "Tu", "W", "Th", "F", "Sa", "Su")
STATUS = {  # status -> (label, explanation, tone)
    "optimal": ("Best possible", "No better schedule exists under your rules.", "good"),
    "feasible": ("Valid schedule", "Meets every hard rule; the search stopped before proving it's the best.", "good"),
    "infeasible": ("No schedule possible", "The hard rules contradict each other.", "bad"),
    "unknown": ("No schedule found", "Nothing found in the time allowed. Try a longer time limit.", "bad"),
    "invalid": ("Internal error", "Please send this run to Claude.", "bad"),
}

st.set_page_config(page_title=APP_NAME, page_icon=str(LOGO), layout="wide")

CSS = f"""
<style>
  header[data-testid="stHeader"] {{ background: transparent; }}
  #MainMenu, footer {{ visibility: hidden; }}
  .block-container {{ max-width: 1240px; padding-top: 1.2rem; padding-bottom: 3rem; }}

  .app-header {{
    display: flex; align-items: center; gap: 18px;
    padding: 16px 24px; margin-bottom: 1.2rem; border-radius: 18px;
    background: linear-gradient(120deg, #0d0d0d 0%, #1f1f1f 70%, #2b2016 100%);
    box-shadow: 0 6px 20px rgba(0,0,0,.12); position: relative; overflow: hidden;
  }}
  .app-header::after {{
    content: ""; position: absolute; right: -60px; top: -60px; width: 220px; height: 220px;
    border-radius: 50%; background: radial-gradient(circle, rgba(245,131,31,.35), transparent 70%);
  }}
  .app-header img {{ height: 64px; background: #fff; border-radius: 14px; padding: 6px 8px; }}
  .app-header .title {{ color: #fff; font-size: 1.65rem; font-weight: 800; letter-spacing: -.01em; line-height: 1.1; }}
  .app-header .title span {{ color: {ORANGE}; }}
  .app-header .sub {{ color: #b9b9b9; font-size: .88rem; margin-top: 4px; }}

  .step {{ display: flex; align-items: center; gap: 12px; margin: 2px 0 10px; }}
  .step .num {{
    width: 30px; height: 30px; border-radius: 50%; flex: none;
    display: inline-flex; align-items: center; justify-content: center;
    background: #ececec; color: #555; font-weight: 800; font-size: .95rem;
  }}
  .step.active .num {{ background: {ORANGE}; color: #fff; box-shadow: 0 0 0 4px rgba(245,131,31,.18); }}
  .step.done .num {{ background: #111; color: #fff; }}
  .step .label {{ font-size: 1.12rem; font-weight: 750; color: #111; }}
  .step .hint {{ font-size: .85rem; color: #777; margin-left: auto; }}

  div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 16px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.05);
  }}
  div[data-testid="stMetric"] {{
    background: #f7f7f8; border-radius: 12px; padding: 12px 16px; border: 1px solid #efefef;
  }}
  div[data-testid="stMetricValue"] {{ font-weight: 750; }}
  .stButton > button, .stDownloadButton > button {{ border-radius: 10px; font-weight: 650; }}
  .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
  .stTabs [data-baseweb="tab"] {{ font-weight: 650; }}

  button[kind="primary"], [data-testid="stBaseButton-primary"] {{
    background: {ORANGE} !important; border-color: {ORANGE} !important; color: #fff !important;
  }}
  button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {{
    background: #e06f0c !important; border-color: #e06f0c !important;
  }}
  [data-testid="stProgress"] div[role="progressbar"] > div > div {{ background-color: {ORANGE} !important; }}
  .stTabs [aria-selected="true"] {{ color: {ORANGE} !important; }}
  .stTabs [data-baseweb="tab-highlight"] {{ background-color: {ORANGE} !important; }}

  .pill {{
    display: inline-block; padding: 4px 12px; border-radius: 999px; font-weight: 700; font-size: .85rem;
  }}
  .pill.good {{ background: #e7f6ec; color: #136c35; }}
  .pill.bad {{ background: #fdecea; color: #a1281b; }}
  .pill.warn {{ background: #fff3e6; color: #a2520b; }}
  .result-head {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }}
  .result-head .what {{ color: #666; font-size: .9rem; }}
  .muted {{ color: #777; font-size: .88rem; }}
  .conflict {{
    border-left: 4px solid #d93025; background: #fff6f5; padding: 8px 12px; border-radius: 8px; margin: 6px 0;
  }}
</style>
"""


@st.cache_resource
def _store() -> dict:
    """Process-wide state, so a running solve survives a page refresh."""
    return {"job": None}


STORE = _store()


# --- helpers -------------------------------------------------------------------------------


def logo_b64() -> str:
    return base64.b64encode(LOGO.read_bytes()).decode()


def step(num: int, label: str, state: str = "", hint: str = "") -> None:
    """Numbered step header. state: '' (upcoming), 'active' or 'done'."""
    mark = "✓" if state == "done" else str(num)
    hint_html = f'<span class="hint">{hint}</span>' if hint else ""
    st.markdown(f'<div class="step {state}"><span class="num">{mark}</span>'
                f'<span class="label">{label}</span>{hint_html}</div>', unsafe_allow_html=True)


def rules_files() -> list[Path]:
    """Excel files in the working folder and examples/, newest first."""
    files = [p for p in WORKDIR.glob("*.xlsx") if not p.name.startswith("~$")]
    files += sorted((WORKDIR / "examples").glob("*.xlsx"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def is_schedule(path: Path) -> bool:
    """Schedules written by the solver have a Grid sheet; rules workbooks don't."""
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
    st.dataframe(grid_frame(run, teams, games, dates), width="stretch")
    st.markdown('<span class="muted">Colored cell = home game vs that opponent (home team\'s color) · '
                '@XXX = away game at XXX</span>', unsafe_allow_html=True)


# --- page ----------------------------------------------------------------------------------

st.markdown(CSS, unsafe_allow_html=True)
st.markdown(f"""
<div class="app-header">
  <img src="data:image/png;base64,{logo_b64()}" alt="AUSL"/>
  <div>
    <div class="title">AUSL <span>Schedule Solver</span></div>
    <div class="sub">Build the best league schedule from your rules · runs privately on this computer</div>
  </div>
</div>
""", unsafe_allow_html=True)

job: Job | None = STORE["job"]
busy = job is not None and job.running
tab_new, tab_past = st.tabs(["New run", "Past runs & compare"])

with tab_new:
    # 1. Rules file -------------------------------------------------------------------------
    files = rules_files()
    rules_path: Path | None = None
    with st.container(border=True):
        step(1, "Rules file", "done" if files else "active", "Excel workbook with Settings, Teams and Rules")
        left, right = st.columns([3, 2], gap="large")
        with left:
            if files:
                labels = {str(p.relative_to(WORKDIR)): p for p in files}
                choice = st.selectbox("Rules workbook", list(labels), disabled=busy,
                                      help="Files in your folder, newest first. After editing in Excel, "
                                           "save and click Re-check.")
                rules_path = labels[choice]
                b1, b2, _ = st.columns([1, 1, 2])
                b1.button("↻ Re-check", disabled=busy, width="stretch",
                          help="Re-read the file after saving changes in Excel")
                if ON_MAC and b2.button("Open in Excel", disabled=busy, width="stretch"):
                    open_in_mac(rules_path)
            else:
                st.info("No Excel files in your folder yet. Upload one, or start from a blank template.")
        with right:
            uploaded = st.file_uploader("Add a rules file", type=["xlsx"], disabled=busy)
            if uploaded is not None:
                target = WORKDIR / Path(uploaded.name).name
                if not (target.exists() and target.read_bytes() == uploaded.getvalue()):
                    stem, n = target.stem, 2
                    while target.exists():
                        target = WORKDIR / f"{stem}_{n}.xlsx"
                        n += 1
                    target.write_bytes(uploaded.getvalue())
                    st.success(f"Saved as **{target.name}**. Choose it from the list.")
            buf = io.BytesIO()
            build_workbook().save(buf)
            st.download_button("Blank rules template", buf.getvalue(), "blank_rules.xlsx",
                               width="stretch")

    if rules_path is None:
        st.stop()

    # 2. Check ------------------------------------------------------------------------------
    checked = load(rules_path) if not is_schedule(rules_path) else None
    run = checked.run if checked else None
    with st.container(border=True):
        step(2, "Check", "done" if run else "active", rules_path.name)
        if checked is None:
            st.error("This looks like a schedule (output) file, not a rules file. Choose a rules workbook.")
        else:
            if checked.errors:
                st.error(f"**{len(checked.errors)} problem(s) to fix before solving.** Fix them in Excel, save, "
                         "then click **Re-check**.")
                st.dataframe(issues_frame(checked, Level.ERROR), width="stretch", hide_index=True)
            if run is not None:
                hard = sum(r.hard for r in run.rules)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Teams", len(run.teams))
                m2.metric("Season", f"{len(run.season_dates)} days",
                          f"{run.settings.season_start:%b %d} – {run.settings.season_end:%b %d}", delta_color="off")
                m3.metric("Rules", len(run.rules), f"{hard} hard · {len(run.rules) - hard} soft", delta_color="off")
                m4.metric("Locked games", len(run.locks))
                st.success("No problems found. Ready to solve.")
            if checked.warnings:
                with st.expander(f"{len(checked.warnings)} warning(s), which don't stop a run"):
                    st.dataframe(issues_frame(checked, Level.WARNING), width="stretch", hide_index=True)
    if run is None:
        st.stop()

    # 3. Solve ------------------------------------------------------------------------------
    with st.container(border=True):
        step(3, "Solve", "active" if not (job and job.finished) or busy else "done",
             "Longer searches usually find better schedules")
        c1, c2, _ = st.columns([1, 1, 2])
        time_limit = c1.number_input("Time limit (seconds)", min_value=10, max_value=3600, step=10,
                                     value=int(run.settings.time_limit_seconds), disabled=busy,
                                     help="You can always stop early and keep the best schedule found so far.")
        c2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if c2.button("▶ Solve", type="primary", disabled=busy, width="stretch"):
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
                st.info("No schedule satisfies every hard rule. Working out which rules conflict…")
            else:
                elapsed = min(c.elapsed, job.time_limit)
                st.progress(elapsed / job.time_limit if job.time_limit else 0.0,
                            text=f"Solving **{job.rules_path.name}** · {int(job.time_limit - elapsed)} s left")
                p1, p2, p3 = st.columns(3)
                p1.metric("Best soft cost so far", "—" if c.best_cost is None else f"{c.best_cost:g}",
                          help="Lower is better. It drops as better schedules are found.")
                p2.metric("Schedules found", c.solutions)
                p3.metric("Elapsed", f"{int(elapsed)} s")
                if c.solutions == 0:
                    st.markdown('<span class="muted">Searching for a first schedule that meets every hard '
                                'rule…</span>', unsafe_allow_html=True)
            if st.button("■ Stop and keep the best so far", disabled=c.stopped):
                job.stop()

        if busy:
            progress_panel()

    # 4. Result -----------------------------------------------------------------------------
    if job is not None and job.finished:
        with st.container(border=True):
            step(4, "Result", "done")
            if job.error:
                st.error("Something went wrong while solving. Please send this to Claude:")
                st.code(job.error)
            elif job.result is not None:
                res = job.result
                label, why, tone = STATUS[res.status]
                if res.has_schedule and res.penalties:
                    tone = "warn" if tone == "good" else tone
                st.markdown(f'<div class="result-head"><span class="pill {tone}">{label}</span>'
                            f'<span class="what">{job.rules_path.name} → '
                            f'<code>{job.folder.relative_to(WORKDIR)}</code></span></div>'
                            f'<div class="muted">{why} {res.message}</div>', unsafe_allow_html=True)
                for conflict in res.conflicts:
                    st.markdown(f'<div class="conflict">{conflict}</div>', unsafe_allow_html=True)
                if res.has_schedule:
                    r1, r2, r3, r4 = st.columns(4)
                    r1.metric("Games", len(res.games))
                    r2.metric("Soft cost", f"{res.soft_cost:g}", help="Total cost of broken soft rules")
                    r3.metric("Soft rules broken", len({p.rule.id for p in res.penalties}))
                    r4.metric("Solve time", f"{res.wall_time:.0f} s")
                if job.output and job.output.exists():
                    d1, d2, _ = st.columns([1, 1, 2])
                    d1.download_button("⬇ Download schedule" if res.has_schedule else "⬇ Download summary",
                                       job.output.read_bytes(), f"{job.folder.name}.xlsx",
                                       type="primary" if res.has_schedule else "secondary", width="stretch")
                    if ON_MAC and d2.button("Show in Finder", width="stretch"):
                        open_in_mac(job.output, reveal=True)
                if res.has_schedule:
                    t_grid, t_soft, t_rules, t_teams = st.tabs(
                        ["Schedule", "Soft rule violations", "Rules", "Team checks"])
                    with t_grid:
                        show_grid(job.run, res.games)
                    with t_soft:
                        if res.penalties:
                            st.dataframe(pd.DataFrame([{"Rule": p.rule.id, "Type": p.rule.type, "Where": p.label,
                                                        "Units": p.amount, "Cost": p.cost}
                                                       for p in res.penalties]),
                                         width="stretch", hide_index=True)
                        else:
                            st.success("Every soft rule was met.")
                    with t_rules:
                        units, cost = Counter(), Counter()
                        for p in res.penalties:
                            units[p.rule.id] += p.amount
                            cost[p.rule.id] += p.cost
                        st.dataframe(pd.DataFrame([{
                            "Rule": r.id, "Type": r.type, "Hard/Soft": "Hard" if r.hard else "Soft",
                            "Status": "Broken" if units[r.id] else "Met", "Units": units[r.id] or None,
                            "Cost": cost[r.id] or None, "Note": r.note} for r in res.rules]),
                            width="stretch", hide_index=True)
                    with t_teams:
                        st.dataframe(pd.DataFrame(analysis.team_summary(res.games, list(job.run.teams)),
                                                  columns=analysis.TEAM_SUMMARY_COLUMNS),
                                     width="stretch", hide_index=True)

with tab_past:
    history = list_runs(WORKDIR / RUNS_DIR)
    if not history:
        st.info("No runs yet. Your runs appear here after you solve.")
    else:
        labels = {r.label: r for r in history}
        with st.container(border=True):
            step(1, "Open a past run", "active", f"{len(history)} saved in {RUNS_DIR}/")
            h1, h2, h3 = st.columns([3, 1, 1])
            pick = labels[h1.selectbox("Run", list(labels), label_visibility="collapsed")]
            h2.download_button("⬇ Schedule", pick.schedule.read_bytes(), f"{pick.folder.name}.xlsx",
                               key="dl_past_schedule", width="stretch")
            if pick.rules.exists():
                h3.download_button("⬇ Rules used", pick.rules.read_bytes(), f"{pick.folder.name}_rules.xlsx",
                                   key="dl_past_rules", width="stretch")
            try:
                past_rules = load(pick.rules).run if pick.rules.exists() else None  # team colours and order
                show_grid(past_rules, read_schedule(pick.schedule))
            except ValueError as e:
                st.error(str(e))

        with st.container(border=True):
            step(2, "Compare two runs", "active", "Which games moved between them")
            if len(history) < 2:
                st.info("Make at least two runs to compare them.")
            else:
                k1, k2 = st.columns(2)
                old = labels[k1.selectbox("Earlier run", list(labels), index=1)]
                new = labels[k2.selectbox("Later run", list(labels), index=0)]
                try:
                    removed, added = analysis.compare(read_schedule(old.schedule), read_schedule(new.schedule))
                except ValueError as e:
                    st.error(str(e))
                else:
                    c1, c2 = st.columns(2)
                    c1.metric("Only in earlier run", len(removed))
                    c2.metric("Only in later run", len(added))
                    rows = [{"Date": g.date, "Day": DAY_ABBR[g.date.weekday()], "Matchup": f"{g.away} @ {g.home}",
                             "Change": "only in earlier run"} for g in removed]
                    rows += [{"Date": g.date, "Day": DAY_ABBR[g.date.weekday()], "Matchup": f"{g.away} @ {g.home}",
                              "Change": "only in later run"} for g in added]
                    if rows:
                        st.dataframe(pd.DataFrame(rows).sort_values("Date"), width="stretch",
                                     hide_index=True)
                    else:
                        st.success("The two schedules are identical.")
