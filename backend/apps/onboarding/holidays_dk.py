"""Danish and Norwegian public holidays and working-day helpers.

Used by onboarding calendar booking so a step never lands on a weekend or
a holiday: when the computed day isn't a working day, it rolls forward to
the next one. Computed locally (Easter-based) rather than via a third-party
package, so there's no extra dependency and no network lookup.

Besides the official helligdage this also treats Grundlovsdag (5 Jun),
juleaften (24 Dec) and nytårsaften (31 Dec) as days off, since most
Danish workplaces are closed then. Store bededag is not included — it was
abolished as a public holiday from 2024. Edit ``_FIXED_DAYS_OFF`` below if
the company's own days off differ.

Norway (``country="NO"``): the official helligdager plus 1. mai and
17. mai, and, like Denmark, julaften and nyttårsaften as days off.
Every helper takes an optional ``country`` ("DK" default, or "NO").
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# (month, day, name)
_FIXED_DAYS_OFF_NO = (
    (1, 1, "Nyttårsdag"),
    (5, 1, "Arbeidernes dag"),
    (5, 17, "Grunnlovsdag"),
    (12, 24, "Julaften"),
    (12, 25, "1. juledag"),
    (12, 26, "2. juledag"),
    (12, 31, "Nyttårsaften"),
)

_EASTER_RELATIVE_NO = (
    (-3, "Skjærtorsdag"),
    (-2, "Langfredag"),
    (0, "1. påskedag"),
    (1, "2. påskedag"),
    (39, "Kristi himmelfartsdag"),
    (49, "1. pinsedag"),
    (50, "2. pinsedag"),
)

_FIXED_DAYS_OFF = (
    (1, 1, "Nytårsdag"),
    (6, 5, "Grundlovsdag"),
    (12, 24, "Juleaften"),
    (12, 25, "Juledag"),
    (12, 26, "2. juledag"),
    (12, 31, "Nytårsaften"),
)

# Offsets in days from Easter Sunday.
_EASTER_RELATIVE = (
    (-3, "Skærtorsdag"),
    (-2, "Langfredag"),
    (0, "Påskedag"),
    (1, "2. påskedag"),
    (39, "Kristi himmelfartsdag"),
    (49, "Pinsedag"),
    (50, "2. pinsedag"),
)


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian / Meeus algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def holidays_for(year: int, country: str = "DK") -> dict[date, str]:
    """Return ``{date: name}`` for every day off in ``year`` in ``country``."""
    if (country or "").upper() == "NO":
        fixed, easter_relative = _FIXED_DAYS_OFF_NO, _EASTER_RELATIVE_NO
    else:
        fixed, easter_relative = _FIXED_DAYS_OFF, _EASTER_RELATIVE
    days = {date(year, m, d): name for m, d, name in fixed}
    easter = easter_sunday(year)
    for offset, name in easter_relative:
        days[easter + timedelta(days=offset)] = name
    return days


def danish_holidays(year: int) -> dict[date, str]:
    return holidays_for(year, "DK")


def is_holiday(d: date, country: str = "DK") -> bool:
    return d in holidays_for(d.year, (country or "DK").upper())


def is_working_day(d: date, country: str = "DK") -> bool:
    """Monday–Friday and not a public holiday in ``country``."""
    return d.weekday() < 5 and not is_holiday(d, country)


def next_working_day(d: date, country: str = "DK") -> date:
    """``d`` itself if it's a working day, otherwise the next one."""
    while not is_working_day(d, country):
        d += timedelta(days=1)
    return d
