from datetime import date
from pathlib import Path

import pytest

from wildflyer.catalog import CATALOG
from wildflyer.loader import load
from wildflyer.model import Level
from wildflyer.template import build_workbook

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ausl_2027.xlsx"

SETTINGS = {"Season start": date(2027, 6, 12), "Season end": date(2027, 8, 15)}
TEAMS = [("AAA", "Team A", "FF0000"), ("BBB", "Team B", "00FF00"), ("CCC", "Team C", "")]


def write(tmp_path, rules=(), settings=SETTINGS, teams=TEAMS, locks=()):
    path = tmp_path / "in.xlsx"
    build_workbook(settings=settings, teams=teams, rules=rules, locks=locks).save(path)
    return load(path)


def rule(**kw):
    return {"ID": "R1", **kw}


def messages(result, level=Level.ERROR):
    return [str(i) for i in result.issues if i.level is level]


def assert_error(result, text, field=None):
    errs = [i for i in result.errors if text in i.message and (field is None or i.field == field)]
    assert errs, f"expected error containing {text!r}; got {messages(result)}"
    return errs[0]


def test_example_workbook_is_valid():
    result = load(EXAMPLE)
    assert result.ok, messages(result)
    assert len(result.run.teams) == 6
    assert len(result.run.rules) == 29  # R90 is disabled


def test_minimal_valid(tmp_path):
    result = write(tmp_path, [rule(Type="TEAM_GAMES", Min=4, Max=4)])
    assert result.ok, messages(result)
    r = result.run.rules[0]
    assert r.teams == {"AAA", "BBB", "CCC"}  # blank Teams = ALL
    assert r.hard and r.min == 4 and r.max == 4
    assert result.run.teams["CCC"].color == "D9D9D9"  # default color
    assert len(result.run.season_dates) == 65


class TestSettings:
    def test_missing_dates(self, tmp_path):
        result = write(tmp_path, settings={})
        assert_error(result, "'Season start' is required")
        assert result.run is None

    def test_end_before_start(self, tmp_path):
        result = write(tmp_path, settings={"Season start": date(2027, 8, 1), "Season end": date(2027, 6, 1)})
        assert_error(result, "Season end is before")

    def test_text_dates_and_options(self, tmp_path):
        result = write(tmp_path, settings={"Season start": "2027-06-12", "Season end": "8/15/2027",
                                           "Time limit (seconds)": 60, "Run name": "v1"})
        assert result.ok, messages(result)
        assert result.run.settings.time_limit_seconds == 60 and result.run.settings.run_name == "v1"


class TestTeams:
    def test_duplicate_team(self, tmp_path):
        e = assert_error(write(tmp_path, teams=TEAMS + [("AAA", "dup", "")]), "duplicate team code")
        assert e.row == 5 and e.field == "Code"

    def test_bad_color(self, tmp_path):
        assert_error(write(tmp_path, teams=[("AAA", "A", "red")] + TEAMS[1:]), "hex code")

    def test_reserved_code(self, tmp_path):
        assert_error(write(tmp_path, teams=TEAMS + [("ALL", "x", "")]), "can't be ALL")

    def test_too_few_teams(self, tmp_path):
        assert_error(write(tmp_path, teams=TEAMS[:1]), "at least two teams")


