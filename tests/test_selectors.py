from datetime import date, datetime

import pytest

from wildflyer.selectors import (SelectorError, parse_codes, parse_date_cell, parse_dates, parse_days,
                                 parse_int, parse_location)

START, END = date(2027, 6, 12), date(2027, 8, 15)
TEAMS = {"CHI", "CAR", "UTA", "PDX"}


def d(m, day, y=2027):
    return date(y, m, day)


class TestCodes:
    def test_list_and_case(self):
        assert parse_codes("chi, UTA", TEAMS, "team") == {"CHI", "UTA"}

    def test_all(self):
        assert parse_codes("ALL", TEAMS, "team") == TEAMS

    def test_all_except(self):
        assert parse_codes("All except CHI, UTA", TEAMS, "team") == {"CAR", "PDX"}

    def test_blank(self):
        assert parse_codes(None, TEAMS, "team") == frozenset()

    def test_unknown(self):
        with pytest.raises(SelectorError, match="unknown team code.*XYZ"):
            parse_codes("CHI, XYZ", TEAMS, "team")


class TestLocation:
    def test_keywords_and_venues(self):
        loc = parse_location("home, PDX", {"PDX", "CHI"})
        assert loc.keywords == {"home"} and loc.venues == {"PDX"}

    def test_unknown(self):
        with pytest.raises(SelectorError, match="unknown venue"):
            parse_location("nowhere", {"PDX"})

    def test_required(self):
        with pytest.raises(SelectorError):
            parse_location("", {"PDX"})


class TestDays:
    def test_range(self):
        assert parse_days("Mon-Thu") == {0, 1, 2, 3}

    def test_list(self):
        assert parse_days("Fri, Sat,Sun") == {4, 5, 6}

    def test_wrapping_range(self):
        assert parse_days("Sat-Mon") == {5, 6, 0}

    def test_bad(self):
        with pytest.raises(SelectorError):
            parse_days("Funday")


class TestDates:
    def p(self, v):
        return parse_dates(v, START, END)

    def test_single(self):
        assert self.p("6/25") == {d(6, 25)}

    def test_range(self):
        assert self.p("6/25-6/27") == {d(6, 25), d(6, 26), d(6, 27)}

    def test_short_range(self):
        assert self.p("6/25-27") == {d(6, 25), d(6, 26), d(6, 27)}

    def test_list_of_ranges(self):
        assert self.p("6/25-26, 7/1") == {d(6, 25), d(6, 26), d(7, 1)}

    def test_cross_month(self):
        assert len(self.p("6/28-7/2")) == 5

    def test_iso_and_range(self):
        assert self.p("2027-06-25 - 2027-06-26") == {d(6, 25), d(6, 26)}
        assert self.p("2027-06-25") == {d(6, 25)}

    def test_to_keyword(self):
        assert self.p("6/25 to 6/26") == {d(6, 25), d(6, 26)}

    def test_start_end(self):
        assert min(self.p("8/2-end")) == d(8, 2) and max(self.p("8/2-end")) == END
        assert min(self.p("start-6/13")) == START

    def test_explicit_year(self):
        assert self.p("6/25/28") == {d(6, 25, 2028)}

    def test_excel_date(self):
        assert self.p(datetime(2027, 7, 4)) == {d(7, 4)}

    def test_year_inference_across_new_year(self):
        assert parse_dates("1/5", date(2026, 11, 1), date(2027, 3, 1)) == {d(1, 5)}
        assert parse_dates("12/5", date(2026, 11, 1), date(2027, 3, 1)) == {d(12, 5, 2026)}

    def test_backwards_range(self):
        with pytest.raises(SelectorError, match="ends before"):
            self.p("6/27-6/25")

    def test_garbage(self):
        with pytest.raises(SelectorError):
            self.p("next tuesday")

    def test_invalid_day(self):
        with pytest.raises(SelectorError):
            self.p("6/31")


def test_parse_int():
    assert parse_int(3) == 3 and parse_int(3.0) == 3 and parse_int("4") == 4 and parse_int(None) is None
    with pytest.raises(SelectorError):
        parse_int(2.5)
    with pytest.raises(SelectorError):
        parse_int("three")


def test_parse_date_cell():
    assert parse_date_cell(datetime(2027, 6, 12)) == d(6, 12)
    assert parse_date_cell("2027-06-12") == d(6, 12)
    assert parse_date_cell("6/12/2027") == d(6, 12)
    with pytest.raises(SelectorError):
        parse_date_cell("6/12")
