"""The outcome: bankruptcy events from BRD, turned into observable labels.

The event source is the Florida-UCLA-LoPucki Bankruptcy Research Database
(D-013). It records US public-company Chapter 7/11 petitions, one row per
case, with the petition date (`DateFiled`), the chapter, the debtor's CIK, and
disposition/emergence dates.

## This module refuses to invent a label

Three things are *not* labels here, per the phase brief's absolute rule:
Phase 7 deterioration signals, ratio thresholds, and any model's own output.
The only positive class is "this company filed a bankruptcy petition recorded
by BRD", which is an externally observed legal event with a date.

## Three real properties of the source that the label design must respect

**1. Coverage stops, and thins before it stops.** BRD's last release is
December 2022, and case entry lags the petition (cases are catalogued as the
docket develops). Counting petitions per year shows the tail thinning well
before the nominal end, so the last fully-trustworthy year has to be *measured*
from the data (`measure_label_completeness`), not read off the release date. A
row whose forward window extends past that point is censored, not negative --
an event that had not yet been catalogued is unobserved, and scoring it as
survival would teach the model that the recent past was safe.

**2. BRD only covers large public filers.** Its inclusion rule is a public
company filing 10-Ks with assets above a size threshold. A small filer that
failed quietly is absent, so a `0` label means "no *large public* bankruptcy
was recorded", not "nothing bad happened". This is label noise pushed entirely
into the negative class, and it is documented rather than corrected, because
correcting it would require an event source this project does not have.

**3. A company can be in bankruptcy and still file.** A debtor in Chapter 11
keeps filing 10-Ks. Asking "will this company file for bankruptcy in the next
year" of a company that is already in bankruptcy is not the product's question
and its answer is contaminated by the proceeding itself, so observations inside
an active case are excluded rather than labelled either way. A company that
emerges is at risk again (BRD records 50 CIKs with more than one case), so
exclusion covers the case window, not everything after it.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.modeling.contract import HorizonPolicy, Outcome

#: BRD ships US-style dates; a couple of columns are ISO. Both are accepted,
#: anything else is treated as absent rather than guessed at.
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")


def parse_brd_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class BankruptcyCase(BaseModel):
    """One BRD case, reduced to the fields the label needs."""

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    filed: date
    chapter: str
    #: When the debtor left the proceeding, from whichever of BRD's
    #: `DateEmerging` / `DateEffective` / `DateConvDismiss` / `DateDisposed`
    #: columns is populated. `None` means the case never resolved in the
    #: data -- the company is treated as under the proceeding indefinitely.
    resolved: date | None

    def covers(self, moment: date) -> bool:
        """Whether `moment` falls inside the active proceeding."""
        if moment < self.filed:
            return False
        return self.resolved is None or moment <= self.resolved


class EventTable(BaseModel):
    """Every usable BRD case, indexed by CIK."""

    model_config = ConfigDict(frozen=True)

    cases_by_cik: dict[int, tuple[BankruptcyCase, ...]]

    @property
    def case_count(self) -> int:
        return sum(len(cases) for cases in self.cases_by_cik.values())

    def cases(self, cik: int) -> tuple[BankruptcyCase, ...]:
        return self.cases_by_cik.get(cik, ())

    def first_event_after(self, cik: int, moment: date) -> BankruptcyCase | None:
        later = [case for case in self.cases(cik) if case.filed > moment]
        return min(later, key=lambda c: c.filed) if later else None

    def active_case(self, cik: int, moment: date) -> BankruptcyCase | None:
        for case in self.cases(cik):
            if case.covers(moment):
                return case
        return None

    def outcome(self, cik: int, prediction_date: date, policy: HorizonPolicy) -> Outcome:
        """The label for one (company, date), or a censored outcome with a reason.

        Order matters, and the observability check comes **before** the event
        check on purpose. It is tempting to reason that a recorded event is
        positive evidence and needs no further observation, so a row with a
        known petition could be labelled `1` even past the completeness
        cutoff. That is selection on the outcome: past the cutoff the source
        still records the events it has catalogued but cannot yet confirm the
        non-events, so keeping the positives and censoring the negatives
        yields a period that is **100% positive**. Measured on this corpus,
        doing so produced three folds (2020-2022) whose every row was an
        event -- a base rate of 1.0 -- which distorts both what a model trained
        on them learns and what the pooled evaluation reports. A period that
        cannot be observed completely is dropped completely.
        """
        horizon_end = policy.horizon_end(prediction_date)

        active = self.active_case(cik, prediction_date)
        if active is not None:
            return Outcome(
                label=None,
                horizon_end=horizon_end,
                censoring_reason=(
                    f"Company was inside an active {active.chapter} proceeding filed "
                    f"{active.filed} at the prediction date."
                ),
            )

        if not policy.is_observable(prediction_date):
            return Outcome(
                label=None,
                horizon_end=horizon_end,
                censoring_reason=(
                    f"Forward window ends {horizon_end}, after the event source is complete "
                    f"({policy.label_complete_through}); neither an event nor its absence can "
                    "be established without selecting on the outcome."
                ),
            )

        event = self.first_event_after(cik, prediction_date)
        if event is not None and event.filed <= horizon_end:
            return Outcome(
                label=1,
                horizon_end=horizon_end,
                event_date=event.filed,
                days_to_event=(event.filed - prediction_date).days,
            )

        return Outcome(label=0, horizon_end=horizon_end)


def load_event_table(cases_csv: Path) -> EventTable:
    """Read BRD's `cases.csv` into an `EventTable`.

    Rows without a usable CIK or petition date are dropped -- they cannot be
    joined to SEC data or placed in time, so they can neither label a row nor
    disqualify one.
    """
    by_cik: dict[int, list[BankruptcyCase]] = {}
    with cases_csv.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            raw_cik = (row.get("CikBefore") or "").strip()
            filed = parse_brd_date(row.get("DateFiled"))
            if not raw_cik.isdigit() or int(raw_cik) == 0 or filed is None:
                continue
            resolved = _first_date(
                row, ("DateEmerging", "DateEffective", "DateConvDismiss", "DateDisposed")
            )
            by_cik.setdefault(int(raw_cik), []).append(
                BankruptcyCase(
                    cik=int(raw_cik),
                    company=(row.get("NameCorp") or "").strip(),
                    filed=filed,
                    chapter=(row.get("Chapter") or "").strip(),
                    resolved=resolved,
                )
            )
    return EventTable(
        cases_by_cik={
            cik: tuple(sorted(cases, key=lambda c: c.filed)) for cik, cases in by_cik.items()
        }
    )


def _first_date(row: dict[str, str], columns: tuple[str, ...]) -> date | None:
    for column in columns:
        parsed = parse_brd_date(row.get(column))
        if parsed is not None:
            return parsed
    return None


class CompletenessMeasurement(BaseModel):
    """Where the event source stops being trustworthy, measured not assumed."""

    model_config = ConfigDict(frozen=True)

    last_event_date: date
    cases_per_year: dict[int, int]
    reference_median: float
    #: The last year whose case count is at least `min_share` of the
    #: reference median -- i.e. the last year that does not look truncated.
    last_complete_year: int
    label_complete_through: date


def measure_label_completeness(
    table: EventTable,
    *,
    reference_years: tuple[int, int] = (2011, 2019),
    min_share: float = 0.5,
) -> CompletenessMeasurement:
    """Find the last year BRD appears to record completely.

    Case entry lags the petition, so the final years of any BRD release are
    thin. Rather than trusting the release date, this compares each year's
    case count against the median of a stable reference span and walks back
    from the end until a year clears `min_share` of it.

    `reference_years` deliberately starts after the 2008-2010 crisis spike and
    ends before COVID, so the yardstick is a normal-conditions median rather
    than a crisis one. `min_share` at 0.5 is loose on purpose: real bankruptcy
    counts genuinely halve in easy-credit years, so only a much sharper drop
    should be read as truncation.
    """
    counts = Counter(case.filed.year for cases in table.cases_by_cik.values() for case in cases)
    reference = sorted(
        counts.get(year, 0) for year in range(reference_years[0], reference_years[1] + 1)
    )
    median = (
        (reference[len(reference) // 2])
        if len(reference) % 2
        else (reference[len(reference) // 2 - 1] + reference[len(reference) // 2]) / 2
    )
    last_event = max(case.filed for cases in table.cases_by_cik.values() for case in cases)

    last_complete = last_event.year
    while last_complete > reference_years[1] and counts.get(last_complete, 0) < min_share * median:
        last_complete -= 1

    return CompletenessMeasurement(
        last_event_date=last_event,
        cases_per_year={year: counts.get(year, 0) for year in sorted(counts) if year >= 2005},
        reference_median=float(median),
        last_complete_year=last_complete,
        label_complete_through=date(last_complete, 12, 31),
    )


def measure_filing_to_event_gap(
    table: EventTable, last_filing_before_event: dict[int, date]
) -> dict[str, float]:
    """Distribution of days between a company's last pre-event annual filing
    and its petition date.

    This is what decides the horizon. A horizon shorter than the typical gap
    silently discards events: the company stops filing once it fails, so if
    the last 10-K predates the petition by more than the horizon, no row ever
    carries that event's label.
    """
    gaps = sorted(
        (table.cases(cik)[0].filed - filed).days
        for cik, filed in last_filing_before_event.items()
        if table.cases(cik)
    )
    if not gaps:
        return {}
    return {
        "n": float(len(gaps)),
        "min": float(gaps[0]),
        "p25": float(gaps[len(gaps) // 4]),
        "median": float(gaps[len(gaps) // 2]),
        "p75": float(gaps[3 * len(gaps) // 4]),
        "p90": float(gaps[int(0.9 * len(gaps))]),
        "max": float(gaps[-1]),
        "share_within_365d": sum(1 for g in gaps if 0 < g <= 365) / len(gaps),
        "share_within_547d": sum(1 for g in gaps if 0 < g <= 547) / len(gaps),
        "share_within_730d": sum(1 for g in gaps if 0 < g <= 730) / len(gaps),
    }


def default_horizon_policy(table: EventTable, horizon_days: int) -> HorizonPolicy:
    """A policy whose completeness cutoff is measured from `table`."""
    measurement = measure_label_completeness(table)
    return HorizonPolicy(
        horizon_days=horizon_days,
        label_complete_through=measurement.label_complete_through,
    )


def horizon_end_of(prediction_date: date, horizon_days: int) -> date:
    return prediction_date + timedelta(days=horizon_days)
