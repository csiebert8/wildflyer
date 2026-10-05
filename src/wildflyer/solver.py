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

from .model import Rule, RunInput

# Soft weights may be decimals; CP-SAT needs integer objective coefficients.
WEIGHT_SCALE = 100


@dataclass(frozen=True)
class Game:
    date: date
    home: str
    away: str


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

    @property
    def has_schedule(self) -> bool:
        return self.status in ("optimal", "feasible")

    @property
    def soft_cost(self) -> float:
        return sum(p.cost for p in self.penalties)


class ScheduleModel:
    def __init__(self, run: RunInput):
        self.run = run
        self.m = cp_model.CpModel()
        self.dates = run.season_dates
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.days = range(len(self.dates))
        self.teams = list(run.teams)
        self.skipped: list[Rule] = []
        # (rule, label, linear expression counting violation units)
        self._soft_terms: list[tuple[Rule, str, cp_model.LinearExprT]] = []

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
            self.m.add(self.x[lock.home, lock.away, self.day_index[lock.date]] == 1)

        compilers: dict[str, Callable[[Rule], None]] = {
            "LEAGUE_BLACKOUT": self._league_blackout,
            "SEASON_WINDOW": self._season_window,
            "MATCHUP_GAMES": self._matchup_games,
            "TEAM_GAMES": self._team_games,
            "GAMES_PER_DAY": self._games_per_day,
            "AVAILABILITY": self._availability,
            "FIXED_GAME": self._fixed_game,
        }
        objective = []
        for rule in run.rules:
            compile_rule = compilers.get(rule.type)
            if compile_rule is None:
                self.skipped.append(rule)
                continue
            compile_rule(rule)
        for rule, _, expr in self._soft_terms:
            objective.append(round(rule.weight * WEIGHT_SCALE) * expr)
        if objective:
            self.m.minimize(sum(objective))

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
                self.m.add(expr >= lo)
            if hi is not None:
                self.m.add(expr <= hi)
            return
        if lo is not None and lo > 0:
            short = self.m.new_int_var(0, lo, f"short_{rule.id}")
            self.m.add(expr + short >= lo)
            self._soft_terms.append((rule, f"{label}: below minimum {lo}", short))
        if hi is not None and hi < upper:
            over = self.m.new_int_var(0, upper - hi, f"over_{rule.id}")
            self.m.add(expr - over <= hi)
            self._soft_terms.append((rule, f"{label}: above maximum {hi}", over))

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
                self.m.add(out_games == 0)
                self.m.add(in_games >= 1)
                continue
            missed = self.m.new_bool_var(f"window_{rule.id}_{t}")
            self.m.add(out_games <= len(outside) * missed)
            self.m.add(in_games >= 1 - missed)
            self._soft_terms.append((rule, f"{t} {what} game outside window", missed))

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
        result = SolveResult(status, skipped_rules=list(self.skipped), wall_time=elapsed)
        if status == "infeasible":
            result.message = "The hard rules contradict each other; no schedule satisfies all of them."
        elif status == "unknown":
            result.message = "No schedule found within the time limit (the rules may be contradictory)."
        elif status == "invalid":
            result.message = f"Internal model error: {self.m.validate()}"
        if not result.has_schedule:
            return result
        result.games = sorted(
            (Game(self.dates[i], h, a) for (h, a, i), v in self.x.items() if solver.boolean_value(v)),
            key=lambda g: (g.date, g.home),
        )
        for rule, label, expr in self._soft_terms:
            amount = int(solver.value(expr))
            if amount:
                result.penalties.append(Penalty(rule, label, amount))
        return result


def solve(run: RunInput, time_limit: float | None = None, workers: int | None = None,
          log: bool = False) -> SolveResult:
    return ScheduleModel(run).solve(time_limit, workers, log)
