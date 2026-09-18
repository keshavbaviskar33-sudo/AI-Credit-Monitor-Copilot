"""Target construction: events, censoring and label completeness.

The rule these tests defend is that a `0` must mean "we watched the whole
window and nothing happened", never "we could not see". Everything else in
Phase 8 is downstream of that distinction.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from credit_risk_copilot.modeling.contract import HorizonPolicy
from credit_risk_copilot.modeling.labels import (
    BankruptcyCase,
    EventTable,
    load_event_table,
    measure_filing_to_event_gap,
    measure_label_completeness,
    parse_brd_date,
)

_CSV_HEADER = "NameCorp,CikBefore,DateFiled,Chapter,DateEmerging,DateDisposed\n"


def _table(*cases: BankruptcyCase) -> EventTable:
    by_cik: dict[int, list[BankruptcyCase]] = {}
    for case in cases:
        by_cik.setdefault(case.cik, []).append(case)
    return EventTable(
        cases_by_cik={
            cik: tuple(sorted(items, key=lambda c: c.filed)) for cik, items in by_cik.items()
        }
    )


def _case(cik: int, filed: str, resolved: str | None = None) -> BankruptcyCase:
    return BankruptcyCase(
        cik=cik,
        company="Test Co",
        filed=date.fromisoformat(filed),
        chapter="11",
        resolved=date.fromisoformat(resolved) if resolved else None,
    )


def _policy(days: int = 365, through: str = "2020-12-31") -> HorizonPolicy:
    return HorizonPolicy(horizon_days=days, label_complete_through=date.fromisoformat(through))


class TestDateParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("3/25/2009", date(2009, 3, 25)), ("2009-03-25", date(2009, 3, 25))],
    )
    def test_both_formats_brd_actually_uses(self, raw: str, expected: date) -> None:
        assert parse_brd_date(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "not a date", None])
    def test_unparseable_is_absent_rather_than_guessed(self, raw: str | None) -> None:
        assert parse_brd_date(raw) is None


class TestOutcome:
    def test_an_event_inside_the_window_is_a_positive_with_its_date(self) -> None:
        table = _table(_case(1, "2019-08-15"))

        outcome = table.outcome(1, date(2019, 3, 1), _policy())

        assert outcome.label == 1
        assert outcome.event_date == date(2019, 8, 15)
        assert outcome.days_to_event == 167

    def test_an_event_just_past_the_window_is_a_genuine_negative(self) -> None:
        """The company did fail -- but not within the horizon. `0` is the
        correct answer to the question asked, not a mislabelled positive."""
        table = _table(_case(1, "2020-06-01"))

        outcome = table.outcome(1, date(2019, 3, 1), _policy())

        assert outcome.label == 0
        assert outcome.event_date is None

    def test_a_company_with_no_event_is_a_negative_when_the_window_is_observable(self) -> None:
        outcome = _table().outcome(99, date(2019, 3, 1), _policy())

        assert outcome.label == 0

    def test_an_unobservable_window_is_censored_not_negative(self) -> None:
        """The failure mode this whole design exists to prevent: scoring the
        most recent rows as survivals because the event source has not caught
        up yet."""
        outcome = _table().outcome(99, date(2020, 6, 1), _policy())

        assert outcome.label is None
        assert outcome.censoring_reason is not None
        assert "after the event source is complete" in outcome.censoring_reason

    def test_an_unobservable_window_is_censored_even_when_an_event_is_recorded(self) -> None:
        """Keeping known events past the cutoff while censoring the unknown
        non-events is selection on the outcome: the period becomes 100%
        positive. Measured on the real corpus, the earlier ordering produced
        three folds whose every row was an event."""
        table = _table(_case(1, "2020-09-01"))

        outcome = table.outcome(1, date(2020, 6, 1), _policy())

        assert outcome.label is None
        assert outcome.censoring_reason is not None
        assert "selecting on the outcome" in outcome.censoring_reason

    def test_a_row_inside_an_active_proceeding_is_censored(self) -> None:
        """A debtor keeps filing 10-Ks in Chapter 11. Asking whether it will
        file for bankruptcy is not the product's question."""
        table = _table(_case(1, "2018-05-01", resolved="2020-02-01"))

        outcome = table.outcome(1, date(2019, 3, 1), _policy())

        assert outcome.label is None
        assert outcome.censoring_reason is not None
        assert "active" in outcome.censoring_reason

    def test_a_company_that_emerged_is_at_risk_again(self) -> None:
        """BRD records 50 CIKs with more than one case, so exclusion has to
        cover the case window, not everything after the first filing."""
        table = _table(_case(1, "2015-05-01", resolved="2016-06-01"), _case(1, "2019-09-01"))

        assert table.outcome(1, date(2019, 3, 1), _policy()).label == 1
        assert table.outcome(1, date(2017, 3, 1), _policy()).label == 0

    def test_an_unresolved_case_covers_everything_after_it(self) -> None:
        table = _table(_case(1, "2016-05-01", resolved=None))

        assert table.outcome(1, date(2019, 3, 1), _policy()).label is None


