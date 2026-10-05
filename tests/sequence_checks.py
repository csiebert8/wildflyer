"""Independent checks of sequence rules on a solved schedule (used by tests).

These recompute blocks, moves and runs directly from the game list, without
the solver's model, so they catch modeling mistakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from wildflyer.solver import Game


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
    out: list[list[Appearance]] = []
    for a in seq:
        if out and out[-1][-1].opponent == a.opponent:
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
