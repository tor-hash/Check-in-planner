"""Countries BCT onboards employees in, and the language each one uses.

An employee's ``OnboardingProfile.country`` (snapshotted onto each
``OnboardingAssignment``) decides:

* which public holidays booking skips (``holidays_dk.holidays_for``),
* which language step titles/agendas are written in (``FlowStep.title_for``),
* which welcome-email templates are offered (``WelcomeEmailTemplate.language``).
"""
from __future__ import annotations

COUNTRY_DK = "DK"
COUNTRY_NO = "NO"
COUNTRY_CHOICES = (
    (COUNTRY_DK, "Danmark"),
    (COUNTRY_NO, "Norge"),
)
DEFAULT_COUNTRY = COUNTRY_DK

LANG_DA = "da"
LANG_NO = "no"
LANGUAGE_CHOICES = (
    (LANG_DA, "Dansk"),
    (LANG_NO, "Norsk"),
)

_LANGUAGE_FOR_COUNTRY = {COUNTRY_DK: LANG_DA, COUNTRY_NO: LANG_NO}

COUNTRY_CODES = tuple(c for c, _ in COUNTRY_CHOICES)
LANGUAGE_CODES = tuple(code for code, _ in LANGUAGE_CHOICES)


def normalize_country(value: str | None) -> str:
    """Upper-cased country code, or the default for anything unknown/blank."""
    code = (value or "").strip().upper()
    return code if code in COUNTRY_CODES else DEFAULT_COUNTRY


def language_for_country(country: str | None) -> str:
    return _LANGUAGE_FOR_COUNTRY[normalize_country(country)]
