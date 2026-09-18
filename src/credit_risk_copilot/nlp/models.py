"""Typed narrative risk signals, with a verbatim quote behind every one.

The product rule for this layer is stricter than for any other. A ratio can be
recomputed from its inputs and a model score can be re-derived from its
features, but a claim about what a filing *says* is only checkable against the
filing's own words. So `NarrativeRiskSignal` cannot exist without an
`EvidenceQuote`, the quote stores the character span it came from, and SC-03 is
a string comparison anyone can run: slice the document at the span and it must
equal the quote.

Two schema choices carry most of the weight.

**A signal names why it fired *and how sure the language is*.** Filings talk
about distress in two grammatical moods. "There exists substantial doubt
whether we will be able to continue as a going concern" is a statement of fact
about the filer. "If we are unable to refinance, we may be unable to continue
as a going concern" is a hypothetical, and every 10-K ever written contains
hundreds of them. A layer that cannot tell the two apart fires on every filing
and is worth nothing. `Assertion` is therefore a first-class field, and the
extractor's default is to emit only `ASSERTED` matches -- but the hypothetical
and cross-reference matches are *available*, because "this company's risk
factors newly discuss covenant breach" is a weaker signal, not a non-signal.

**Specificity is declared per signal, not inferred from counts.** Some of these
phrases are near-proof of distress and some are ordinary corporate English.
`RiskSignalDefinition.specificity` records which, measured on the evaluation
corpus rather than guessed, so a downstream consumer weighting signals does not
have to rediscover that "impairment charge" appears in Coca-Cola's MD&A
sixteen times.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RiskSignalCode(str, Enum):
    """The signal catalog, as machine-readable codes.

    Same discipline as `WarningCode` (D-021) and `CaveatCode` (D-029): a
    downstream consumer branches on a code, never on a substring of English.
    """

    #: Management or the auditor states substantial doubt about the filer's
    #: ability to continue as a going concern. The single strongest narrative
    #: credit signal a filing can carry.
    GOING_CONCERN_DOUBT = "going_concern_doubt"
    #: The filer states it was not in compliance with a debt covenant.
    COVENANT_BREACH = "covenant_breach"
    #: A covenant was waived, or an agreement amended, to avoid or cure a
    #: breach -- distress that has already been papered over.
    COVENANT_WAIVER_OR_AMENDMENT = "covenant_waiver_or_amendment"
    #: An event of default has occurred, or debt has been accelerated or
    #: reclassified to current because of one.
    DEBT_DEFAULT_OR_ACCELERATION = "debt_default_or_acceleration"
    #: An out-of-court restructuring is under way: forbearance, exchange offer,
    #: restructuring support agreement, or restructuring advisers engaged.
    DEBT_RESTRUCTURING = "debt_restructuring"
    #: Bankruptcy protection is contemplated, prepared for, or already filed.
    BANKRUPTCY_CONTEMPLATED = "bankruptcy_contemplated"
    #: The filer states its resources may not be sufficient to meet its
    #: obligations -- a liquidity statement about itself, not about markets.
    LIQUIDITY_SHORTFALL = "liquidity_shortfall"
    #: A material weakness in internal control over financial reporting was
    #: identified. Bears on whether the *numbers* in this filing can be trusted.
    MATERIAL_WEAKNESS = "material_weakness"
    #: The dividend was suspended, eliminated or cut.
    DIVIDEND_SUSPENSION = "dividend_suspension"
    #: An exchange notified the filer that it no longer meets listing standards.
    DELISTING_NOTICE = "delisting_notice"
    #: A rating agency downgraded the filer.
    CREDIT_RATING_DOWNGRADE = "credit_rating_downgrade"
    #: An impairment was recognised. Deliberately in the catalog despite being
    #: common in healthy filers: it is evidence when it is large or repeated,
    #: and its measured specificity says so.
    ASSET_IMPAIRMENT = "asset_impairment"


class Assertion(str, Enum):
    """What grammatical mood the matched sentence is in.

    This is the distinction that makes the layer useful, so it is a field
    rather than a filter applied and forgotten.
    """

    #: The filer states this about itself as a fact or a current condition.
    ASSERTED = "asserted"
    #: Conditional or modal -- "if we fail to", "we may be unable to". The
    #: overwhelming majority of Item 1A.
    HYPOTHETICAL = "hypothetical"
    #: A pointer to where the topic is discussed ("see Note 1"), which asserts
    #: nothing on its own.
    CROSS_REFERENCE = "cross_reference"
    #: The trigger is explicitly denied -- "no event of default has occurred",
    #: "we were in compliance with all covenants". Retained rather than
    #: dropped: an explicit denial is itself worth showing an analyst.
    NEGATED = "negated"


class Specificity(str, Enum):
    """How much a signal's presence alone tells you, measured on the corpus.

    Set from the evaluation run (`docs/nlp_risk_signals.md` §6), not from
    intuition. A `LOW` signal is not noise -- it is information that needs
    corroboration before it means anything.
    """

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class EvidenceQuote(BaseModel):
    """A verbatim span of a source document, and where it came from.

    `text` must equal `document.text[char_start:char_end]`. Nothing normalises,
    trims or prettifies it on the way out -- the whole point is that a reader
    can find these exact characters in the filing. SC-03 is the automated check
    that this holds for every quote the pipeline emits.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    section_id: str | None = None
    #: The matched trigger's offsets **relative to `text`**, so a UI can
    #: highlight the phrase inside the sentence without re-running the regex.
    trigger_start: int = Field(ge=0)
    trigger_end: int = Field(ge=0)
    #: Filing identity, absent for an analyst-uploaded document (FR-04).
    accession: str | None = None
    form: str | None = None
    filed: str | None = None

    @property
    def trigger_text(self) -> str:
        return self.text[self.trigger_start : self.trigger_end]


