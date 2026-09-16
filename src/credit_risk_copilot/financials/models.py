"""Canonical financial-fact schema: the Phase 5 → Phase 6 boundary.

Phase 4 answers "what can we retrieve, and where from" (`extraction/models.py`).
This module answers "what does that represent financially": one typed,
provenance-carrying fact per (canonical concept, fiscal period), regardless of
whether it came from XBRL, a document table, or a derivation.

Design principles carried over from Phase 4 and made explicit here because
Phase 6+ depends on them:

- **Evidence or nothing.** Every `CanonicalFact` carries `provenance`, even a
  `MISSING` one (the reason it's missing is itself provenance).
- **Missing is not zero.** A `CanonicalFact` with `status=MISSING` has
  `value=None`, never a fabricated `0`.
- **Derived is never disguised as reported.** `origin` distinguishes a value
  taken directly from a filing from one this pipeline computed.
- **Conflicts are preserved, not silently resolved.** `candidates` holds every
  disagreeing value when `status=CONFLICTING`.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FiscalPeriodLabel = Literal["FY", "Q1", "Q2", "Q3", "Q4"]


class PeriodType(str, Enum):
    """Whether a fact is a balance (a moment) or a flow (a span).

    Confusing the two is a real bug class (§8 of the phase brief): "December
    31, 2025" (instant) and "Year ended December 31, 2025" (duration) are not
    the same period even though they share an end date.
    """

    INSTANT = "instant"
    DURATION = "duration"


class StatementType(str, Enum):
    """Which financial statement a fact or table belongs to."""

    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    EQUITY = "equity"
    NOTES = "notes"
    OTHER = "other"


class SourceType(str, Enum):
    XBRL = "xbrl"
    HTML = "html"
    PDF = "pdf"
    DERIVED = "derived"
    MANUAL = "manual"


class FactStatus(str, Enum):
    """Whether, and how, a canonical fact was resolved.

    Kept small on purpose (§14 of the phase brief): downstream code branches
    on this, so each state must mean one thing.
    """

    #: Resolved directly from a single, unambiguous source tag/cell.
    FOUND = "found"
    #: Computed from other canonical facts because no direct tag existed.
    DERIVED = "derived"
    #: No sufficiently reliable source found.
    MISSING = "missing"
    #: Two or more sources/tags disagree; both are kept, none is chosen.
    CONFLICTING = "conflicting"
    #: A value exists but is weak enough (single alternative concept, unusual
    #: magnitude, failed validation) that an analyst should look at it.
    REQUIRES_REVIEW = "requires_review"
    #: An analyst overwrote the extracted value; the original is preserved.
    MANUALLY_CORRECTED = "manually_corrected"


class Confidence(str, Enum):
    """Coarse trust signal. Deliberately not a float (§20): a manufactured
    0.87 would look like evidence without being any."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Origin(str, Enum):
    """Was this fact reported by the filer, or computed by this pipeline?"""

    REPORTED = "reported"
    DERIVED = "derived"


class Period(BaseModel):
    """A fiscal period, point-in-time (instant) or flow (duration).

    Identity is the actual `end` date (and `start` for durations), not the
    filing-level `fy`/`fp` XBRL fields -- `golden_set.md` §2 notes those
    describe the *filing's* fiscal context, not each comparative column's own
    period, so several rows in one filing legitimately share one `fy` while
    their `end` dates span different years.

    Annual-only scope (D-007): `fiscal_year` is read off `end.year`, which is
    correct for the annual columns a 10-K reports. Quarterly support would
    need `fiscal_period` to stop defaulting to "FY".
    """

    model_config = ConfigDict(frozen=True)

    period_type: PeriodType
    start: date | None = None
    end: date
    fiscal_period: FiscalPeriodLabel = "FY"

    @model_validator(mode="after")
    def _instant_has_no_start(self) -> Period:
        if self.period_type is PeriodType.INSTANT and self.start is not None:
            raise ValueError("An instant period has no start date -- it is a single moment.")
        if self.period_type is PeriodType.DURATION and self.start is None:
            raise ValueError("A duration period needs a start date to define its span.")
        return self

    @property
    def fiscal_year(self) -> int:
        return self.end.year

    @property
    def label(self) -> str:
        """The canonical period identifier facts are keyed and grouped by."""
        if self.fiscal_period == "FY":
            return f"FY{self.fiscal_year}"
        return f"FY{self.fiscal_year}-{self.fiscal_period}"


