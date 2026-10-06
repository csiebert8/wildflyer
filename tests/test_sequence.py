"""Sequence rules (M3), verified with the independent checks in wildflyer.analysis."""

from collections import Counter

import pytest

from wildflyer.analysis import blocks, max_streak, moves, off_days_between, rematch_gaps, runs, sequence
from test_solver import R, day, make_run
from wildflyer.model import Location, Lock
from wildflyer.solver import solve

TEAMS = ("T1", "T2", "T3", "T4")
# Each team hosts each opponent twice: 12 games per team.
TWICE = R("MATCHUP_GAMES", id="RR", role="home", min=2, max=2)
PAIRS = R("OPPONENT_BLOCK", id="BLK", min=2, max=2)


def solved(rules, n_days=30, locks=()):
    result = solve(make_run(rules, n_days=n_days, locks=locks), time_limit=30, workers=8)
    assert result.has_schedule, result.status
    return result


def seqs(result):
    return {t: sequence(result.games, t) for t in TEAMS}


def loc(*hosts, kw=()):
    return Location(frozenset(hosts), frozenset(kw))


class TestOpponentBlock:
    def test_block_sizes(self):
        result = solved([TWICE, PAIRS])
        for s in seqs(result).values():
            assert {len(b) for b in blocks(s)} == {2}

    def test_range_of_sizes(self):
        result = solved([TWICE, R("OPPONENT_BLOCK", min=2, max=4)])
        for s in seqs(result).values():
            assert all(2 <= len(b) <= 4 for b in blocks(s))

    def test_no_gap_inside_block(self):
        result = solved([TWICE, R("OPPONENT_BLOCK", min=2, max=2, n=0)])
        for s in seqs(result).values():
            for b in blocks(s):
                assert all(off_days_between(a, c) == 0 for a, c in zip(b, b[1:]))

    def test_gap_limit_inside_block(self):
        thrice = R("MATCHUP_GAMES", id="RR3", role="home", min=3, max=3)
        result = solved([thrice, R("OPPONENT_BLOCK", min=3, max=3, n=1)], n_days=50)
        for s in seqs(result).values():
            for b in blocks(s):
                assert len(b) == 3
                assert all(off_days_between(a, c) <= 1 for a, c in zip(b, b[1:]))

    def test_soft_max_counts_extra_games(self):
        # T1 hosts T2 on three straight days; soft Max = 2 -> exactly one game beyond the limit.
        thrice = R("MATCHUP_GAMES", id="RR3", role="home", min=3, max=3)
        locks = [Lock(2 + i, day(i), "T1", "T2") for i in range(3)]
        result = solved([thrice, R("OPPONENT_BLOCK", hard=False, weight=4, teams={"T1"}, opponents={"T2"}, max=2)],
                        n_days=40, locks=locks)
        assert result.soft_cost == 4

    def test_home_and_away_are_separate_blocks(self):
        # T1 v T2: 2 games at T1 then 1 at T2 -> blocks of 2 and 1, not one block of 3.
        locks = [Lock(2, day(0), "T1", "T2"), Lock(3, day(1), "T1", "T2"), Lock(4, day(2), "T2", "T1"),
                 Lock(5, day(3), "T3", "T1")]
        rule = R("OPPONENT_BLOCK", hard=False, weight=4, teams={"T1"}, opponents={"T2"}, min=2)
        result = solved([TWICE, rule], locks=locks)
        assert any("block ending" in p.label and "at T2" in p.label for p in result.penalties)


def test_rematch_gap():
    result = solved([TWICE, PAIRS, R("REMATCH_GAP", n=8)], n_days=40)
    for s in seqs(result).values():
        assert min(rematch_gaps(s)) >= 8


def test_opponent_change_rest():
    result = solved([TWICE, PAIRS, R("OPPONENT_CHANGE_REST", n=1)], n_days=40)
    for s in seqs(result).values():
        for b1, b2 in zip(blocks(s), blocks(s)[1:]):
            if b1[0].opponent != b2[0].opponent:
                assert off_days_between(b1[-1], b2[0]) >= 1


