"""Build and solve the scheduling model with OR-Tools CP-SAT.

Core decision: x[home, away, day] = 1 if `home` hosts `away` on that day.
Each enabled rule row compiles to constraints (hard) or penalty terms (soft).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ortools.sat.python import cp_model

from .model import Game, Lock, Rule, RunInput

__all__ = ["Game", "Penalty", "SolveResult", "ScheduleModel", "solve", "CHANGE_RULE_ID"]

# Soft weights may be decimals; CP-SAT needs integer objective coefficients.
WEIGHT_SCALE = 100
CHANGE_RULE_ID = "BASE"  # pseudo rule id for "keep base-run games" penalties
DIAGNOSE_SECONDS = 120  # budget for finding the conflicting hard rules


@dataclass
class _Soft:
    rule: Rule
    label: str
    expr: cp_model.LinearExprT
    move: tuple[str, str, int] | None = None  # (team, destination host, day) for move labels


@dataclass(frozen=True)
class Penalty:
    """A soft rule violation in the solved schedule."""

    rule: Rule
    label: str
    amount: int  # violation units

    @property
    def cost(self) -> float:
        return self.amount * self.rule.weight


@dataclass
class SolveResult:
    status: str  # optimal | feasible | infeasible | unknown | invalid
    games: list[Game] = field(default_factory=list)
    penalties: list[Penalty] = field(default_factory=list)
    skipped_rules: list[Rule] = field(default_factory=list)
    wall_time: float = 0.0
    message: str = ""
    conflicts: list[str] = field(default_factory=list)  # hard rules that can't all hold together
    rules: list[Rule] = field(default_factory=list)  # every rule applied, incl. the base-run rule

    @property
    def has_schedule(self) -> bool:
        return self.status in ("optimal", "feasible")

    @property
    def soft_cost(self) -> float:
        return sum(p.cost for p in self.penalties)


class ScheduleModel:
    def __init__(self, run: RunInput, diagnose: bool = False):
        """Build the model. With `diagnose`, every hard rule (and lock) is switched by its own
        literal so the solver can report which ones conflict."""
        self.run = run
        self.diagnose = diagnose
        self.guards: dict[str, cp_model.IntVar] = {}  # description -> on/off literal
        self._guard: cp_model.IntVar | None = None
        self.m = cp_model.CpModel()
        self.dates = run.season_dates
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.days = range(len(self.dates))
        self.teams = list(run.teams)
        self.skipped: list[Rule] = []
        self._cache: dict[str, dict] = {}
        self._soft_terms: list[_Soft] = []
        self.rules = list(run.rules)

        self.x: dict[tuple[str, str, int], cp_model.IntVar] = {}
        for h in self.teams:
            for a in self.teams:
                if h != a:
                    for i in self.days:
                        self.x[h, a, i] = self.m.new_bool_var(f"x_{h}_{a}_{i}")

        # Per-team daily state. A team plays at most one game per day.
        self.home: dict[tuple[str, int], cp_model.IntVar] = {}
        self.away: dict[tuple[str, int], cp_model.IntVar] = {}
        self.plays: dict[tuple[str, int], cp_model.IntVar] = {}
        for t in self.teams:
            others = [o for o in self.teams if o != t]
            for i in self.days:
                h = self.home[t, i] = self.m.new_bool_var(f"home_{t}_{i}")
                a = self.away[t, i] = self.m.new_bool_var(f"away_{t}_{i}")
                p = self.plays[t, i] = self.m.new_bool_var(f"plays_{t}_{i}")
                self.m.add(h == sum(self.x[t, o, i] for o in others))
                self.m.add(a == sum(self.x[o, t, i] for o in others))
                self.m.add(p == h + a)

        for lock in run.locks:
            if lock.date not in self.day_index:
                continue
            self._guard = self._new_guard(_lock_description(lock))
            self._hard(self.m.add(self.x[lock.home, lock.away, self.day_index[lock.date]] == 1))
        self._guard = None

        compilers = self.compilers()
        for rule in run.rules:
            compile_rule = compilers.get(rule.type)
            if compile_rule is None:
                self.skipped.append(rule)
                continue
            self._guard = self._new_guard(_rule_description(rule)) if rule.hard else None
            compile_rule(rule)
        self._guard = None
        self._freeze_before_cutoff()
        self._keep_base_games()
        if not diagnose:
            objective = [round(t.rule.weight * WEIGHT_SCALE) * t.expr for t in self._soft_terms]
            if objective:
                self.m.minimize(sum(objective))

    def compilers(self) -> dict[str, Callable[[Rule], None]]:
        """Rule type -> method that adds the rule to the model."""
        return {
            "LEAGUE_BLACKOUT": self._league_blackout,
            "SEASON_WINDOW": self._season_window,
            "MATCHUP_GAMES": self._matchup_games,
            "TEAM_GAMES": self._team_games,
            "GAMES_PER_DAY": self._games_per_day,
            "AVAILABILITY": self._availability,
            "FIXED_GAME": self._fixed_game,
            "OPPONENT_BLOCK": self._opponent_block,
            "REMATCH_GAP": self._rematch_gap,
            "OPPONENT_CHANGE_REST": self._opponent_change_rest,
            "TRAVEL_REST": self._travel_rest,
            "PREFERRED_TRANSITION": self._preferred_transition,
            "HOME_AWAY_RUN": self._home_away_run,
            "MAX_CONSECUTIVE_GAME_DAYS": self._max_consecutive_game_days,
            "GAMES_IN_WINDOW": self._games_in_window,
            "DATE_PREFERENCE": self._date_preference,
            "BALANCE": self._balance,
        }

    # --- hard-rule switches (diagnose mode) -------------------------------------------

    def _new_guard(self, description: str) -> cp_model.IntVar | None:
        if not self.diagnose:
            return None
        if description not in self.guards:
            self.guards[description] = self.m.new_bool_var(f"guard_{len(self.guards)}")
        return self.guards[description]

    def _hard(self, constraint: cp_model.Constraint) -> None:
        """Mark a constraint as belonging to the hard rule being compiled."""
        if self._guard is not None:
            constraint.only_enforce_if(self._guard)

    def _guard_lits(self) -> list:
        return [self._guard] if self._guard is not None else []

    # --- helpers ------------------------------------------------------------------

    def _rule_days(self, rule: Rule) -> list[int]:
        return [i for i, d in enumerate(self.dates) if rule.applies_on(d)]

    def _opponents(self, rule: Rule, team: str) -> list[str]:
        return [o for o in (rule.opponents or self.teams) if o != team]

    def _indicator(self, rule: Rule, team: str, i: int) -> cp_model.LinearExprT:
        """1 if `team` plays on day i in the rule's Role (and vs its Opponents filter)."""
        if not rule.opponents:
            return {"home": self.home, "away": self.away}.get(rule.role, self.plays)[team, i]
        opps = self._opponents(rule, team)
        terms = []
        if rule.role in ("home", "any"):
            terms += [self.x[team, o, i] for o in opps]
        if rule.role in ("away", "any"):
            terms += [self.x[o, team, i] for o in opps]
        return sum(terms)

    def _bound(self, rule: Rule, expr: cp_model.LinearExprT, upper: int, label: str,
               lo: int | None = None, hi: int | None = None) -> None:
        """Require lo <= expr <= hi; `upper` is the largest value expr can take."""
        if rule.hard:
            if lo is not None:
                self._hard(self.m.add(expr >= lo))
            if hi is not None:
                self._hard(self.m.add(expr <= hi))
            return
        if lo is not None and lo > 0:
            short = self.m.new_int_var(0, lo, f"short_{rule.id}")
            self.m.add(expr + short >= lo)
            self._soft_terms.append(_Soft(rule, f"{label}: below minimum {lo}", short))
        if hi is not None and hi < upper:
            over = self.m.new_int_var(0, upper - hi, f"over_{rule.id}")
            self.m.add(expr - over <= hi)
            self._soft_terms.append(_Soft(rule, f"{label}: above maximum {hi}", over))

    # --- rule compilers -------------------------------------------------------------

    def _league_blackout(self, rule: Rule) -> None:
        for i in self._rule_days(rule):
            games = [self.x[h, a, i] for h in self.teams for a in self.teams if h != a]
            self._bound(rule, sum(games), len(self.teams) // 2, f"games on {self.dates[i]}", hi=0)

    def _season_window(self, rule: Rule) -> None:
        window = sorted(self.day_index[d] for d in rule.dates if d in self.day_index)
        if not window:
            self.skipped.append(rule)
            return
        first = rule.option == "first"
        outside = range(0, window[0]) if first else range(window[-1] + 1, len(self.dates))
        what = "first" if first else "last"
        for t in self.teams:
            out_games = sum(self.plays[t, i] for i in outside)
            in_games = sum(self.plays[t, i] for i in window)
            if rule.hard:
                self._hard(self.m.add(out_games == 0))
                self._hard(self.m.add(in_games >= 1))
                continue
            missed = self.m.new_bool_var(f"window_{rule.id}_{t}")
            self.m.add(out_games <= len(outside) * missed)
            self.m.add(in_games >= 1 - missed)
            self._soft_terms.append(_Soft(rule, f"{t} {what} game outside window", missed))

    def _matchup_games(self, rule: Rule) -> None:
        days = self._rule_days(rule)
        done: set[frozenset[str]] = set()
        for t in sorted(rule.teams):
            for o in self._opponents(rule, t):
                if rule.role == "any":
                    if frozenset((t, o)) in done:
                        continue
                    done.add(frozenset((t, o)))
                    games = [self.x[t, o, i] for i in days] + [self.x[o, t, i] for i in days]
                    label = f"{t} vs {o}"
                elif rule.role == "home":
                    games, label = [self.x[t, o, i] for i in days], f"{t} hosting {o}"
                else:
                    games, label = [self.x[o, t, i] for i in days], f"{t} at {o}"
                self._bound(rule, sum(games), len(games), label, rule.min, rule.max)

    def _team_games(self, rule: Rule) -> None:
        days = self._rule_days(rule)
        for t in sorted(rule.teams):
            games = sum(self._indicator(rule, t, i) for i in days)
            self._bound(rule, games, len(days), f"{t} games", rule.min, rule.max)

    def _games_per_day(self, rule: Rule) -> None:
        for i in self._rule_days(rule):
            games = sum(self.x[h, a, i] for h in self.teams for a in self.teams if h != a)
            self._bound(rule, games, len(self.teams) // 2, f"games on {self.dates[i]}", rule.min, rule.max)

    def _availability(self, rule: Rule) -> None:
        listed = set(self._rule_days(rule))
        role = "" if rule.role == "any" else f" {rule.role}"
        for t in sorted(rule.teams):
            for i in self.days:
                d = self.dates[i]
                if rule.option == "must" and i in listed:
                    self._bound(rule, self._indicator(rule, t, i), 1, f"{t} not playing{role} on {d}", lo=1)
                elif rule.option == "cannot" and i in listed:
                    self._bound(rule, self._indicator(rule, t, i), 1, f"{t} playing{role} on {d}", hi=0)
                elif rule.option == "only" and i not in listed:
                    self._bound(rule, self._indicator(rule, t, i), 1, f"{t} playing{role} on {d}", hi=0)

    def _fixed_game(self, rule: Rule) -> None:
        (home,), (away,) = rule.teams, rule.opponents
        for d in sorted(rule.dates):
            if d in self.day_index:
                self._bound(rule, self.x[home, away, self.day_index[d]], 1,
                            f"{away} @ {home} on {d} not played", lo=1)

    # --- sequence state (built on first use) -----------------------------------------
    #
    # A team's games form a sequence with off days in between. Sequence rules are
    # expressed with per-day state that carries forward across off days:
    #   last_at[t, h, i]   t's most recent game (on or before day i) was hosted by h
    #   last_vs[t, o, i]   t's most recent game (on or before day i) was against o
    #   off[t, i]          consecutive off days ending on day i (0 if t plays on i)

    def _vs(self, t: str, o: str, i: int) -> cp_model.IntVar:
        """Bool: t plays o (either venue) on day i."""
        cache = self._cache.setdefault("vs", {})
        key = (min(t, o), max(t, o), i)
        if key not in cache:
            v = cache[key] = self.m.new_bool_var(f"vs_{key[0]}_{key[1]}_{i}")
            self.m.add(v == self.x[t, o, i] + self.x[o, t, i])
        return cache[key]

    def _at(self, t: str, h: str, i: int) -> cp_model.IntVar:
        """Bool: t plays on day i at h's location (h hosting)."""
        return self.home[t, i] if h == t else self.x[h, t, i]

    def _carry(self, name: str, t: str, event: Callable[[int], cp_model.LinearExprT]) -> list[cp_model.IntVar]:
        """c[i] = 1 if t's most recent game on or before day i satisfied `event`."""
        out = []
        for i in self.days:
            e, p = event(i), self.plays[t, i]
            c = self.m.new_bool_var(f"{name}_{i}")
            if i == 0:
                self.m.add(c == e)
            else:
                prev = out[-1]
                self.m.add(c >= e)
                self.m.add(c >= prev - p)
                self.m.add(c <= e + prev)
                self.m.add(c <= e + 1 - p)
            out.append(c)
        return out

    def _last_at(self, t: str, h: str, i: int) -> cp_model.IntVar:
        cache = self._cache.setdefault("last_at", {})
        if (t, h) not in cache:
            cache[t, h] = self._carry(f"lastat_{t}_{h}", t, lambda i: self._at(t, h, i))
        return cache[t, h][i]

    def _last_vs(self, t: str, o: str, i: int) -> cp_model.IntVar:
        cache = self._cache.setdefault("last_vs", {})
        if (t, o) not in cache:
            cache[t, o] = self._carry(f"lastvs_{t}_{o}", t, lambda i: self._vs(t, o, i))
        return cache[t, o][i]

    def _off(self, t: str, i: int) -> cp_model.IntVar:
        cache = self._cache.setdefault("off", {})
        if t not in cache:
            seq = []
            for j in self.days:
                v = self.m.new_int_var(0, len(self.dates), f"off_{t}_{j}")
                self.m.add(v == 0).only_enforce_if(self.plays[t, j])
                self.m.add(v == (seq[-1] + 1 if seq else 1)).only_enforce_if(~self.plays[t, j])
                seq.append(v)
            cache[t] = seq
        return cache[t][i]

    def _played_before(self, t: str, i: int) -> cp_model.LinearExprT:
        """1 if t has played at least once on or before day i."""
        return sum(self._last_at(t, h, i) for h in self.teams)

    def _counter(self, name: str, inc: cp_model.IntVar, reset: list, t: str) -> list[cp_model.IntVar]:
        """Counts `inc` days; resets to 0 on days t plays with all `reset` literals true;
        carries over off days."""
        seq = []
        for i in self.days:
            v = self.m.new_int_var(0, len(self.dates), f"{name}_{i}")
            prev = seq[-1] if seq else 0
            self.m.add(v == prev + 1).only_enforce_if(inc[i])
            self.m.add(v == 0).only_enforce_if([self.plays[t, i]] + [r[i] for r in reset])
            self.m.add(v == prev).only_enforce_if(~self.plays[t, i])
            seq.append(v)
        return seq

    def _enforce(self, rule: Rule, build: Callable[[], cp_model.Constraint], lits: list, label: str,
                 move: tuple[str, str, int] | None = None) -> None:
        """Add constraint `build()` when all `lits` hold; for soft rules allow breaking it at a cost."""
        if rule.hard:
            build().only_enforce_if(lits + self._guard_lits())
            return
        broken = self.m.new_bool_var(f"broken_{rule.id}")
        build().only_enforce_if(lits + [~broken])
        self._soft_terms.append(_Soft(rule, label, broken, move))

    def _hosts(self, loc, t: str) -> set[str]:
        hosts = set(loc.hosts)
        if "any" in loc.keywords:
            hosts |= set(self.teams)
        if "home" in loc.keywords:
            hosts.add(t)
        if "away" in loc.keywords:
            hosts |= set(self.teams) - {t}
        return hosts

    # --- sequence rules ------------------------------------------------------------------

    # A block is a run of a team's games against one opponent at one location (host), with no
    # other game in between. Off days don't break a block; a change of host does.

    def _game_at(self, t: str, o: str, h: str, i: int) -> cp_model.IntVar:
        """Bool: t plays o on day i, hosted by h (h is t or o)."""
        return self.x[t, o, i] if h == t else self.x[o, t, i]

    def _last_game_at(self, t: str, o: str, h: str, i: int) -> cp_model.IntVar:
        """Bool: t's most recent game (on or before day i) was against o, hosted by h."""
        cache = self._cache.setdefault("last_game_at", {})
        if (t, o, h) not in cache:
            cache[t, o, h] = self._carry(f"lastgame_{t}_{o}_{h}", t, lambda i: self._game_at(t, o, h, i))
        return cache[t, o, h][i]

    def _opponent_block(self, rule: Rule) -> None:
        for t in sorted(rule.teams):
            for o in self._opponents(rule, t):
                for h in (t, o):
                    where = "home" if h == t else f"at {o}"
                    game = [self._game_at(t, o, h, i) for i in self.days]
                    # Games so far in the current block (0 once t has played any other game).
                    count = self._counter(f"blk_{t}_{o}_{h}", game, [[~g for g in game]], t)
                    for i in self.days:
                        d = self.dates[i]
                        if rule.max is not None:
                            self._enforce(rule, lambda i=i, c=count: self.m.add(c[i] <= rule.max), [game[i]],
                                          f"{t} vs {o} ({where}): game {rule.max + 1}+ of a block on {d}")
                        if i == 0:
                            continue
                        in_block = self._last_game_at(t, o, h, i - 1)
                        if rule.min is not None and rule.min > 1:
                            # The block ended on day i: t played a different game.
                            self._enforce(rule, lambda i=i, c=count: self.m.add(c[i - 1] >= rule.min),
                                          [self.plays[t, i], ~game[i], in_block],
                                          f"{t} vs {o} ({where}): block ending before {d} shorter than "
                                          f"{rule.min}")
                        if rule.n is not None:
                            self._enforce(rule, lambda i=i: self.m.add(self._off(t, i - 1) <= rule.n),
                                          [game[i], in_block],
                                          f"{t} vs {o} ({where}): more than {rule.n} off days inside block "
                                          f"before {d}")
                    if rule.min is not None and rule.min > 1:
                        last = len(self.dates) - 1
                        self._enforce(rule, lambda c=count: self.m.add(c[last] >= rule.min),
                                      [self._last_game_at(t, o, h, last)],
                                      f"{t} vs {o} ({where}): season-ending block shorter than {rule.min}")

    def _rematch_gap(self, rule: Rule) -> None:
        n = rule.n
        for t in sorted(rule.teams):
            for o in self._opponents(rule, t):
                # since[i] = days since t's last game vs o (any location), capped at n.
                since = []
                for i in self.days:
                    v = self.m.new_int_var(0, n, f"since_{t}_{o}_{i}")
                    vs = self._vs(t, o, i)
                    self.m.add(v == 0).only_enforce_if(vs)
                    if since:
                        step = self.m.new_int_var(0, n, f"step_{t}_{o}_{i}")
                        self.m.add_min_equality(step, [since[-1] + 1, n])
                        self.m.add(v == step).only_enforce_if(~vs)
                    else:
                        self.m.add(v == n).only_enforce_if(~vs)
                    since.append(v)
                for j in range(1, len(self.dates)):
                    for h in (t, o):
                        # A new block vs o (hosted by h) starts on day j: t's previous game vs o
                        # must be at least n days back.
                        self._enforce(rule, lambda j=j: self.m.add(since[j - 1] + 1 >= n),
                                      [self._game_at(t, o, h, j), ~self._last_game_at(t, o, h, j - 1)],
                                      f"{t} vs {o}: rematch on {self.dates[j]} within {n} days")

    def _opponent_change_rest(self, rule: Rule) -> None:
        days = set(self._rule_days(rule))
        for t in sorted(rule.teams):
            for o in self._opponents(rule, t):
                for j in range(1, len(self.dates)):
                    if j not in days:
                        continue
                    # t plays o on day j after last playing someone else.
                    switched = self.m.new_bool_var(f"switch_{t}_{o}_{j}")
                    self.m.add(switched >= self._vs(t, o, j) - self._last_vs(t, o, j - 1)
                               + self._played_before(t, j - 1) - 1)
                    self._enforce(rule, lambda j=j: self.m.add(self._off(t, j - 1) >= rule.n), [switched],
                                  f"{t}: fewer than {rule.n} off days before playing {o} on {self.dates[j]}")

    def _travel_rest(self, rule: Rule) -> None:
        days = set(self._rule_days(rule))
        for t in sorted(rule.teams):
            origins, dests = self._hosts(rule.from_loc, t), self._hosts(rule.to_loc, t)
            for j in range(1, len(self.dates)):
                if j not in days:
                    continue
                for b in sorted(dests):
                    froms = [a for a in origins if a != b]
                    if not froms:
                        continue
                    moved = self.m.new_bool_var(f"move_{rule.id}_{t}_{b}_{j}")
                    self.m.add(moved >= self._at(t, b, j) + sum(self._last_at(t, a, j - 1) for a in froms) - 1)
                    self._enforce(rule, lambda j=j: self.m.add(self._off(t, j - 1) >= rule.n), [moved],
                                  f"fewer than {rule.n} off days", move=(t, b, j))

    def _preferred_transition(self, rule: Rule) -> None:
        for t in sorted(rule.teams):
            origins = self._hosts(rule.from_loc, t)
            if rule.role == "home":
                origins &= {t}
            elif rule.role == "away":
                origins -= {t}
            dests = self._hosts(rule.to_loc, t)
            for j in range(1, len(self.dates)):
                for b in self.teams:
                    froms = [a for a in origins if a != b]
                    if b in dests or not froms:
                        continue
                    left = sum(self._last_at(t, a, j - 1) for a in froms) + self._at(t, b, j)
                    if rule.hard:
                        self._hard(self.m.add(left <= 1))
                    else:
                        wrong = self.m.new_bool_var(f"pref_{rule.id}_{t}_{b}_{j}")
                        self.m.add(left <= 1 + wrong)
                        wanted = "/".join(sorted(dests))
                        self._soft_terms.append(_Soft(rule, f"next stop should have been {wanted}", wrong,
                                                      move=(t, b, j)))

    def _home_away_run(self, rule: Rule) -> None:
        home = rule.role == "home"
        for t in sorted(rule.teams):
            mine = [(self.home if home else self.away)[t, i] for i in self.days]
            other = [(self.away if home else self.home)[t, i] for i in self.days]
            if rule.option == "games":
                length = self._counter(f"run_{rule.id}_{t}", mine, [other], t)
                limit = rule.max
            else:
                # Days since the first game of the current run (counts off days too).
                length = []
                for i in self.days:
                    v = self.m.new_int_var(0, len(self.dates), f"span_{rule.id}_{t}_{i}")
                    if i == 0:
                        self.m.add(v == 0)
                    else:
                        prev = length[-1]
                        # cont: t's previous game was of the same kind, so day i extends the run.
                        prev_home = self._last_at(t, t, i - 1)
                        cont = self.m.new_bool_var(f"cont_{rule.id}_{t}_{i}")
                        self.m.add(cont == (prev_home if home else self._played_before(t, i - 1) - prev_home))
                        self.m.add(v == prev + 1).only_enforce_if([mine[i], cont])
                        self.m.add(v == 0).only_enforce_if([mine[i], ~cont])
                        self.m.add(v == 0).only_enforce_if(other[i])
                        self.m.add(v == prev + 1).only_enforce_if(~self.plays[t, i])
                    length.append(v)
                limit = rule.max - 1  # span is inclusive: first and last game days both count
            what = "homestand" if home else "road trip"
            for i in self.days:
                self._enforce(rule, lambda i=i: self.m.add(length[i] <= limit), [mine[i]],
                              f"{t}: {what} too long on {self.dates[i]}")

    def _max_consecutive_game_days(self, rule: Rule) -> None:
        span = rule.max + 1
        for t in sorted(rule.teams):
            for i in range(len(self.dates) - span + 1):
                window = sum(self.plays[t, k] for k in range(i, i + span))
                self._bound(rule, window, span, f"{t}: {span} straight game days from {self.dates[i]}",
                            hi=rule.max)

    def _games_in_window(self, rule: Rule) -> None:
        counted = set(self._rule_days(rule))
        if rule.option == "week":
            weeks: dict[tuple[int, int], list[int]] = {}
            for i, d in enumerate(self.dates):
                weeks.setdefault(tuple(d.isocalendar())[:2], []).append(i)
            windows = list(weeks.values())
        else:
            windows = [list(range(i, i + rule.n)) for i in range(len(self.dates) - rule.n + 1)]
        for t in sorted(rule.teams):
            for window in windows:
                games = sum(self._indicator(rule, t, i) for i in window if i in counted)
                full = len(window) == (7 if rule.option == "week" else rule.n)
                label = f"{t}: games {self.dates[window[0]]} to {self.dates[window[-1]]}"
                self._bound(rule, games, len(window), label, rule.min if full else None, rule.max)

    # --- preferences --------------------------------------------------------------------

    def _games_for(self, rule: Rule, i: int) -> list[cp_model.IntVar]:
        """Games on day i involving the rule's Teams in its Role (each game counted once)."""
        out = []
        for h in self.teams:
            for a in self.teams:
                if h == a:
                    continue
                if rule.role == "home":
                    hit = h in rule.teams
                elif rule.role == "away":
                    hit = a in rule.teams
                else:
                    hit = h in rule.teams or a in rule.teams
                if hit:
                    out.append(self.x[h, a, i])
        return out

    def _date_preference(self, rule: Rule) -> None:
        listed = set(self._rule_days(rule))
        if rule.option == "prefer":
            counted = [g for i in self.days if i not in listed for g in self._games_for(rule, i)]
            label = "games not on the preferred dates/days"
        else:
            counted = [g for i in listed for g in self._games_for(rule, i)]
            label = "games on the avoided dates/days"
        if counted:
            total = self.m.new_int_var(0, len(counted), f"pref_{rule.id}")
            self.m.add(total == sum(counted))
            self._soft_terms.append(_Soft(rule, label, total))

    def _balance(self, rule: Rule) -> None:
        days = self._rule_days(rule)
        teams = sorted(rule.teams)
        if len(teams) < 2:
            return
        hi = self.m.new_int_var(0, len(days), f"bal_hi_{rule.id}")
        lo = self.m.new_int_var(0, len(days), f"bal_lo_{rule.id}")
        for t in teams:
            count = sum(self._indicator(rule, t, i) for i in days)
            self.m.add(count <= hi)
            self.m.add(count >= lo)
        if rule.hard:
            self._hard(self.m.add(hi - lo <= rule.max))
        else:
            over = self.m.new_int_var(0, len(days), f"bal_over_{rule.id}")
            self.m.add(hi - lo - over <= rule.max)
            self._soft_terms.append(_Soft(rule, f"gap between teams above {rule.max}", over))

    def _freeze_before_cutoff(self) -> None:
        """Settings "Lock base before": the base run's games before the cutoff are locked (as Locks),
        and no other games may be added before it."""
        cutoff = self.run.settings.lock_base_before
        if not cutoff or not self.run.base_games:
            return
        keep = {(g.home, g.away, self.day_index[g.date]) for g in self.run.base_games if g.date in self.day_index}
        self._guard = self._new_guard(f"Lock base before {cutoff}: no new games before that date")
        for (h, a, i), v in self.x.items():
            if self.dates[i] < cutoff and (h, a, i) not in keep:
                self._hard(self.m.add(v == 0))
        self._guard = None

    def _keep_base_games(self) -> None:
        """Soft: keep the base run's games (Settings: Base run + Change weight)."""
        weight = self.run.settings.change_weight
        if not self.run.base_games or weight <= 0:
            return
        rule = Rule(id=CHANGE_RULE_ID, type="KEEP_BASE_GAMES", row=0, hard=False, weight=weight,
                    note=f"Keep games from base run {self.run.settings.base_run}")
        self.rules.append(rule)
        for g in self.run.base_games:
            if g.date in self.day_index and (g.home, g.away, self.day_index[g.date]) in self.x:
                kept = self.x[g.home, g.away, self.day_index[g.date]]
                self._soft_terms.append(_Soft(rule, f"{g.away} @ {g.home} on {g.date} moved", 1 - kept))

    # --- solving ----------------------------------------------------------------------

    def solve(self, time_limit: float | None = None, workers: int | None = None,
              log: bool = False) -> SolveResult:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit or self.run.settings.time_limit_seconds)
        solver.parameters.num_workers = workers or min(8, os.cpu_count() or 1)
        solver.parameters.log_search_progress = log
        started = time.monotonic()
        code = solver.solve(self.m)
        elapsed = time.monotonic() - started
        status = {
            cp_model.OPTIMAL: "optimal",
            cp_model.FEASIBLE: "feasible",
            cp_model.INFEASIBLE: "infeasible",
            cp_model.MODEL_INVALID: "invalid",
        }.get(code, "unknown")
        result = SolveResult(status, skipped_rules=list(self.skipped), wall_time=elapsed, rules=self.rules)
        if status == "infeasible":
            result.message = "The hard rules contradict each other; no schedule satisfies all of them."
        elif status == "unknown":
            result.message = ("No schedule found within the time limit. Try a longer time limit; if that "
                              "doesn't help, the hard rules may be contradictory.")
        elif status == "invalid":
            result.message = f"Internal model error: {self.m.validate()}"
        if not result.has_schedule:
            return result
        result.games = sorted(
            (Game(self.dates[i], h, a) for (h, a, i), v in self.x.items() if solver.boolean_value(v)),
            key=lambda g: (g.date, g.home),
        )
        hosts = {(t, g.date): g.home for g in result.games for t in (g.home, g.away)}
        for term in self._soft_terms:
            amount = int(solver.value(term.expr))
            if amount:
                result.penalties.append(Penalty(term.rule, self._describe(term, hosts), amount))
        return result

    def _describe(self, term: _Soft, hosts: dict[tuple[str, date], str]) -> str:
        if term.move is None:
            return term.label
        t, b, j = term.move
        origin = next((hosts[t, self.dates[i]] for i in range(j - 1, -1, -1) if (t, self.dates[i]) in hosts), "?")
        return f"{t}: {origin} → {b} on {self.dates[j]}: {term.label}"

    def find_conflicts(self, time_budget: float = DIAGNOSE_SECONDS) -> list[str] | None:
        """In diagnose mode: a small set of hard rules (and locks) that can't all hold.

        Solves with every hard rule switched on as an assumption; CP-SAT then reports a subset
        of assumptions that is already contradictory. Re-solving with just that subset usually
        shrinks it further. Returns None if nothing was found within the time budget.
        """
        assert self.diagnose, "build the model with diagnose=True"
        deadline = time.monotonic() + time_budget
        by_index = {lit.index: name for name, lit in self.guards.items()}
        active = list(self.guards)
        found = None
        for _ in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                break
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = remaining
            solver.parameters.num_workers = min(8, os.cpu_count() or 1)
            self.m.clear_assumptions()
            self.m.add_assumptions([self.guards[n] for n in active])
            if solver.solve(self.m) != cp_model.INFEASIBLE:
                break
            core = [by_index[i] for i in solver.sufficient_assumptions_for_infeasibility() if i in by_index]
            if not core:
                break
            found = core
            if len(core) == len(active):
                break
            active = core
        self.m.clear_assumptions()
        return found


def _rule_description(rule: Rule) -> str:
    text = f"{rule.id} ({rule.type}, Rules row {rule.row})"
    return f"{text}: {rule.note}" if rule.note else text


def _lock_description(lock: Lock) -> str:
    where = "base run lock" if lock.from_base else f"Locks row {lock.row}"
    return f"{where}: {lock.away} @ {lock.home} on {lock.date}"


def solve(run: RunInput, time_limit: float | None = None, workers: int | None = None,
          log: bool = False, diagnose: bool = True) -> SolveResult:
    """Solve `run`. If the hard rules contradict each other and `diagnose` is set, also work out
    which rules conflict (result.conflicts)."""
    result = ScheduleModel(run).solve(time_limit, workers, log)
    if result.status == "infeasible" and diagnose:
        conflicts = ScheduleModel(run, diagnose=True).find_conflicts()
        if conflicts:
            result.conflicts = conflicts
            result.message = ("The hard rules contradict each other. These rules can't all hold at once; "
                              "change, disable or soften at least one of them.")
    return result
