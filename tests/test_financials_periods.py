"""Tests for period construction and parsing (§7, §8)."""

from __future__ import annotations

from datetime import date

import pytest

from credit_risk_copilot.financials.models import Period, PeriodType
from credit_risk_copilot.financials.periods import (
    is_annual_period,
    parse_period_label,
    period_from_xbrl_fact,
)


class TestPeriodModel:
    def test_instant_period_rejects_a_start_date(self) -> None:
        """§8: an instant is a single moment -- giving it a start is a
        contradiction, not a detail to ignore."""
        with pytest.raises(ValueError, match="instant period has no start"):
            Period(period_type=PeriodType.INSTANT, start=date(2024, 1, 1), end=date(2025, 1, 1))

    def test_duration_period_requires_a_start_date(self) -> None:
        with pytest.raises(ValueError, match="duration period needs a start"):
            Period(period_type=PeriodType.DURATION, end=date(2025, 12, 31))

    def test_fiscal_year_and_label_come_from_the_end_date(self) -> None:
        period = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))

        assert period.fiscal_year == 2025
        assert period.label == "FY2025"


class TestPeriodFromXbrlFact:
    def test_instant_fact_has_no_start(self) -> None:
        period = period_from_xbrl_fact({"end": "2025-12-31"}, period_type=PeriodType.INSTANT)

        assert period is not None
        assert period.period_type is PeriodType.INSTANT
        assert period.end == date(2025, 12, 31)

    def test_duration_fact_needs_both_dates(self) -> None:
        period = period_from_xbrl_fact(
            {"start": "2025-01-01", "end": "2025-12-31"}, period_type=PeriodType.DURATION
        )

        assert period is not None
        assert period.start == date(2025, 1, 1)
        assert period.end == date(2025, 12, 31)

    def test_a_duration_fact_is_rejected_for_an_instant_concept(self) -> None:
        """§8: reported nature must match the concept's expected nature --
        never silently coerced."""
        period = period_from_xbrl_fact(
            {"start": "2025-01-01", "end": "2025-12-31"}, period_type=PeriodType.INSTANT
        )

        assert period is None

    def test_an_instant_fact_is_rejected_for_a_duration_concept(self) -> None:
        period = period_from_xbrl_fact({"end": "2025-12-31"}, period_type=PeriodType.DURATION)

        assert period is None

    def test_missing_end_date_yields_no_period(self) -> None:
        assert period_from_xbrl_fact({}, period_type=PeriodType.INSTANT) is None


class TestParsePeriodLabel:
    def test_year_ended_phrasing_is_a_duration(self) -> None:
        result = parse_period_label("Year Ended December 31, 2025")

        assert result == (PeriodType.DURATION, date(2025, 12, 31))

    def test_plural_years_ended_phrasing_is_a_duration(self) -> None:
        result = parse_period_label("Years Ended December 31, 2025")

        assert result is not None
        assert result[0] is PeriodType.DURATION

    def test_bare_date_is_an_instant(self) -> None:
        """§8's own example: a bare balance-sheet date must not be read as a
        duration just because it shares an end date with one."""
        result = parse_period_label("December 31, 2025")

        assert result == (PeriodType.INSTANT, date(2025, 12, 31))

    def test_as_of_phrasing_is_an_instant(self) -> None:
        result = parse_period_label("As of December 31, 2025")

        assert result == (PeriodType.INSTANT, date(2025, 12, 31))

    def test_no_date_returns_none(self) -> None:
        assert parse_period_label("Total assets") is None


class TestIsAnnualPeriod:
    """Regression coverage for a real bug: iHeartMedia's 2016 10-K tags
    `Revenues` for each of 2015 Q1-Q4 *and* full-year 2015 under the same
    concept and accession (a "selected quarterly financial data" footnote).
    A period keyed only by `end.year` folded a quarter's revenue into the
    same bucket as the annual figure -- this is the check that prevents it.
    """

    def test_full_year_duration_matching_the_fiscal_year_end_is_annual(self) -> None:
        period = Period(
            period_type=PeriodType.DURATION, start=date(2015, 1, 1), end=date(2015, 12, 31)
        )

        assert is_annual_period(period, 12, 31)

    def test_q1_is_rejected_its_end_date_is_far_from_the_fiscal_year_end(self) -> None:
        period = Period(
            period_type=PeriodType.DURATION, start=date(2015, 1, 1), end=date(2015, 3, 31)
        )

        assert not is_annual_period(period, 12, 31)

    def test_q4_is_rejected_even_though_its_end_date_is_the_fiscal_year_end(self) -> None:
        """The end date alone is not enough -- Q4 ends exactly on the fiscal
        year end, so only the span check catches it."""
        period = Period(
            period_type=PeriodType.DURATION, start=date(2015, 10, 1), end=date(2015, 12, 31)
        )

        assert not is_annual_period(period, 12, 31)

    def test_instant_period_only_needs_the_end_date_near_the_anchor(self) -> None:
        period = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))

        assert is_annual_period(period, 12, 31)

    def test_instant_period_far_from_the_fiscal_year_end_is_rejected(self) -> None:
        period = Period(period_type=PeriodType.INSTANT, end=date(2025, 6, 30))

        assert not is_annual_period(period, 12, 31)

    def test_a_52_53_week_fiscal_calendars_drift_is_tolerated(self) -> None:
        """A company whose fiscal year ends "the last Saturday of December"
        can land a few days either side of Dec 31 from one year to the next."""
        period = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 27))

        assert is_annual_period(period, 12, 31)

    def test_a_december_january_boundary_fiscal_year_end_does_not_look_far_from_itself(
        self,
    ) -> None:
        """A fiscal year ending Dec 31 and a balance a couple of days into
        the *next* calendar year are the same event -- the distance check
        must look at the surrounding years, not just `candidate.year`'s own
        anchor, or this would appear ~363 days away instead of 2."""
        period = Period(period_type=PeriodType.INSTANT, end=date(2026, 1, 2))

        assert is_annual_period(period, 12, 31)