class NarrativeRiskSignal(BaseModel):
    """One risk signal, its evidence, and how sure the language was."""

    model_config = ConfigDict(frozen=True)

    code: RiskSignalCode
    label: str
    assertion: Assertion
    specificity: Specificity
    quote: EvidenceQuote
    #: Which pattern in the catalog matched, so a false positive can be traced
    #: to one editable line rather than to "the NLP".
    pattern_id: str

    @property
    def is_asserted(self) -> bool:
        return self.assertion is Assertion.ASSERTED


class SectionCoverage(BaseModel):
    """Which narrative sections were actually read, and which were not.

    A signal layer that reports "no signals" is saying something very
    different depending on whether it read Item 7 or failed to find it. That
    difference is recorded rather than left for a reader to assume (the
    fail-safe NFR, and A-10's open measurement).
    """

    model_config = ConfigDict(frozen=True)

    section_id: str
    located: bool
    characters: int = Field(default=0, ge=0)
    sentences: int = Field(default=0, ge=0)
    reason: str | None = None


class NarrativeRiskReport(BaseModel):
    """Every signal found in one filing's narrative sections."""

    model_config = ConfigDict(frozen=True)

    cik: int | None = None
    company: str | None = None
    accession: str | None = None
    form: str | None = None
    filed: str | None = None
    signals: tuple[NarrativeRiskSignal, ...] = ()
    coverage: tuple[SectionCoverage, ...] = ()
    #: Catalog version, so a stored report says which rules produced it
    #: (FR-21 records pipeline versions per assessment).
    catalog_version: str = "1.0"

    @property
    def asserted(self) -> tuple[NarrativeRiskSignal, ...]:
        """The signals the filer states about itself -- the usable headline."""
        return tuple(signal for signal in self.signals if signal.is_asserted)

    def codes(self, *, asserted_only: bool = True) -> frozenset[RiskSignalCode]:
        source = self.asserted if asserted_only else self.signals
        return frozenset(signal.code for signal in source)

    def by_code(self, code: RiskSignalCode) -> tuple[NarrativeRiskSignal, ...]:
        return tuple(signal for signal in self.signals if signal.code is code)

    @property
    def sections_read(self) -> tuple[str, ...]:
        return tuple(c.section_id for c in self.coverage if c.located)

    @property
    def sections_missing(self) -> tuple[str, ...]:
        return tuple(c.section_id for c in self.coverage if not c.located)
