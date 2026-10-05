"""Scale check: a synthetic league with N teams playing each opponent home and away.

Run: python scripts/bench_scale.py [n_teams] [n_days] [time_limit]
"""

import sys
import time
from datetime import date, timedelta

from wildflyer.model import Rule, RunInput, Settings, Team
from wildflyer.solver import solve


def main(n_teams: int = 30, n_days: int = 150, time_limit: float = 120) -> None:
    codes = [f"T{i:02d}" for i in range(1, n_teams + 1)]
    teams = {c: Team(c, c, "4472C4") for c in codes}
    start = date(2027, 4, 1)
    all_teams = frozenset(codes)
    rules = [
        Rule("RR", "MATCHUP_GAMES", 2, True, teams=all_teams, role="home", min=1, max=1),
        Rule("DAY", "GAMES_PER_DAY", 3, True, max=n_teams // 2 - 2),
        Rule("OFF", "LEAGUE_BLACKOUT", 4, True, days=frozenset({0})),  # no Monday games
        Rule("W", "SEASON_WINDOW", 5, True, teams=all_teams, option="first",
             dates=frozenset(start + timedelta(i) for i in range(7))),
    ]
    run = RunInput(Settings(start, start + timedelta(n_days - 1)), teams, rules)
    t0 = time.monotonic()
    result = solve(run, time_limit=time_limit)
    print(f"{n_teams} teams, {n_days} days: {result.status}, {len(result.games)} games, "
          f"solve {result.wall_time:.1f}s, total {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    main(*(float(a) if i == 2 else int(a) for i, a in enumerate(sys.argv[1:])))
