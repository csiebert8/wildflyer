# Wildflyer

A constraint-based sports league scheduler. You describe a league and a set of
hard and soft rules in an Excel workbook, and Wildflyer finds the best schedule
it can. See [SCOPE.md](SCOPE.md) for the full MVP scope.

**Status:** M1 (input template, loader, validation). Solving comes in M2.

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
```

`examples/ausl_2027.xlsx` is the 2027 constraints document entered as rules
(regenerate with `python scripts/make_example_2027.py`).

## Input workbook

| Sheet | Contents |
|---|---|
| Settings | Season start/end, time limit, optional base run |
| Teams | Code, name, home venue, grid color |
| Venues | Code, name, owning team (blank = neutral site) |
| Rules | One rule per row: type, filters, parameters, Hard/Soft, Weight |
| Locks | Optional: games pinned to a date |
| Help | Syntax reference and the full rule catalog (generated) |

Rule types are defined in `src/wildflyer/catalog.py`, the single source of
truth for validation and the Help sheet.

## Tests

```bash
pytest
```
