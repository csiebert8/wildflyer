"""Build examples/ausl_2027.xlsx: the 2027 constraints document entered as rule rows.

This is the expressiveness acceptance test from SCOPE.md §9: every item in the
document is written with catalog rule types. Where the document is ambiguous,
the Note column records the interpretation chosen; edit the rows to change it.

Run: python scripts/make_example_2027.py
"""

from datetime import date
from pathlib import Path

from wildflyer.template import write_template

SETTINGS = {
    "Run name": "2027-example",
    "Season start": date(2027, 6, 12),
    "Season end": date(2027, 8, 15),
    "Time limit (seconds)": 300,
}

TEAMS = [
    ("CHI", "Chicago Bandits", "CHI", "76D6FF"),
    ("CAR", "Carolina Blaze", "CAR", "FF00FF"),
    ("OKC", "Oklahoma City Spark", "OKC", "0000FF"),
    ("UTA", "Utah Talons", "UTA", "274E13"),
    ("TEX", "Texas Volts", "TEX", "9900FF"),
    ("PDX", "Portland Cascade", "PDX", "B7E1CD"),
]

VENUES = [
    ("CHI", "Rosemont, Ill. (Parkway Bank Sports Complex)", "CHI"),
    ("CAR", "Durham, N.C. (Smith Family Stadium)", "CAR"),
    ("OKC", "Edmond, Okla. (Tom Heath Field)", "OKC"),
    ("UTA", "Salt Lake City, Utah (Dumke Family Stadium)", "UTA"),
    ("TEX", "Round Rock, Texas", "TEX"),
    ("PDX", "Portland, Ore.", "PDX"),
    ("SAT", "San Antonio, Texas (neutral site)", None),
    ("DBAP", "Durham Bulls Athletic Park (neutral site)", None),
]

RR_HOME = "6/25-27, 7/1-3, 7/15-17, 7/29-31, 8/12-14"
PDX_WINDOWS = "6/14-21, 6/28-7/15, 7/26-8/2, 8/9-8/16"


def rule(id, type, hard_soft="Hard", **kw):
    return {"ID": id, "Enabled": kw.pop("Enabled", "Y"), "Type": type, "Hard/Soft": hard_soft, **kw}


