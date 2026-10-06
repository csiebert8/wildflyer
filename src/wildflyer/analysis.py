"""Facts about a schedule computed directly from its game list.

Used for the Checks sheet and by tests: these don't use the solver's model, so
they also catch modeling mistakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .model import Game


@dataclass(frozen=True)
class Appearance:
    date: date
    opponent: str
    host: str
    home: bool


def sequence(games: list[Game], team: str) -> list[Appearance]:
    out = [Appearance(g.date, g.away if g.home == team else g.home, g.home, g.home == team)
           for g in games if team in (g.home, g.away)]
    return sorted(out, key=lambda a: a.date)


def blocks(seq: list[Appearance]) -> list[list[Appearance]]:
    """Runs of games against one opponent at one location (off days don't break a run)."""
    out: list[list[Appearance]] = []
    for a in seq:
        if out and out[-1][-1].opponent == a.opponent and out[-1][-1].host == a.host:
            out[-1].append(a)
        else:
            out.append([a])
    return out


def off_days_between(a: Appearance, b: Appearance) -> int:
    return (b.date - a.date).days - 1


def moves(seq: list[Appearance]) -> list[tuple[Appearance, Appearance]]:
    return [(a, b) for a, b in zip(seq, seq[1:]) if a.host != b.host]


def runs(seq: list[Appearance], home: bool) -> list[list[Appearance]]:
    out: list[list[Appearance]] = []
    prev = None
    for a in seq:
        if a.home == home:
            if prev is not None and prev.home == home:
                out[-1].append(a)
            else:
                out.append([a])
        prev = a
    return out


def max_streak(seq: list[Appearance]) -> int:
    best = streak = 0
    prev = None
    for a in seq:
        streak = streak + 1 if prev and (a.date - prev.date).days == 1 else 1
        best = max(best, streak)
        prev = a
    return best


def rematch_gaps(seq: list[Appearance]) -> list[int]:
    """Days from the last game of a block to the first game of the next block vs the same opponent."""
    last_block_end: dict[str, date] = {}
    gaps = []
    for b in blocks(seq):
        opp = b[0].opponent
        if opp in last_block_end:
            gaps.append((b[0].date - last_block_end[opp]).days)
        last_block_end[opp] = b[-1].date
    return gaps


def span_days(run_: list[Appearance]) -> int:
    """Calendar days from the first to the last game of a run, inclusive."""
    return (run_[-1].date - run_[0].date).days + 1


def compare(old: list[Game], new: list[Game]) -> tuple[list[Game], list[Game]]:
    """Games only in `old` (removed) and games only in `new` (added)."""
    old_set, new_set = set(old), set(new)
    removed = sorted(old_set - new_set, key=lambda g: (g.date, g.home))
    added = sorted(new_set - old_set, key=lambda g: (g.date, g.home))
    return removed, added


TEAM_SUMMARY_COLUMNS = ("Team", "Games", "Home", "Away", "Home Fri-Sun", "Longest homestand (days)",
                        "Longest road trip (days)", "Most game days in a row", "Moves",
                        "Fewest off days on a move", "Shortest rematch gap (days)")


def team_summary(games: list[Game], teams: list[str]) -> list[tuple]:
    """One row per team, in TEAM_SUMMARY_COLUMNS order."""
    rows = []
    for t in teams:
        seq = sequence(games, t)
        mv = moves(seq)
        rows.append((
            t, len(seq), sum(a.home for a in seq), sum(not a.home for a in seq),
            sum(a.home and a.date.weekday() >= 4 for a in seq),
            max((span_days(r) for r in runs(seq, True)), default=0),
            max((span_days(r) for r in runs(seq, False)), default=0),
            max_streak(seq), len(mv),
            min((off_days_between(a, b) for a, b in mv), default=None),
            min(rematch_gaps(seq), default=None),
        ))
    return rows
