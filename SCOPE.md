# Wildflyer — League Scheduler: MVP Scope

Status: draft for review · Last updated 2026-10-05

## 1. Purpose

A general-purpose sports league scheduler. The user defines a league, a season
window and a set of **rules** (hard or soft); the tool generates the best
schedule it can find, saves it, and lets the user change rules and re-run.

The tool has **no knowledge of any specific league**. Everything league-specific
(teams, dates, blackouts, rest requirements, series lengths) is input,
entered per run.

## 2. Core principles

1. **Game-based, not series-based.** The engine schedules individual games
   (home team, away team, date). "Series" are not a built-in concept;
   they emerge from rules such as *min/max consecutive games vs the same
   opponent*. This supports mixed series lengths and single-game leagues with
   no special logic.
2. **Fixed catalog of parameterized rule types.** Every rule a user writes is a
   row that uses one rule type from the catalog (§5). If a need can't be
   expressed, a new rule type is added to the catalog — the engine is never
   special-cased for a league.
3. **Hard vs soft, numerically weighted.** Any rule row can be *hard* (must
   hold; otherwise no schedule) or *soft* (each violation costs
   `weight × units`). The solver minimizes the total soft cost. No priority
   tiers.
4. **No distances, no venues.** Every game is played at the home team's
   location, so a location is named by the hosting team. Travel is expressed
   only through explicit transition rules ("require 2 days off when moving from
   a TEX home game to a CAR home game"). Neutral-site games are entered as
   locks (home team + away team on a date).
5. **Explainable.** Every rule is checked and reported on the output; when hard
   rules conflict, the tool names the conflicting rule rows.

## 3. Inputs (Excel template)

| Tab | Contents | Reused across runs? |
|---|---|---|
| **Teams** | Code, name, grid color | Yes (league profile) |
| **Settings** | Season start/end dates, solver time limit, base run for re-solving (optional) | Per run |
| **Rules** | One row per rule (see below) | Per run |
| **Locks** *(optional)* | Games pinned from a previous run | Per run |

### Rules tab columns

| Column | Meaning |
|---|---|
| ID | Unique row id, used in reports and conflict explanations |
| Enabled | Y/N, toggle a rule without deleting it |
| Rule type | One of the catalog types (§5) |
| Teams | Team(s) the rule applies to: `CHI`, `CHI,UTA`, `ALL`, `ALL except CHI` |
| Opponents | Optional opponent filter (same syntax) |
| Role | `home`, `away` or `any` |
| From / To | Transition rules only: hosting team codes, or `any` / `home` / `away` |
| Dates | Single dates, ranges, lists: `6/25-6/27, 7/1-7/3`; blank = whole season |
| Days of week | Optional filter: `Mon-Thu`, `Fri,Sat,Sun` |
| Min / Max / N | Numeric parameters, meaning depends on rule type |
| Hard/Soft | `Hard` or `Soft` |
| Weight | Soft only: cost per violation unit |
| Note | Free text |

The loader validates every row (unknown teams, bad dates, missing parameters)
and reports errors by row ID before solving.

## 4. Engine

- **Solver:** Google OR-Tools CP-SAT (Python).
- **Core decision:** for each ordered team pair *(home, away)* and each date,
  whether that game is played.
- **Built-in invariants** (not rules): a team plays at most one game per date;
  every game has a home and an away team.
- **Derived state** available to rules: whether a team plays on a date, its
  location (host team) on each game date, its opponent on each game date,
  home/away status.
- Each **hard** rule row compiles to constraints guarded by an on/off flag, so
  that when the model is infeasible the solver can report a minimal set of
  conflicting rule IDs.
- Each **soft** rule row compiles to violation counters; objective =
  Σ weight × violations (+ optional "minimize changes vs base run" term).
- Stops at the optimum or the time limit, returning the best schedule found and
  whether it's proven optimal.

## 5. Rule catalog

Each type supports the common filters (Teams, Opponents, Role, Dates, Days of
week) where meaningful, and can be hard or soft.

### Season & volume
| Type | Parameters | Example use |
|---|---|---|
| `LEAGUE_BLACKOUT` | Dates | No games during a national event |
| `SEASON_WINDOW` | First-game date range, last-game date | Opening day between 6/12 and 6/15; end by 8/15 |
| `MATCHUP_GAMES` | Teams, Opponents, Role, Min/Max | Each team hosts each opponent exactly 3 games |
| `TEAM_GAMES` | Teams, Role, Dates, Min/Max | 30 games per team; ≤ 15 home games |
| `GAMES_PER_DAY` | Dates, Days of week, Min/Max | ≤ 1 game on Wednesdays; ≤ 2 Mon-Thu |

### Availability
| Type | Parameters | Example use |
|---|---|---|
| `AVAILABILITY` | Teams, Role, Dates, Mode = `must` / `cannot` / `only` | Team must be home on given dates; cannot host in August; may host only within given windows |
| `FIXED_GAME` | Date, home, away | Pin a specific game |

### Sequence: opponents
| Type | Parameters | Example use |
|---|---|---|
| `OPPONENT_BLOCK` | Min/Max consecutive games vs same opponent, N = max off days allowed inside a block | Matchups come in blocks of 2–3 games, at most 1 off day inside |
| `REMATCH_GAP` | N = min days between blocks vs the same opponent | Don't play the same opponent again within 14 days |
| `OPPONENT_CHANGE_REST` | N = min off days when switching opponents | 1 day off between blocks |

### Sequence: locations & workload
| Type | Parameters | Example use |
|---|---|---|
| `TRAVEL_REST` | From location(s), To location(s) (host team codes or `any`, `home`, `away`), N = min off days | 2 days off when moving from TEX home to CAR home; 1 day off on any location change |
| `PREFERRED_TRANSITION` | From location(s), To location(s) | Visitors go PDX → UTA back-to-back (soft) |
| `HOME_AWAY_RUN` | Role, Max consecutive games or Max days | No road trip or homestand longer than 14 days |
| `MAX_CONSECUTIVE_GAME_DAYS` | Max | No more than 4 game days in a row |
| `GAMES_IN_WINDOW` | N-day rolling window or calendar week, Min/Max | ≤ 4 games in any 7 days |

### Preferences (typically soft)
| Type | Parameters | Example use |
|---|---|---|
| `DATE_PREFERENCE` | Dates, Days of week, Weight (+ reward / − penalty per game) | Favor weekend games; fewer games 7/18-7/31 |
| `BALANCE` | Metric (games matching Role/Dates/Days filter), Max spread across teams | Home weekend dates within 1 of each other across teams |

## 6. Outputs (one Excel workbook per run)

1. **Grid** — teams in rows, every season date as a column (month bands,
   weekday labels, weekends shaded, league blackouts marked). Cell = opponent:
   home games `UTA` filled with the home team's color; away games `@UTA` on
   white; off days blank. Game counts per team.
2. **List** — Date, Day, Away, Home (sorted by date).
3. **Checks** — matchup matrix (home/away games per pair), home/away totals per
   team, games per day by weekday, transitions per team with off days between.
4. **Rules report** — every rule row: met / violated, where (dates, teams),
   and soft cost. Total score.
5. **Infeasible run** — instead of 1–4, a report listing the conflicting hard
   rule IDs.

## 7. Runs & iteration

- Each run is saved to `runs/<timestamp>_<name>/` containing the input
  workbook as used, the output workbook, a solve log and the score.
- **Locks:** pin games (or all games before a date) from a previous run.
- **Minimize changes:** optional soft term penalizing each game that differs
  from a base run.
- **Compare:** score side by side and the list of games added / removed /
  moved between two runs.
- Interface: command line, e.g. `wildflyer solve inputs.xlsx --name v3`.

## 8. Out of scope (MVP)

Web UI (phase 2), natural-language rule entry (phase 2), venues / neutral
sites (use locks), game times,
doubleheaders, TV windows, postseason, divisions, officials, calendar exports,
multi-user access.

## 9. Acceptance criteria

1. **Expressiveness:** the 2027 constraints document can be entered entirely
   with catalog rule types — no league-specific code.
2. **Solves the real case:** with those rules (6 teams, 90 games), produces a
   valid schedule, with checks at least as clean as the existing hand-built v2.
3. **Scale:** a synthetic 30-team league solves to a feasible schedule within a
   configurable time limit.
4. **Iteration:** changing/toggling a rule and re-running with a base run
   shows exactly what moved.
5. **Infeasibility:** contradictory hard rules produce a report naming them.

## 10. Milestones

1. **M1 — Inputs:** template, loader, validation with row-level errors.
2. **M2 — Core engine:** game variables, invariants, season/volume and
   availability rules, locks; grid + list output.
3. **M3 — Sequence rules:** opponent blocks, rematch gap, transitions,
   home/away runs, workload windows.
4. **M4 — Soft rules & reporting:** weighted objective, preferences, balance,
   checks and rules report, infeasibility explanation.
5. **M5 — Runs:** saved runs, locks, minimize-changes, compare. 30-team
   scale test.

## 11. Risks

- **Block rules across off days** (`OPPONENT_BLOCK` with gaps allowed) are the
  most complex constraints to model; they get dedicated tests.
- **Performance at 30 teams** with many sequence rules: mitigated by time
  limits, returning best-found schedules, and solver tuning.
- **Rule ambiguity:** every rule type gets a precise written definition
  (e.g. what counts as "consecutive" when off days intervene) in the template's
  help tab.
