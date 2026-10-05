"""Validated, solver-ready representation of a run's inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum


class Level(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """A validation problem, pinned to a sheet/row/field where possible."""

    level: Level
    sheet: str
    message: str
    row: int | None = None
    rule_id: str | None = None
    field: str | None = None

    def __str__(self) -> str:
        where = self.sheet
        if self.row is not None:
            where += f" row {self.row}"
        if self.rule_id:
            where += f" [{self.rule_id}]"
        if self.field:
            where += f" ({self.field})"
        return f"{self.level.value.upper()}: {where}: {self.message}"


@dataclass(frozen=True)
class Team:
    code: str
    name: str
    color: str  # 6-digit hex, no '#'


@dataclass(frozen=True)
class Settings:
    season_start: date
    season_end: date
    run_name: str = ""
    time_limit_seconds: int = 300
    base_run: str | None = None
    change_weight: float = 0.0  # soft cost per game differing from base run


@dataclass(frozen=True)
class Location:
    """A From/To location selector for transition rules.

    Every game is played at the home team's location, so a location is named by
    the hosting team's code. `hosts` holds explicit team codes; the keywords
    expand per team at solve time: `home` = the team's own home games, `away` =
    games hosted by anyone else, `any` = every game.
    """

    hosts: frozenset[str] = frozenset()
    keywords: frozenset[str] = frozenset()  # subset of {"any", "home", "away"}


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    row: int
    hard: bool
    weight: float = 0.0
    teams: frozenset[str] = frozenset()
    opponents: frozenset[str] = frozenset()
    role: str = "any"  # home | away | any
    from_loc: Location | None = None
    to_loc: Location | None = None
    dates: frozenset[date] = frozenset()  # empty = whole season
    days: frozenset[int] = frozenset()  # 0=Mon..6=Sun; empty = all days
    min: int | None = None
    max: int | None = None
    n: int | None = None
    option: str | None = None
    note: str = ""

    def applies_on(self, d: date) -> bool:
        """True if `d` passes both the Dates and Days-of-week filters."""
        return (not self.dates or d in self.dates) and (not self.days or d.weekday() in self.days)


@dataclass(frozen=True)
class Lock:
    row: int
    date: date
    home: str
    away: str


@dataclass
class RunInput:
    settings: Settings
    teams: dict[str, Team]
    rules: list[Rule]
    locks: list[Lock] = field(default_factory=list)

    @property
    def season_dates(self) -> list[date]:
        days = (self.settings.season_end - self.settings.season_start).days
        return [self.settings.season_start + timedelta(i) for i in range(days + 1)]