class TestLoadEventTable:
    def test_rows_without_a_usable_cik_or_date_are_dropped(self, tmp_path: Path) -> None:
        csv = tmp_path / "cases.csv"
        csv.write_text(
            _CSV_HEADER
            + "Good Co,0000001234,3/25/2009,11,,\n"
            + "No Cik,,5/1/2010,11,,\n"
            + "Zero Cik,0,5/1/2010,11,,\n"
            + "No Date,0000005678,,11,,\n",
            encoding="utf-8",
        )

        table = load_event_table(csv)

        assert table.case_count == 1
        assert table.cases(1234)[0].filed == date(2009, 3, 25)

    def test_resolution_date_falls_back_across_brd_columns(self, tmp_path: Path) -> None:
        csv = tmp_path / "cases.csv"
        csv.write_text(
            _CSV_HEADER + "Emerged Co,0000001234,3/25/2009,11,,7/1/2011\n", encoding="utf-8"
        )

        table = load_event_table(csv)

        assert table.cases(1234)[0].resolved == date(2011, 7, 1)


class TestLabelCompleteness:
    def _table_with_counts(self, counts: dict[int, int]) -> EventTable:
        cases = [
            _case(year * 100 + i, f"{year}-06-0{(i % 9) + 1}")
            for year, count in counts.items()
            for i in range(count)
        ]
        return _table(*cases)

    def test_a_truncated_tail_is_detected_and_excluded(self) -> None:
        """BRD's final release years are thin because case entry lags the
        petition. The cutoff has to be measured from the counts, not read off
        the release date."""
        counts = dict.fromkeys(range(2011, 2020), 25)
        counts[2020] = 24
        counts[2021] = 3
        counts[2022] = 1

        measurement = self._table_with_counts(counts)
        result = measure_label_completeness(measurement)

        assert result.reference_median == 25.0
        assert result.last_complete_year == 2020
        assert result.label_complete_through == date(2020, 12, 31)

    def test_a_genuinely_quiet_but_complete_year_is_kept(self) -> None:
        """Real bankruptcy counts halve in easy-credit years, so the bar is
        deliberately loose -- only a much sharper drop reads as truncation."""
        counts = dict.fromkeys(range(2011, 2020), 25)
        counts[2020] = 14

        result = measure_label_completeness(self._table_with_counts(counts))

        assert result.last_complete_year == 2020


class TestFilingToEventGap:
    def test_the_gap_distribution_drives_the_horizon_choice(self) -> None:
        table = _table(_case(1, "2019-06-01"), _case(2, "2019-06-01"), _case(3, "2019-06-01"))
        last_filings = {
            1: date(2019, 3, 1),  # 92 days
            2: date(2018, 9, 1),  # 273 days
            3: date(2017, 12, 1),  # 547 days
        }

        gap = measure_filing_to_event_gap(table, last_filings)

        assert gap["n"] == 3.0
        assert gap["median"] == 273.0
        assert gap["share_within_365d"] == pytest.approx(2 / 3)
        assert gap["share_within_730d"] == 1.0