class TestTravelRest:
    def test_any_move(self):
        result = solved([TWICE, PAIRS, R("TRAVEL_REST", from_loc=loc(kw=("any",)), to_loc=loc(kw=("any",)), n=1)],
                        n_days=40)
        for s in seqs(result).values():
            assert all(off_days_between(a, b) >= 1 for a, b in moves(s))

    def test_specific_moves(self):
        rule = R("TRAVEL_REST", from_loc=loc("T1"), to_loc=loc("T2"), n=3)
        result = solved([TWICE, PAIRS, rule], n_days=40)
        for s in seqs(result).values():
            assert all(off_days_between(a, b) >= 3 for a, b in moves(s) if (a.host, b.host) == ("T1", "T2"))

    def test_home_to_away_keyword(self):
        rule = R("TRAVEL_REST", from_loc=loc(kw=("home",)), to_loc=loc(kw=("away",)), n=2)
        result = solved([TWICE, PAIRS, rule], n_days=40)
        for t, s in seqs(result).items():
            assert all(off_days_between(a, b) >= 2 for a, b in moves(s) if a.home and not b.home)

    def test_staying_put_is_not_a_move(self):
        # T1 hosts T2 then T3 on consecutive days: T1 doesn't move, so no rest needed for T1.
        locks = [Lock(2, day(0), "T1", "T2"), Lock(3, day(1), "T1", "T3")]
        rule = R("TRAVEL_REST", teams={"T1"}, from_loc=loc(kw=("any",)), to_loc=loc(kw=("any",)), n=2)
        solved([TWICE, rule], locks=locks)

    def test_soft_penalised_once_per_move(self):
        # T2 plays at T1 on day 0 and at T3 on day 1: one move with no rest.
        locks = [Lock(2, day(0), "T1", "T2"), Lock(3, day(1), "T3", "T2")]
        rule = R("TRAVEL_REST", hard=False, weight=5, teams={"T2"}, from_loc=loc(kw=("any",)),
                 to_loc=loc(kw=("any",)), n=1)
        result = solved([TWICE, rule], locks=locks)
        assert result.soft_cost == 5 and len(result.penalties) == 1

    def test_hard_conflict_with_lock_is_infeasible(self):
        locks = [Lock(2, day(0), "T1", "T2"), Lock(3, day(1), "T3", "T2")]
        rule = R("TRAVEL_REST", teams={"T2"}, from_loc=loc(kw=("any",)), to_loc=loc(kw=("any",)), n=1)
        assert solve(make_run([TWICE, rule], n_days=30, locks=locks), time_limit=20).status == "infeasible"


def test_preferred_transition():
    rule = R("PREFERRED_TRANSITION", role="away", from_loc=loc("T1"), to_loc=loc("T2"))
    result = solved([TWICE, PAIRS, rule], n_days=40)
    for t, s in seqs(result).items():
        for a, b in moves(s):
            if a.host == "T1" and not a.home and b.host != "T2":
                pytest.fail(f"{t} left T1 for {b.host}")


class TestHomeAwayRun:
    def test_games(self):
        result = solved([TWICE, PAIRS, R("HOME_AWAY_RUN", role="home", option="games", max=2)])
        for s in seqs(result).values():
            assert max(len(r) for r in runs(s, True)) <= 2

    def test_days(self):
        result = solved([TWICE, PAIRS, R("HOME_AWAY_RUN", role="away", option="days", max=6)], n_days=40)
        for s in seqs(result).values():
            assert max((r[-1].date - r[0].date).days + 1 for r in runs(s, False)) <= 6


def test_max_consecutive_game_days():
    result = solved([TWICE, R("MAX_CONSECUTIVE_GAME_DAYS", max=2)])
    for s in seqs(result).values():
        assert max_streak(s) <= 2


class TestGamesInWindow:
    def test_rolling_max(self):
        result = solved([TWICE, R("GAMES_IN_WINDOW", option="rolling", n=7, max=3)], n_days=35)
        for s in seqs(result).values():
            dates = [a.date for a in s]
            for d in dates:
                assert sum(0 <= (x - d).days < 7 for x in dates) <= 3

    def test_week_max_and_min(self):
        # Season starts on a Tuesday (2027-06-01), so the first week is partial: Min doesn't apply there.
        result = solved([TWICE, R("GAMES_IN_WINDOW", option="week", min=2, max=3)], n_days=34)
        for s in seqs(result).values():
            weeks = Counter(a.date.isocalendar()[1] for a in s)
            assert max(weeks.values()) <= 3
            full_weeks = {day(i).isocalendar()[1] for i in range(6, 27)}
            assert all(weeks[w] >= 2 for w in full_weeks)


def test_block_is_one_location():
    """Regression: a 3-game series must not mix venues (e.g. 1 game away + 2 at home)."""
    thrice = R("MATCHUP_GAMES", id="RR3", role="home", min=3, max=3)
    result = solved([thrice, R("OPPONENT_BLOCK", min=3, max=3, n=1)], n_days=45)
    for t, s in seqs(result).items():
        bl = blocks(s)
        assert all(len(b) == 3 and len({a.host for a in b}) == 1 for b in bl), t
        assert len(bl) == 6  # 3 opponents x (home + away)


def test_rematch_gap_applies_between_home_and_away_series():
    """A home series straight after an away series vs the same opponent is a rematch."""
    thrice = R("MATCHUP_GAMES", id="RR3", role="home", min=3, max=3)
    rules = [thrice, R("OPPONENT_BLOCK", min=3, max=3, n=1), R("REMATCH_GAP", n=7)]
    result = solved(rules, n_days=60)
    for s in seqs(result).values():
        assert min(rematch_gaps(s)) >= 7
