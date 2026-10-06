"""Command line entry point: `wildflyer template | validate | solve | compare`."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .loader import load
from .template import write_template


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wildflyer", description="Sports league scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("template", help="write a blank input workbook")
    p.add_argument("path", help="where to write the .xlsx")

    p = sub.add_parser("validate", help="check an input workbook and list any problems")
    p.add_argument("path", help="input .xlsx")

    p = sub.add_parser("solve", help="generate a schedule from an input workbook")
    p.add_argument("path", help="input .xlsx")
    p.add_argument("-o", "--output", help="output .xlsx (default: a new folder runs/<date-time>_<run name>/ "
                                          "holding schedule.xlsx and a copy of the rules)")
    p.add_argument("--time-limit", type=float, help="seconds to search (overrides the Settings sheet)")
    p.add_argument("--log", action="store_true", help="show solver progress")

    p = sub.add_parser("compare", help="list the games that differ between two schedules")
    p.add_argument("old", help="earlier schedule .xlsx")
    p.add_argument("new", help="later schedule .xlsx")

    args = parser.parse_args(argv)
    if args.command == "compare":
        return _compare(args.old, args.new)
    if args.command == "template":
        print(f"Wrote {write_template(args.path)}")
        return 0
    if args.command == "solve":
        return _solve(args.path, args.output, args.time_limit, args.log)
    return _validate(args.path)


def _solve(path: str, output: str | None, time_limit: float | None, log: bool) -> int:
    from .output import write_output
    from .solver import solve

    result = load(path)
    for issue in result.issues:
        print(issue)
    if result.run is None:
        print(f"\n{len(result.errors)} error(s); fix them and try again.")
        return 1
    run = result.run
    if output:
        out = Path(output)
    else:
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", run.settings.run_name or Path(path).stem)
        folder = Path("runs") / f"{datetime.now():%Y-%m-%d_%H%M%S}_{name}"
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, folder / "rules.xlsx")
        out = folder / "schedule.xlsx"
    limit = time_limit or run.settings.time_limit_seconds
    print(f"Solving {len(run.teams)} teams over {len(run.season_dates)} days "
          f"with {len(run.rules)} rules (time limit {limit:g}s)...")
    solved = solve(run, time_limit=limit, log=log)
    for rule in solved.skipped_rules:
        print(f"  not applied (not supported yet): {rule.id} {rule.type}")
    print(f"Status: {solved.status} in {solved.wall_time:.1f}s")
    if solved.message:
        print(solved.message)
    for conflict in solved.conflicts:
        print(f"  - {conflict}")
    if solved.has_schedule:
        print(f"{len(solved.games)} games, soft cost {solved.soft_cost:g}")
        for p in solved.penalties:
            print(f"  {p.rule.id}: {p.label} (cost {p.cost:g})")
    print(f"Wrote {write_output(out, run, solved, path)}")
    return 0 if solved.has_schedule else 2


def _compare(old: str, new: str) -> int:
    from .analysis import compare
    from .loader import read_schedule

    try:
        before, after = read_schedule(old), read_schedule(new)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    removed, added = compare(before, after)
    print(f"{old}: {len(before)} games; {new}: {len(after)} games")
    print(f"{len(removed)} game(s) only in {old}, {len(added)} only in {new}\n")
    rows = [(g, "-") for g in removed] + [(g, "+") for g in added]
    for g, sign in sorted(rows, key=lambda r: (r[0].date, r[1])):
        print(f"  {sign} {g.date:%a %Y-%m-%d}  {g.away} @ {g.home}")
    if rows:
        print(f"\n- = only in {old}   + = only in {new}")
    return 0


def _validate(path: str) -> int:
    result = load(path)
    for issue in result.issues:
        print(issue)
    if result.run is not None:
        run = result.run
        s = run.settings
        types = Counter(r.type for r in run.rules)
        hard = sum(r.hard for r in run.rules)
        print(f"\n{len(run.teams)} teams, season {s.season_start} to "
              f"{s.season_end} ({len(run.season_dates)} days)")
        print(f"{len(run.rules)} enabled rules ({hard} hard, {len(run.rules) - hard} soft), "
              f"{len(run.locks)} locked games")
        for name, count in sorted(types.items()):
            print(f"  {name}: {count}")
    print(f"\n{len(result.errors)} error(s), {len(result.warnings)} warning(s)")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
