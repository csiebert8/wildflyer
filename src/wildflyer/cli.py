"""Command line entry point: `wildflyer template ...`, `wildflyer validate ...`."""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from .loader import load
from .template import write_template


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wildflyer", description="Sports league scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("template", help="write a blank input workbook")
    p.add_argument("path", help="where to write the .xlsx")

    p = sub.add_parser("validate", help="check an input workbook and list any problems")
    p.add_argument("path", help="input .xlsx")

    args = parser.parse_args(argv)
    if args.command == "template":
        print(f"Wrote {write_template(args.path)}")
        return 0
    return _validate(args.path)


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
