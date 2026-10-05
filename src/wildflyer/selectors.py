"""Parsers for the selector syntaxes used in rule rows.

Each parser raises `SelectorError` with a user-facing message on bad input.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .model import Location


class SelectorError(ValueError):
    pass


def _tokens(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,;\n]", text) if t.strip()]


# --- Team codes ---------------------------------------------------


def parse_codes(value: object, known: set[str], what: str) -> frozenset[str]:
    """Parse `A,B`, `ALL` or `ALL except A,B` into a set of known codes.

    Blank input returns an empty set; callers decide what blank means.
    """
    text = _cell_text(value)
    if not text:
        return frozenset()
    m = re.fullmatch(r"all(?:\s+except\s+(.*))?", text, flags=re.I | re.S)
    if m:
        excluded = _known_codes(m.group(1) or "", known, what)
        if m.group(1) is not None and not excluded:
            raise SelectorError(f"'ALL except' needs at least one {what} code")
        return frozenset(known - excluded)
    return _known_codes(text, known, what)


def _known_codes(text: str, known: set[str], what: str) -> frozenset[str]:
    codes = {t.upper() for t in _tokens(text)}
    unknown = sorted(codes - known)
    if unknown:
        raise SelectorError(f"unknown {what} code(s): {', '.join(unknown)}")
    return frozenset(codes)


# --- Locations (From / To on transition rules) --------------------------------

LOCATION_KEYWORDS = {"any", "home", "away"}


def parse_location(value: object, teams: set[str]) -> Location:
    """Parse a From/To cell: hosting team codes and/or any / home / away."""
    text = _cell_text(value)
    if not text:
        raise SelectorError("location is required (hosting team code, or any / home / away)")
    hosts, keywords = set(), set()
    for tok in _tokens(text):
        if tok.lower() in LOCATION_KEYWORDS:
            keywords.add(tok.lower())
        elif tok.upper() in teams:
            hosts.add(tok.upper())
        else:
            raise SelectorError(f"unknown team code '{tok}' (or use any / home / away)")
    return Location(frozenset(hosts), frozenset(keywords))


# --- Days of week -------------------------------------------------------------

_DAY_NAMES = {
    "mon": 0, "monday": 0, "m": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "tu": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "w": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "th": 3,
    "fri": 4, "friday": 4, "f": 4,
    "sat": 5, "saturday": 5, "sa": 5,
    "sun": 6, "sunday": 6, "su": 6,
}


def parse_days(value: object) -> frozenset[int]:
    """Parse `Mon-Thu`, `Fri,Sat,Sun`, `Wed` into weekday numbers (Mon=0)."""
    text = _cell_text(value)
    if not text:
        return frozenset()
    days: set[int] = set()
    for tok in _tokens(text):
        parts = [p.strip().lower() for p in tok.split("-")]
        if len(parts) > 2 or any(p not in _DAY_NAMES for p in parts):
            raise SelectorError(f"can't read day(s) of week '{tok}' (use e.g. Mon-Thu or Fri,Sat)")
        start = _DAY_NAMES[parts[0]]
        end = _DAY_NAMES[parts[-1]]
        i = start
        days.add(i)
        while i != end:  # ranges may wrap, e.g. Fri-Sun or Sat-Mon
            i = (i + 1) % 7
            days.add(i)
    return frozenset(days)


# --- Dates --------------------------------------------------------------------

_ISO = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")


def parse_dates(value: object, season_start: date, season_end: date) -> frozenset[date]:
    """Parse a date spec into a set of dates.

    Accepts Excel dates, and text made of comma/semicolon separated items:
      - single dates: `6/25`, `6/25/2027`, `2027-06-25`
      - ranges: `6/25-6/27`, `6/25-27` (same month), `6/25 to 2027-06-27`
      - `start` / `end` for the season bounds: `8/2-end`
    Dates without a year take the year that places them inside (or nearest to)
    the season.
    """
    if value is None or value == "":
        return frozenset()
    if isinstance(value, (datetime, date)):
        return frozenset({_as_date(value)})
    text = str(value).strip()
    out: set[date] = set()
    for item in _tokens(text):
        lo_text, hi_text = _split_range(item)
        lo = _parse_one(lo_text, season_start, season_end)
        if hi_text is None:
            out.add(lo)
            continue
        if re.fullmatch(r"\d{1,2}", hi_text):  # `6/25-27`: same month as start
            try:
                hi = lo.replace(day=int(hi_text))
            except ValueError as e:
                raise SelectorError(f"bad date range '{item}': {e}") from None
        else:
            hi = _parse_one(hi_text, season_start, season_end)
        if hi < lo:
            raise SelectorError(f"date range '{item}' ends before it starts")
        out.update(lo + timedelta(i) for i in range((hi - lo).days + 1))
    return frozenset(out)


def _split_range(item: str) -> tuple[str, str | None]:
    m = re.fullmatch(r"(.+?)\s+to\s+(.+)", item, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Hide ISO dates' hyphens before splitting on '-'.
    isos = _ISO.findall(item)
    masked = _ISO.sub("\0", item)
    parts = [p.strip() for p in masked.split("-")]
    if len(parts) > 2:
        raise SelectorError(f"can't read date range '{item}'")
    restored = []
    for p in parts:
        while "\0" in p:
            p = p.replace("\0", isos.pop(0), 1)
        restored.append(p)
    return restored[0], (restored[1] if len(restored) == 2 else None)


def _parse_one(text: str, season_start: date, season_end: date) -> date:
    t = text.strip().lower()
    if t == "start":
        return season_start
    if t == "end":
        return season_end
    try:
        if _ISO.fullmatch(t):
            return date.fromisoformat("-".join(f"{int(p):02d}" for p in t.split("-")))
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", t)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            if m.group(3):
                year = int(m.group(3))
                return date(year + 2000 if year < 100 else year, month, day)
            return _infer_year(month, day, season_start, season_end)
    except ValueError as e:
        raise SelectorError(f"bad date '{text}': {e}") from None
    raise SelectorError(f"can't read date '{text}' (use e.g. 6/25, 2027-06-25, or start/end)")


def _infer_year(month: int, day: int, season_start: date, season_end: date) -> date:
    candidates = []
    for year in {season_start.year - 1, season_start.year, season_end.year, season_end.year + 1}:
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            pass
    if not candidates:
        raise ValueError(f"{month}/{day} is not a valid date")

    def distance(d: date) -> int:
        if season_start <= d <= season_end:
            return 0
        return min(abs((d - season_start).days), abs((d - season_end).days))

    return min(candidates, key=distance)


# --- Cell helpers ---------------------------------------------------------------


def _as_date(v: datetime | date) -> date:
    return v.date() if isinstance(v, datetime) else v


def _cell_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SelectorError(f"expected a whole number, got '{value}'")
    if isinstance(value, (int, float)):
        if float(value) != int(value):
            raise SelectorError(f"expected a whole number, got '{value}'")
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    raise SelectorError(f"expected a whole number, got '{value}'")


def parse_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SelectorError(f"expected a number, got '{value}'")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        raise SelectorError(f"expected a number, got '{value}'") from None


def parse_date_cell(value: object) -> date:
    if isinstance(value, (datetime, date)):
        return _as_date(value)
    text = _cell_text(value)
    if _ISO.fullmatch(text):
        return date.fromisoformat("-".join(f"{int(p):02d}" for p in text.split("-")))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", text)
    if m:
        year = int(m.group(3))
        return date(year + 2000 if year < 100 else year, int(m.group(1)), int(m.group(2)))
    raise SelectorError(f"expected a full date (e.g. 2027-06-12), got '{text}'")
