"""The rule catalog: every rule type a user can write, and what it accepts.

This is the single source of truth for rule types. The loader validates rows
against it and the template's Help tab is generated from it.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fields a rule row may fill. Keys match the Rules tab column headers (lowercased).
FIELDS = ("teams", "opponents", "role", "venues", "from", "to", "dates", "days",
          "min", "max", "n", "option")

ROLES = ("home", "away", "any")


@dataclass(frozen=True)
class FieldSpec:
    required: bool
    help: str


@dataclass(frozen=True)
class RuleSpec:
    name: str
    category: str
    summary: str
    fields: dict[str, FieldSpec]
    example: str
    options: tuple[str, ...] = ()
    option_default: str | None = None
    roles: tuple[str, ...] = ROLES
    soft_only: bool = False
    needs_min_or_max: bool = False
    single_team: bool = False  # Teams must name exactly one team
    single_opponent: bool = False
    single_venue: bool = False
    teams_default_all: bool = True  # blank Teams means ALL
    violation_unit: str = "occurrence"


def _f(required: bool, help: str) -> FieldSpec:
    return FieldSpec(required, help)


TEAMS = _f(False, "Teams the rule applies to (blank = ALL)")
OPPONENTS = _f(False, "Only count games against these opponents (blank = any)")
ROLE = _f(False, "home / away / any (blank = any)")
DATES_OPT = _f(False, "Only count these dates (blank = whole season)")
DAYS_OPT = _f(False, "Only count these days of week (blank = all)")

_SPECS = [
    # --- Season & volume -------------------------------------------------------
    RuleSpec(
        "LEAGUE_BLACKOUT", "Season & volume",
        "No games at all on the given dates.",
        {"dates": _f(True, "Dates with no games"), "days": DAYS_OPT},
        "Dates = 7/11-7/13", teams_default_all=False, violation_unit="game",
    ),
    RuleSpec(
        "SEASON_WINDOW", "Season & volume",
        "Each listed team's first (or last) game must fall within the given dates.",
        {"teams": TEAMS, "dates": _f(True, "Window the first/last game must fall in")},
        "Option = first, Dates = 6/12-6/15",
        options=("first", "last"), option_default="first", violation_unit="team",
    ),
    RuleSpec(
        "MATCHUP_GAMES", "Season & volume",
        "Number of games between each team and each opponent, checked pair by pair. "
        "Role = home counts games the team hosts the opponent.",
        {"teams": TEAMS, "opponents": OPPONENTS, "role": ROLE, "dates": DATES_OPT,
         "min": _f(False, "Minimum games per pair"), "max": _f(False, "Maximum games per pair")},
        "Teams = ALL, Opponents = ALL, Role = home, Min = 3, Max = 3",
        needs_min_or_max=True, violation_unit="game short/over, per pair",
    ),
    RuleSpec(
        "TEAM_GAMES", "Season & volume",
        "Number of games per team (optionally only home/away, within dates or days).",
        {"teams": TEAMS, "opponents": OPPONENTS, "role": ROLE, "dates": DATES_OPT, "days": DAYS_OPT,
         "min": _f(False, "Minimum games per team"), "max": _f(False, "Maximum games per team")},
        "Min = 30, Max = 30",
        needs_min_or_max=True, violation_unit="game short/over, per team",
    ),
    RuleSpec(
        "GAMES_PER_DAY", "Season & volume",
        "League-wide number of games on each matching date.",
        {"dates": DATES_OPT, "days": DAYS_OPT,
         "min": _f(False, "Minimum games per date"), "max": _f(False, "Maximum games per date")},
        "Days = Wed, Max = 1",
        needs_min_or_max=True, teams_default_all=False, violation_unit="game short/over, per date",
    ),
    # --- Availability & venues ---------------------------------------------------
    RuleSpec(
        "AVAILABILITY", "Availability & venues",
        "Where/when a team may play. must = the team plays (in Role) on every listed date; "
        "cannot = the team does not play (in Role) on listed dates; "
        "only = the team plays (in Role) only on listed dates. "
        "Venues narrows the rule to games at those venues (e.g. a home-stadium blackout "
        "that doesn't apply to games moved to a neutral site).",
        {"teams": TEAMS, "opponents": OPPONENTS, "role": ROLE, "venues": _f(False, "Only games at these venues"),
         "dates": _f(True, "Dates the rule refers to"), "days": DAYS_OPT},
        "Teams = UTA, Role = home, Option = cannot, Dates = 8/1-end",
        options=("must", "cannot", "only"), violation_unit="date",
    ),
    RuleSpec(
        "VENUE_OVERRIDE", "Availability & venues",
        "The team's home games on the listed dates are played at the given venue instead of "
        "its home venue. Does not by itself require a home game; combine with AVAILABILITY.",
        {"teams": TEAMS, "venues": _f(True, "The venue to play at"), "dates": _f(True, "Dates of the override")},
        "Teams = TEX, Venues = SAT, Dates = 8/12-8/14",
        single_venue=True, teams_default_all=False, violation_unit="game",
    ),
    RuleSpec(
        "FIXED_GAME", "Availability & venues",
        "A specific game on each listed date: Teams = home team, Opponents = away team.",
        {"teams": _f(True, "Home team"), "opponents": _f(True, "Away team"),
         "venues": _f(False, "Venue (blank = home team's venue)"), "dates": _f(True, "Date(s) of the game")},
        "Teams = CHI, Opponents = UTA, Dates = 7/4",
        single_team=True, single_opponent=True, single_venue=True, teams_default_all=False,
        violation_unit="game",
    ),
    # --- Sequence: opponents --------------------------------------------------------
    RuleSpec(
        "OPPONENT_BLOCK", "Sequence: opponents",
        "Games against the same opponent come in blocks. A block is a run of a team's games "
        "against one opponent with no game against anyone else in between (off days don't "
        "break a block). Min/Max = games per block; N = most off days allowed between "
        "consecutive games inside a block.",
        {"teams": TEAMS, "opponents": OPPONENTS, "dates": DATES_OPT,
         "min": _f(False, "Minimum games per block"), "max": _f(False, "Maximum games per block"),
         "n": _f(False, "Max off days inside a block (blank = no limit)")},
        "Min = 3, Max = 3, N = 1",
        needs_min_or_max=True, violation_unit="block",
    ),
    RuleSpec(
        "REMATCH_GAP", "Sequence: opponents",
        "Minimum days between the end of one block against an opponent and the start of the "
        "next block against the same opponent.",
        {"teams": TEAMS, "opponents": OPPONENTS, "n": _f(True, "Minimum days between blocks")},
        "N = 14", violation_unit="rematch",
    ),
    RuleSpec(
        "OPPONENT_CHANGE_REST", "Sequence: opponents",
        "Minimum off days between a team's last game against one opponent and its next game "
        "against a different opponent.",
        {"teams": TEAMS, "dates": DATES_OPT, "n": _f(True, "Minimum off days when switching opponents")},
        "N = 1", violation_unit="switch",
    ),
    # --- Sequence: locations & workload ------------------------------------------------
    RuleSpec(
        "TRAVEL_REST", "Sequence: locations & workload",
        "Minimum off days when a team's next game is at a different venue, for moves from a "
        "From venue to a To venue. From/To accept venue codes or any / home / away "
        "(home = the team's own home venue).",
        {"teams": TEAMS, "from": _f(True, "Venue(s) moved from"), "to": _f(True, "Venue(s) moved to"),
         "dates": DATES_OPT, "n": _f(True, "Minimum off days between the two games")},
        "From = TEX, To = CAR, N = 2", violation_unit="move",
    ),
    RuleSpec(
        "PREFERRED_TRANSITION", "Sequence: locations & workload",
        "When a team leaves a From venue for a different venue, its next venue should be a "
        "To venue.",
        {"teams": TEAMS, "role": ROLE, "from": _f(True, "Venue(s) left"), "to": _f(True, "Venue(s) to go to next")},
        "Role = away, From = PDX, To = UTA", violation_unit="move",
    ),
    RuleSpec(
        "HOME_AWAY_RUN", "Sequence: locations & workload",
        "Limits the length of a homestand (Role = home) or road trip (Role = away). "
        "Option = games counts consecutive games; days counts calendar days from first to "
        "last game of the run.",
        {"teams": TEAMS, "role": _f(True, "home or away"), "max": _f(True, "Maximum run length")},
        "Role = away, Option = days, Max = 14",
        options=("games", "days"), option_default="games", roles=("home", "away"),
        violation_unit="run",
    ),
    RuleSpec(
        "MAX_CONSECUTIVE_GAME_DAYS", "Sequence: locations & workload",
        "Maximum number of consecutive calendar days on which a team plays.",
        {"teams": TEAMS, "max": _f(True, "Maximum consecutive game days")},
        "Max = 4", violation_unit="day over",
    ),
    RuleSpec(
        "GAMES_IN_WINDOW", "Sequence: locations & workload",
        "Number of games a team plays per window. Option = rolling checks every N-day window; "
        "week checks each Mon-Sun calendar week.",
        {"teams": TEAMS, "role": ROLE, "dates": DATES_OPT, "n": _f(False, "Window length in days (rolling)"),
         "min": _f(False, "Minimum games per window"), "max": _f(False, "Maximum games per window")},
        "Option = rolling, N = 7, Max = 4",
        options=("rolling", "week"), option_default="rolling", needs_min_or_max=True,
        violation_unit="game short/over, per window",
    ),
    # --- Preferences ----------------------------------------------------------------
    RuleSpec(
        "DATE_PREFERENCE", "Preferences",
        "Favour (Option = prefer) or discourage (Option = avoid) games on matching dates. "
        "Each matching game earns or costs Weight. Teams/Role narrow which games count.",
        {"teams": TEAMS, "role": ROLE, "dates": DATES_OPT, "days": DAYS_OPT},
        "Option = prefer, Days = Fri-Sun, Weight = 5",
        options=("prefer", "avoid"), soft_only=True, violation_unit="game",
    ),
    RuleSpec(
        "BALANCE", "Preferences",
        "Keeps a count even across teams: counts each team's games matching the Role/Dates/Days "
        "filters; the gap between the highest and lowest team must be at most Max.",
        {"teams": TEAMS, "role": ROLE, "dates": DATES_OPT, "days": DAYS_OPT,
         "max": _f(True, "Maximum spread between teams")},
        "Role = home, Days = Fri-Sun, Max = 1", violation_unit="game over spread",
    ),
]

CATALOG: dict[str, RuleSpec] = {s.name: s for s in _SPECS}