class TestRules:
    def test_unknown_type(self, tmp_path):
        e = assert_error(write(tmp_path, [rule(Type="MAGIC")]), "unknown rule type")
        assert e.rule_id == "R1" and e.row == 2

    def test_missing_required_field(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="REMATCH_GAP")]), "N is required", field="N")

    def test_unknown_team(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="TEAM_GAMES", Teams="AAA, ZZZ", Max=3)]), "ZZZ", field="Teams")

    def test_bad_dates(self, tmp_path):
        result = write(tmp_path, [rule(Type="LEAGUE_BLACKOUT", Dates="sometime")])
        assert_error(result, "can't read date", field="Dates")

    def test_min_greater_than_max(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="TEAM_GAMES", Min=5, Max=3)]), "greater than Max")

    def test_needs_min_or_max(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="GAMES_PER_DAY", Days="Wed")]), "needs Min and/or Max")

    def test_option_required(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="AVAILABILITY", Teams="AAA", Dates="7/1")]), "Option is required")

    def test_option_default(self, tmp_path):
        result = write(tmp_path, [rule(Type="HOME_AWAY_RUN", Role="away", Max=5)])
        assert result.ok, messages(result)
        assert result.run.rules[0].option == "games"

    def test_bad_option(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="SEASON_WINDOW", Dates="6/12-15", Option="middle")]),
                     "Option must be one of")

    def test_role_restricted(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="HOME_AWAY_RUN", Role="any", Max=5)]), "Role must be one of")

    def test_soft_needs_weight(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="TEAM_GAMES", Max=3, **{"Hard/Soft": "Soft"})]), "need a Weight")

    def test_soft_weight_parsed(self, tmp_path):
        result = write(tmp_path, [rule(Type="TEAM_GAMES", Max=3, Weight=7.5, **{"Hard/Soft": "Soft"})])
        assert result.ok and not result.run.rules[0].hard and result.run.rules[0].weight == 7.5

    def test_soft_only_type(self, tmp_path):
        result = write(tmp_path, [rule(Type="DATE_PREFERENCE", Option="prefer", Days="Sat", **{"Hard/Soft": "Hard"})])
        assert_error(result, "can only be Soft")

    def test_soft_only_defaults_to_soft(self, tmp_path):
        result = write(tmp_path, [rule(Type="DATE_PREFERENCE", Option="prefer", Days="Sat", Weight=2)])
        assert result.ok, messages(result)
        assert not result.run.rules[0].hard

    def test_duplicate_ids(self, tmp_path):
        rows = [rule(Type="TEAM_GAMES", Max=3), rule(Type="TEAM_GAMES", Min=1)]
        assert_error(write(tmp_path, rows), "duplicate ID")

    def test_unused_field_is_warning(self, tmp_path):
        result = write(tmp_path, [rule(Type="MAX_CONSECUTIVE_GAME_DAYS", Max=4, Dates="7/1")])
        assert result.ok
        assert any("not used by" in m for m in messages(result, Level.WARNING))

    def test_disabled_rule_errors_are_warnings(self, tmp_path):
        result = write(tmp_path, [rule(Type="REMATCH_GAP", Enabled="N")])
        assert result.ok
        assert any("(disabled rule)" in m for m in messages(result, Level.WARNING))
        assert result.run.rules == []

    def test_disabled_rule_excluded(self, tmp_path):
        rows = [rule(Type="TEAM_GAMES", Max=3), {"ID": "R2", "Type": "TEAM_GAMES", "Max": 2, "Enabled": "N"}]
        result = write(tmp_path, rows)
        assert [r.id for r in result.run.rules] == ["R1"]

    def test_fixed_game(self, tmp_path):
        result = write(tmp_path, [rule(Type="FIXED_GAME", Teams="AAA", Opponents="BBB", Dates="7/4")])
        assert result.ok, messages(result)
        r = result.run.rules[0]
        assert r.teams == {"AAA"} and r.opponents == {"BBB"} and r.dates == {date(2027, 7, 4)}

    def test_fixed_game_single_team(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="FIXED_GAME", Teams="AAA,BBB", Opponents="CCC", Dates="7/4")]),
                     "exactly one team")

    def test_fixed_game_self(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="FIXED_GAME", Teams="AAA", Opponents="AAA", Dates="7/4")]),
                     "can't play itself")

    def test_travel_rest_locations(self, tmp_path):
        result = write(tmp_path, [rule(Type="TRAVEL_REST", From="AAA", To="away", N=2)])
        assert result.ok, messages(result)
        r = result.run.rules[0]
        assert r.from_loc.hosts == {"AAA"} and r.to_loc.keywords == {"away"}

    def test_rolling_window_needs_n(self, tmp_path):
        assert_error(write(tmp_path, [rule(Type="GAMES_IN_WINDOW", Max=4)]), "rolling windows need N")

    def test_dates_outside_season_warn(self, tmp_path):
        result = write(tmp_path, [rule(Type="LEAGUE_BLACKOUT", Dates="6/1-6/13")])
        assert result.ok
        assert any("outside the season" in m for m in messages(result, Level.WARNING))

    def test_blank_rows_skipped(self, tmp_path):
        result = write(tmp_path, [rule(Type="TEAM_GAMES", Max=3), {}, {"ID": "R2", "Type": "TEAM_GAMES", "Min": 1}])
        assert result.ok and len(result.run.rules) == 2


class TestLocks:
    def test_valid_lock(self, tmp_path):
        result = write(tmp_path, locks=[(date(2027, 7, 1), "AAA", "BBB")])
        assert result.ok and result.run.locks[0].home == "AAA"

    def test_bad_lock(self, tmp_path):
        result = write(tmp_path, locks=[(date(2027, 1, 1), "AAA", "AAA"), (date(2027, 7, 1), "AAA", "ZZZ")])
        for text in ("outside the season", "can't play itself", "unknown team 'ZZZ'"):
            assert_error(result, text)


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_catalog_spec_complete(name):
    spec = CATALOG[name]
    assert spec.summary and spec.example
    if spec.option_default is not None:
        assert spec.option_default in spec.options


def test_help_sheet_lists_every_rule_type():
    help_types = {row[0] for row in build_workbook()["Help"].iter_rows(values_only=True)}
    assert set(CATALOG) <= help_types


def test_missing_sheet(tmp_path):
    wb = build_workbook(settings=SETTINGS, teams=TEAMS)
    del wb["Rules"]
    path = tmp_path / "x.xlsx"
    wb.save(path)
    assert_error(load(path), "sheet is missing")


def test_unreadable_file(tmp_path):
    path = tmp_path / "x.xlsx"
    path.write_text("not a workbook")
    assert_error(load(path), "can't open workbook")


def test_dates_column_is_text_formatted():
    ws = build_workbook()["Rules"]
    col = [c.value for c in ws[1]].index("Dates") + 1
    assert ws.cell(2, col).number_format == "@"


def test_old_venue_columns_are_reported(tmp_path):
    wb = build_workbook(settings=SETTINGS, teams=TEAMS, rules=[rule(Type="TEAM_GAMES", Max=3)])
    wb["Rules"].cell(1, 30, "Venues")
    path = tmp_path / "x.xlsx"
    wb.save(path)
    result = load(path)
    assert result.ok
    assert any("unknown column" in m and "Venues" in m for m in messages(result, Level.WARNING))


def test_template_has_no_formulas(tmp_path):
    import zipfile

    path = tmp_path / "t.xlsx"
    build_workbook(rules=[{"ID": "R1", "Type": "TEAM_GAMES", "Note": "=not a formula"}]).save(path)
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("xl/worksheets/"):
                assert "<f>" not in z.read(name).decode(), name
