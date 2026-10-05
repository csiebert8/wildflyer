# Wildflyer

A constraint-based sports league scheduler. You describe a league and a set of
hard and soft rules in an Excel workbook, and Wildflyer finds the best schedule
it can. See [SCOPE.md](SCOPE.md) for the full MVP scope.

**Status:** M2. Input validation and solving for season/volume and
availability rules, locks, and soft rules. Sequence rules (opponent blocks,
rematch gaps, travel rest, homestand/road-trip length) come in M3; until then
they are listed as "not applied" on every run.

## Setup

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Write a blank input workbook
wildflyer template my_season.xlsx

# Check a workbook and list problems by sheet / row / rule ID
wildflyer validate my_season.xlsx

# Generate a schedule (writes runs/<run name>.xlsx unless -o is given)
wildflyer solve my_season.xlsx
wildflyer solve my_season.xlsx -o schedule.xlsx --time-limit 60
```

The output workbook has three sheets:

- **Grid**: teams down the side, dates across the top. A home game shows the
  opponent in the home team's colour; an away game shows `@OPP`.
- **List**: one row per game (date, day, away, home).
- **Summary**: status, soft cost, each soft rule violation, and any rules
  not applied.

`examples/ausl_2027.xlsx` is the 2027 constraints document entered as rules
(regenerate with `python scripts/make_example_2027.py`).

## Input workbook

| Sheet | Contents |
|---|---|
| Settings | Season start/end, time limit, optional base run |
| Teams | Code, name, grid color |
| Rules | One rule per row: type, filters, parameters, Hard/Soft, Weight |
| Locks | Optional: games pinned to a date |
| Help | Syntax reference and the full rule catalog (generated) |

Rule types are defined in `src/wildflyer/catalog.py`, the single source of
truth for validation and the Help sheet.

## Tests

```bash
pytest
python scripts/bench_scale.py 30 150 120   # 30-team scale check
```
