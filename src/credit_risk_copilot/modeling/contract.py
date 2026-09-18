"""The point-in-time contract: what a historical observation is allowed to know.

Every supervised row in this project is a claim of the form:

    "Using only what SEC had published about company C on or before date T,
     here is what happened to C in the window (T, T + horizon]."

The single failure mode that invalidates such a claim is temporal leakage: a
feature that could not have been computed on date T. In this project leakage
has three plausible routes, and this module exists to close all three
explicitly rather than by convention.

**Route 1 — a later filing.** A 10-K filed after T describes periods that end
before T, so it *looks* like history. `financials.history.resolve_company_history`
takes `filed_on_or_before` and drops those filings before the resolver ever
sees them, so their facts cannot reach a feature at all.

**Route 2 — a restatement inside an allowed filing.** Two filings both filed
on or before T may report the same fiscal period differently.
`CompanyFinancials.as_of` resolves this by keeping the *earliest-filed* value
(D-008). That is the value an analyst would have been looking at, and it is
also the conservative choice: a later restatement is frequently the moment bad
news becomes visible, so preferring it would import hindsight.

**Route 3 — the label.** A label built from an event that had not yet been
recorded is not observable either. `labels.py` handles this with an explicit
label-completeness cutoff rather than assuming the event source is current.

## What `information_cutoff` is, precisely

`information_cutoff` is the SEC *filing receipt date* (`filingDate`), never the
fiscal period end. A 10-K for FY2019 filed 2020-03-31 tells you nothing on
2020-01-01. Every observation is therefore anchored to a real publication
event, which is also why observations are spaced like filings rather than like
calendar years.

## Why the observation *is* a filing

The product (D-001) re-assesses a company when it publishes. Making the
observation unit "a filing" rather than "a fiscal year" means the model is
trained on exactly the moments it will be asked to score, and that
`information_cutoff` needs no invention: it is the filing's own `filed` date.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeakageError(AssertionError):
    """A constructed observation violates the point-in-time contract.

    Deliberately an `AssertionError` subclass: this is never an expected
    runtime condition to be handled, it is a bug in dataset construction, and
    it should stop the build rather than be caught and logged.
    """


class ObservationKey(BaseModel):
    """What identifies one point-in-time observation, and when it was knowable."""

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    #: The date the assessment is made -- equal to `information_cutoff`. Kept
    #: as its own field because the two are conceptually distinct (one is
    #: "when we are asked", the other "what we may look at") even though this
    #: design deliberately makes them the same date.
    prediction_date: date
    #: The latest SEC filing receipt date whose contents may inform this row.
    information_cutoff: date
    #: The accession of the filing that triggered this observation.
    source_accession: str
    source_form: str
    #: The fiscal period the triggering filing reports, e.g. "FY2019".
    fiscal_period_label: str
    #: Every accession whose facts actually reached this row's features --
    #: the provenance trail from feature back to filing (§14).
    contributing_accessions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _cutoff_not_after_prediction(self) -> ObservationKey:
        if self.information_cutoff > self.prediction_date:
            raise LeakageError(
                f"CIK{self.cik} {self.source_accession}: information_cutoff "
                f"{self.information_cutoff} is after prediction_date {self.prediction_date}."
            )
        return self


class Outcome(BaseModel):
    """What happened in the observation's forward window, if we can tell."""

    model_config = ConfigDict(frozen=True)

    #: 1 = the modelled event occurred in `(prediction_date, horizon_end]`;
    #: 0 = it did not, and we can see the whole window; `None` = censored, the
    #: window is not fully observable and this row must not be used as either
    #: a positive or a negative.
    label: int | None
    horizon_end: date
    #: Set only when `label == 1`.
    event_date: date | None = None
    days_to_event: int | None = None
    #: Why the row is censored, when it is.
    censoring_reason: str | None = None

    @model_validator(mode="after")
    def _label_consistency(self) -> Outcome:
        if self.label == 1 and self.event_date is None:
            raise ValueError("A positive outcome must carry its event_date.")
        if self.label is None and not self.censoring_reason:
            raise ValueError("A censored outcome must state why.")
        if self.label == 0 and self.event_date is not None:
            raise ValueError("A negative outcome must not carry an event_date.")
        return self

    @property
    def is_usable(self) -> bool:
        return self.label is not None


class Observation(BaseModel):
    """One row of the modelling panel: key + features + outcome.

    Features are `float | None`. `None` means *not computable from the
    information available at the cutoff* and is preserved all the way to the
    model, never silently replaced by zero (§15) -- `features.py` documents
    the distinction each feature draws, and `dataset.py` emits a companion
    missingness indicator where the absence is itself informative.
    """

    model_config = ConfigDict(frozen=True)

    key: ObservationKey
    features: dict[str, float | None]
    outcome: Outcome

    def assert_no_future_information(self, filing_dates: dict[str, date]) -> None:
        """Verify every contributing accession was filed on or before the cutoff.

        `filing_dates` maps accession -> SEC receipt date. Raises
        `LeakageError` on the first violation. This is the assertion that
        makes route 1 a checked property rather than a claim about how the
        builder was written; `dataset.py` calls it for every row it emits and
        `tests/test_modeling_contract.py` calls it on deliberately corrupted
        input.
        """
        for accession in self.key.contributing_accessions:
            filed = filing_dates.get(accession)
            if filed is None:
                raise LeakageError(
                    f"CIK{self.key.cik}: accession {accession} contributed to features but has "
                    "no known filing date, so its timeliness cannot be verified."
                )
            if filed > self.key.information_cutoff:
                raise LeakageError(
                    f"CIK{self.key.cik}: accession {accession} was filed {filed}, after the "
                    f"information cutoff {self.key.information_cutoff}."
                )


class HorizonPolicy(BaseModel):
    """How the forward window and its observability are defined."""

    model_config = ConfigDict(frozen=True)

    #: Length of the forward window, in days.
    horizon_days: int = Field(gt=0)
    #: The last date for which the event source is believed to record events
    #: completely. A row whose `horizon_end` falls after this is censored --
    #: an absent event after this date is unobserved, not evidence of
    #: survival. See `labels.py` for how this date was measured rather than
    #: assumed.
    label_complete_through: date

    def horizon_end(self, prediction_date: date) -> date:
        return prediction_date + timedelta(days=self.horizon_days)

    def is_observable(self, prediction_date: date) -> bool:
        return self.horizon_end(prediction_date) <= self.label_complete_through

    def describe(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "label_complete_through": self.label_complete_through.isoformat(),
            "latest_usable_prediction_date": (
                self.label_complete_through - timedelta(days=self.horizon_days)
            ).isoformat(),
        }
