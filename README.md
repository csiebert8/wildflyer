# Wildflyer

A constraint-based sports league scheduler. You describe a league and a set of
hard and soft rules in an Excel workbook, and Wildflyer finds the best schedule
it can. See [SCOPE.md](SCOPE.md) for the full MVP scope.

**Status:** MVP complete (M1-M5) plus a local web app. Sized for leagues of about 6 teams, 60 days
and 30 games per team.

## Using the app (recommended)

**Mac:** double-click **`Wildflyer.command`** in the `wildflyer` folder. The
first time, it sets everything up (a few minutes). Your browser then opens the
app at `http://localhost:8501`. Keep the Terminal window that opens; close it
to quit the app. If macOS says it can't open the file, right-click it and
choose **Open** once.

**Or from Terminal:**

```bash
source .venv/bin/activate
wildflyer app
```

The app only runs on this computer. Its workflow:

1. **Rules file:** choose an Excel rules workbook from the `wildflyer` folder,
   upload one, or download a blank template.
2. **Check:** the file is checked automatically. Errors stop you, with
   sheet/row/column; warnings don't. After editing in Excel, save and click
   **Re-check file**.
3. **Solve:** set the time limit and click **Solve**. You'll see time left,
   the best cost so far, and a **Stop and keep the best so far** button.
4. **Result:** status, soft cost, a colored schedule preview, soft rule
   violations, rule statuses, team checks, and **Download schedule**.
5. **Past runs:** every run is saved in `runs/`; download its schedule or the
   rules used, preview it, or compare two runs.

## Setup (for the command line)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Command line usage

```bash
# Write a blank input workbook
wildflyer template my_season.xlsx

# Check a workbook and list problems by sheet / row / rule ID
wildflyer validate my_season.xlsx

# Generate a schedule into a new folder runs/<date-time>_<run name>/
# (schedule.xlsx plus a copy of the rules used)
wildflyer solve my_season.xlsx

# ...or to a file of your choice, with a shorter search
wildflyer solve my_season.xlsx -o schedule.xlsx --time-limit 60

# List the games that differ between two schedules
wildflyer compare schedule_v1.xlsx schedule_v2.xlsx
```

The output workbook has these sheets:

- **Grid**: teams down the side, dates across the top. A home game shows the
  opponent in the home team's colour; an away game shows `@OPP`.
- **List**: one row per game (date, day, away, home).
- **Rules**: every rule and whether the schedule met it.
- **Checks**: facts computed from the games: per-team totals, the matchup
  grid, games by weekday, and every move between locations with its off days.
- **Changes**: only with a base run: games added or removed compared to it.
- **Summary**: status, soft cost, each soft rule violation. If no schedule
  is possible, it lists the hard rules that conflict.

### Building on a previous schedule

On the Settings sheet, set **Base run** to an earlier schedule workbook, then:

- **Lock base before** (a date): everything before it stays exactly as in
  the base run, which is useful for re-planning mid-season.
- **Change weight** (a number): each base-run game that moves costs this much,
  so the solver changes as little as it can.

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
```
