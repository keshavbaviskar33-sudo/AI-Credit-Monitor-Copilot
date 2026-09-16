"""Period construction and parsing (§7, §8).

Two distinct jobs live here:

1. **From XBRL facts** (`period_from_xbrl_fact`) -- the primary path for SEC
   filers (D-005). This is exact: `start`/`end` are ISO dates SEC already
   parsed, so there is no ambiguity to resolve.
2. **From table-header text** (`parse_period_label`) -- for the no-XBRL
   upload path (FR-04). This is a best-effort regex reader for the phrasing
   filings actually use ("Year Ended December 31, 2025" vs. "December 31,
   2025"), kept deliberately small: full table-column-to-period alignment for
   uploaded PDFs is a documented Phase 5 limitation, not solved here, because
   XBRL already solves the primary case this product monitors (D-005/D-014).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from credit_risk_copilot.financials.models import Period, PeriodType

_MONTHS = {
    name.lower(): i
    for i, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}

#: "December 31, 2025" / "Dec. 31, 2025" -- a bare date, as an instant column
#: header or a balance-sheet "As of" line.
_DATE_RE = re.compile(r"(?P<month>[A-Za-z]+)\.?\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})")

#: "Year Ended December 31, 2025" / "Years Ended December 31, 2025, 2024 and 2023"
#: -- only the first date is parsed; comparative columns repeat the phrase or
#: are read from their own header cell, matching how filings lay out tables.
_DURATION_RE = re.compile(r"years?\s+ended", re.IGNORECASE)


def period_from_xbrl_fact(entry: dict[str, Any], *, period_type: PeriodType) -> Period | None:
    """Build a `Period` from one raw `companyfacts` entry.

    `period_type` is the canonical concept's *expected* nature (§8): a fact
    reported as a duration where an instant concept was expected (or the
    reverse) is a real data-quality signal, not something to paper over, so
    the caller passes what it expects and this returns `None` on mismatch
    rather than guessing.
    """
    end_raw = entry.get("end")
    if not end_raw:
        return None
    end = date.fromisoformat(end_raw)
    start_raw = entry.get("start")

    if period_type is PeriodType.INSTANT:
        if start_raw:
            return None  # this is actually a duration fact
        return Period(period_type=PeriodType.INSTANT, end=end)

    if not start_raw:
        return None  # this is actually an instant fact
    start = date.fromisoformat(start_raw)
    return Period(period_type=PeriodType.DURATION, start=start, end=end)


#: How far a fact's `end` may sit from the filing's declared fiscal year end
#: and still count as "that fiscal year end" rather than a different period
#: entirely. Wide enough to absorb a 52/53-week fiscal calendar's few days of
#: drift year to year; nowhere near wide enough to admit a quarter-end.
_FISCAL_YEAR_END_TOLERANCE_DAYS = 10

#: A duration must span roughly a year to be an *annual* period (D-007).
_ANNUAL_SPAN_DAYS = (350, 380)


def _day_distance(candidate: date, fiscal_month: int, fiscal_day: int) -> int:
    """Days between `candidate` and the nearest calendar occurrence of
    `fiscal_month`/`fiscal_day`, checked across the surrounding years so a
    December/January-boundary fiscal year end doesn't look far from itself."""
    best = 366
    for year in (candidate.year - 1, candidate.year, candidate.year + 1):
        try:
            anchor = date(year, fiscal_month, fiscal_day)
        except ValueError:
            anchor = date(year, fiscal_month, 28)  # Feb 29 anchor, non-leap year
        best = min(best, abs((candidate - anchor).days))
    return best


def is_annual_period(period: Period, fiscal_month: int, fiscal_day: int) -> bool:
    """Whether `period` is plausibly *this filing's* annual period, not one
    of the quarterly sub-periods a "selected quarterly financial data" note
    tags under the very same XBRL concept and accession.

    Real filings do this: iHeartMedia's 2016 10-K reports `Revenues` for each
    of 2015 Q1-Q4 *and* full-year 2015 under one tag, one accession -- keying
    a period only by `end.year` (as an earlier version of this module did)
    silently folds a quarter's revenue into the same bucket as the annual
    figure. Two checks rule that out: the end date must fall near the
    filing's own declared fiscal year end (rejects Q1-Q3, whose end dates
    land on unrelated months), and a duration must span close to a full year
    (rejects Q4, whose end date is the fiscal year end itself but whose
    start is only three months earlier).
    """
    if _day_distance(period.end, fiscal_month, fiscal_day) > _FISCAL_YEAR_END_TOLERANCE_DAYS:
        return False
    if period.period_type is PeriodType.DURATION:
        assert period.start is not None  # guaranteed by the Period model itself
        span_days = (period.end - period.start).days
        low, high = _ANNUAL_SPAN_DAYS
        if not (low <= span_days <= high):
            return False
    return True


def parse_period_label(text: str) -> tuple[PeriodType, date] | None:
    """Read a table header or units-declaration-adjacent line into a period.

    Returns `(period_type, end_date)` -- a duration period's `start` is not
    recoverable from the label alone (a fiscal year's start depends on the
    company's fiscal year end, which this text does not state), so callers
    needing a full `Period` must supply `start` themselves (e.g. by assuming
    a standard 12-month annual period, per D-007's annual-only scope).
    """
    match = _DATE_RE.search(text)
    if not match:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    end = date(int(match.group("year")), month, int(match.group("day")))

    if _DURATION_RE.search(text):
        return (PeriodType.DURATION, end)
    # A bare date, or one marked "as of", is a balance-sheet-style instant.
    return (PeriodType.INSTANT, end)