RULES = [
    # General structure
    rule("R01", "SEASON_WINDOW", Option="first", Dates="6/12-6/15",
         Note="Season begins 6/12-15 (read as: every team's first game falls in this window)"),
    rule("R02", "TEAM_GAMES", Min=30, Max=30, Note="30 games per team"),
    rule("R03", "MATCHUP_GAMES", Teams="ALL", Opponents="ALL", Role="home", Min=3, Max=3,
         Note="One 3-game home series vs each opponent (so one away series too)"),
    rule("R04", "OPPONENT_BLOCK", Min=3, Max=3, N=1,
         Note="Games vs an opponent come in 3-game series, at most 1 off day inside a series"),
    rule("R05", "REMATCH_GAP", N=14, Note="No series vs the same opponent within 2 weeks"),
    # Hard date restrictions
    rule("R10", "AVAILABILITY", Teams="TEX", Role="home", Option="must", Dates=RR_HOME,
         Note="Round Rock home dates"),
    rule("R11", "AVAILABILITY", Teams="TEX", Role="home", Option="only", Dates=RR_HOME,
         Note="...and no other home dates"),
    rule("R12", "VENUE_OVERRIDE", Teams="TEX", Venues="SAT", Dates="8/12-8/14", Note="8/12-14 in San Antonio"),
    rule("R13", "AVAILABILITY", Teams="CAR", Role="home", Option="must", Dates="8/12-8/14",
         Note="Durham home 8/12-14"),
    rule("R14", "VENUE_OVERRIDE", Teams="CAR", Venues="DBAP", Dates="8/12-8/14", Note="...at DBAP"),
    rule("R15", "AVAILABILITY", Teams="CAR", Role="home", Venues="CAR", Option="cannot",
         Dates="6/11-13, 6/21-22, 7/12-14, 7/23-25, 8/2-end",
         Note="Duke blackout dates (home stadium only; DBAP games unaffected)"),
    rule("R16", "AVAILABILITY", "Soft", Teams="CAR", Role="home", Venues="CAR", Option="cannot",
         Dates="6/23, 7/15", Weight=50, Note="Duke flex dates: avoid unless needed"),
    rule("R17", "AVAILABILITY", Teams="UTA", Role="home", Option="cannot", Dates="8/1-end",
         Note="No Utah home games in August"),
    rule("R18", "AVAILABILITY", Teams="ALL except CHI", Role="home", Option="cannot", Dates="7/11-7/15",
         Note="Only Chicago hosts 7/11-15 (All-Star Weekend travel)"),
    rule("R19", "AVAILABILITY", Teams="OKC", Role="home", Option="cannot", Dates="8/8-end",
         Note="TBD: assume no OKC home dates after 1st week of August"),
    rule("R20", "AVAILABILITY", Teams="PDX", Role="home", Option="only", Dates=PDX_WINDOWS,
         Note="Portland available windows (read as home windows)"),
    # Athlete recovery / travel
    rule("R30", "TRAVEL_REST", From="any", To="any", N=1,
         Note="Never travel and play the next day"),
    rule("R31", "TRAVEL_REST", "Soft", From="any", To="any", N=2, Weight=10,
         Note="2 off days on any move, soft"),
    rule("R32", "TRAVEL_REST", From="CAR", To="PDX, UTA", N=2,
         Note="Example long-distance moves: 2 off days, hard (edit pairs as needed)"),
    rule("R33", "TRAVEL_REST", From="PDX, UTA", To="CAR", N=2, Note="Example long-distance moves (reverse)"),
    rule("R34", "TRAVEL_REST", From="TEX, SAT", To="PDX", N=2, Note="Example long-distance moves"),
    rule("R35", "TRAVEL_REST", From="PDX", To="TEX, SAT", N=2, Note="Example long-distance moves (reverse)"),
    rule("R36", "MAX_CONSECUTIVE_GAME_DAYS", Max=4,
         Note="No more than 4 consecutive games (read as consecutive game days)"),
    rule("R37", "PREFERRED_TRANSITION", "Soft", Role="away", From="PDX", To="UTA", Weight=5,
         Note="Visitors play the Cascade and Talons back-to-back"),
    rule("R38", "PREFERRED_TRANSITION", "Soft", Role="away", From="UTA", To="PDX", Weight=5,
         Note="...in either order"),
    rule("R39", "HOME_AWAY_RUN", "Soft", Role="home", Option="days", Max=14, Weight=10,
         Note="Avoid homestands longer than 14 days"),
    rule("R40", "HOME_AWAY_RUN", "Soft", Role="away", Option="days", Max=14, Weight=10,
         Note="Avoid road trips longer than 14 days"),
    rule("R41", "GAMES_PER_DAY", "Soft", Days="Mon-Thu", Max=2, Weight=5,
         Note="Avoid 3 games on one day Mon-Thu"),
    # Revenue considerations
    rule("R50", "DATE_PREFERENCE", "Soft", Option="prefer", Days="Fri-Sun", Weight=3,
         Note="As many weekend (F/S/S) games as possible"),
    rule("R51", "BALANCE", "Soft", Role="home", Days="Fri-Sun", Max=1, Weight=5,
         Note="Similar number of home weekend games across teams"),
    rule("R52", "DATE_PREFERENCE", "Soft", Option="avoid", Dates="7/18-7/31", Weight=1,
         Note="Lighter slate July 18-31"),
    # Scenario toggles
    rule("R90", "GAMES_PER_DAY", Days="Wed", Max=1, Enabled="N",
         Note="Scenario: no more than 1 game on Wednesdays (set Enabled = Y to test)"),
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "examples" / "ausl_2027.xlsx"
    write_template(out, settings=SETTINGS, teams=TEAMS, venues=VENUES, rules=RULES)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