class Provenance(BaseModel):
    """Where one fact -- or one candidate, or one input to a derivation --
    came from. This is what lets the dashboard answer "where did this number
    come from" (§15) without duplicating raw document content: it references
    Phase 4 evidence (accession, page, section) rather than copying it.
    """

    model_config = ConfigDict(frozen=True)

    source_type: SourceType
    extraction_method: str
    #: Raw XBRL tag, e.g. "Revenues" -- unset for non-XBRL sources.
    concept: str | None = None
    namespace: str | None = None
    is_extension_concept: bool = False
    cik: int | None = None
    accession: str | None = None
    form: str | None = None
    filed: str | None = None
    document_uri: str | None = None
    page: int | None = None
    section_id: str | None = None
    #: The value/text as it actually appeared at the source, before any
    #: normalisation -- e.g. "(1,250)" or the raw XBRL `val`.
    original_text: str | None = None
    original_value: float | None = None
    notes: str | None = None


class CandidateValue(BaseModel):
    """Another value reported for the same concept and period, kept in full.

    On a `CONFLICTING` fact these are the disagreeing synonyms -- never
    averaged, never silently dropped (§13): a caller sees both 12,400 and
    11,400 and decides. On a `FOUND` fact resolved by preferred scope they are
    the differently-scoped alternatives that were deliberately not chosen
    (e.g. consolidated net income beside the parent's), kept as evidence.
    """

    model_config = ConfigDict(frozen=True)

    value: float
    provenance: Provenance


class ManualCorrection(BaseModel):
    """An analyst's override, with the original extraction preserved (§19).

    `CanonicalFact.provenance` is never overwritten; the pre-correction value
    and its provenance stay exactly where they were, and this sits alongside.
    """

    model_config = ConfigDict(frozen=True)

    value: float
    reason: str
    corrected_by: str
    corrected_at: str
    previous_value: float | None
    previous_status: FactStatus


class CanonicalFact(BaseModel):
    """One canonical concept, for one period, for one filing.

    `value=None` is the norm for `MISSING`, never a fabricated `0` (§18).
    """

    model_config = ConfigDict(frozen=True)

    concept: str
    statement: StatementType
    period: Period
    value: float | None
    currency: str = "USD"
    status: FactStatus
    confidence: Confidence
    origin: Origin
    #: Set only when `origin=DERIVED`, e.g. "total_assets - total_equity".
    formula: str | None = None
    #: The canonical concepts a derivation consumed, in formula order. Lets a
    #: caller reconstruct derived -> inputs -> sources without parsing
    #: `formula`, and lets validation refuse to "confirm" a value using the
    #: very identity it was derived from.
    derived_from: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    candidates: tuple[CandidateValue, ...] = ()
    reason: str | None = None
    correction: ManualCorrection | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status in (FactStatus.FOUND, FactStatus.DERIVED, FactStatus.MANUALLY_CORRECTED)

    @property
    def effective_value(self) -> float | None:
        """The value downstream ratio code should use: the correction if one
        exists, otherwise the extracted value. Never the value for a
        `CONFLICTING` or `MISSING` fact."""
        if self.correction is not None:
            return self.correction.value
        if self.status in (FactStatus.FOUND, FactStatus.DERIVED):
            return self.value
        return None


class ValidationResult(BaseModel):
    """One consistency check's outcome (§17): a flag, never a rejection."""

    model_config = ConfigDict(frozen=True)

    rule: str
    passed: bool
    message: str
    period_label: str | None = None
    details: dict[str, float | str | None] = Field(default_factory=dict)


class CanonicalFilingFacts(BaseModel):
    """Everything Phase 5 resolved from one filing."""

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    accession: str
    form: str
    filed: str
    #: The filing's own declared fiscal context (dei:DocumentFiscalYear/PeriodFocus
    #: equivalents from XBRL `fy`/`fp`) -- filing-level, not per-period; see `Period`.
    fiscal_year: int | None
    fiscal_period: FiscalPeriodLabel | None
    facts: tuple[CanonicalFact, ...]
    validations: tuple[ValidationResult, ...] = ()

    def get(self, concept: str, period_label: str) -> CanonicalFact | None:
        return next(
            (f for f in self.facts if f.concept == concept and f.period.label == period_label),
            None,
        )

    def by_statement(self, statement: StatementType) -> tuple[CanonicalFact, ...]:
        return tuple(f for f in self.facts if f.statement is statement)

    def by_period(self, period_label: str) -> tuple[CanonicalFact, ...]:
        return tuple(f for f in self.facts if f.period.label == period_label)

    @property
    def period_labels(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for f in self.facts:
            seen.setdefault(f.period.label, None)
        return tuple(seen)

    @property
    def completeness(self) -> float:
        """Fraction of (concept, period) slots resolved -- FOUND, DERIVED or
        MANUALLY_CORRECTED. A coverage number for triage, not a score to
        optimise blindly (mirrors `ExtractionDiagnostics.looks_complete`)."""
        if not self.facts:
            return 0.0
        return sum(1 for f in self.facts if f.is_resolved) / len(self.facts)
