"""The combined-assessment schema: the Phase 6-10 -> Phase 12 boundary.

Four layers now analyse a company and none of them share a type. Phase 7 emits
a `FinancialHealthReport`, Phase 8/9 a `ModelExplanation`, Phase 10 a
`NarrativeRiskReport`, and Phase 5 a pile of `CanonicalFact`s underneath all
three. Phase 12 is allowed exactly one grounded LLM call, and FR-17 requires
code -- not the model -- to reject a synthesis that cites evidence which does
not exist or quotes a number that was never measured. That requirement is what
this schema is shaped around.

## What this layer deliberately does not produce

There is **no combined risk score, no overall status, and no ranking of the
four layers against each other.** Every temptation in a "combine the outputs"
phase points at a single number, and this project has refused that number three
times already on the same grounds -- D-010 (the model output is not a
probability of default), D-022 (no composite health score), D-033 (the score is
a position in a ranking). A composite built on top of four layers would be
worse than any of them: it would average a measured ranking metric, a
threshold-driven trend label and a regex hit into one uninspectable digit, and
the digit would be the only thing anyone read.

What a combination layer can honestly add is **the relationship between the
layers**, which none of them can see alone:

- where independent methods agree (`Corroboration`) -- the strongest claim this
  project can make, because the three layers fail in unrelated ways;
- where they disagree (`Contradiction`) -- FR-15, and the more useful half,
  because a disagreement is a fact about the company *or* about the pipeline
  and an analyst needs to see which;
- what each layer did **not** see (`LayerAbsence`, coverage evidence) -- a
  filing with no narrative signals and a filing whose Item 7 was never located
  look identical downstream unless this layer keeps them apart.

## Evidence is addressable, and that is the point

`EvidenceItem.evidence_id` is a content hash. Phase 12's prompt carries these
IDs, the LLM cites them, and `Assessment.validate_citations` checks them
mechanically. `EvidenceItem.numbers` carries every figure that appears in
`summary`, so the same validator can check a drafted sentence's digits against
the evidence it claims to rest on without parsing English.

`identity_key` is the other half: the hash changes when the *values* change,
which is what makes an ID trustworthy, and therefore useless for answering "is
this the same signal as last quarter?". `identity_key` omits the period and the
values, so FR-11's change report can diff two assessments by identity while
citations stay pinned to content.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class LayerId(str, Enum):
    """Which analytical layer an evidence item came from.

    Named after the capability rather than the phase number, because a
    downstream consumer reasons about "what the filer said" versus "what the
    ratios did", not about the order the project happened to build them in.
    """

    #: Phase 6 ratios and Phase 7 trends, dimensions and early-warning signals.
    FINANCIAL_HEALTH = "financial_health"
    #: Phase 8's hazard model as explained by Phase 9.
    PREDICTIVE_MODEL = "predictive_model"
    #: Phase 10's narrative risk signals, with verbatim quotes.
    NARRATIVE = "narrative"
    #: Phase 5 provenance and completeness facts that qualify all of the above.
    DATA_QUALITY = "data_quality"


class EvidenceKind(str, Enum):
    """What an evidence item *is*, independent of which layer produced it."""

    #: One ratio's trend over the analysis window (Phase 7 `RatioTrend`).
    RATIO_TREND = "ratio_trend"
    #: One deterministic early-warning signal (Phase 7 `Signal`).
    HEALTH_SIGNAL = "health_signal"
    #: One dimension's aggregate status (Phase 7 `DimensionHealth`).
    DIMENSION_STATUS = "dimension_status"
    #: The latest period-over-period move in one ratio (Phase 6 `RatioChange`).
    RATIO_CHANGE = "ratio_change"
    #: The model's score and its position in the scored population.
    MODEL_SCORE = "model_score"
    #: One dimension's share of the model's attribution (`DimensionAttribution`).
    MODEL_DRIVER = "model_driver"
    #: One structured reason the model output should not be read at face value.
    MODEL_CAVEAT = "model_caveat"
    #: One narrative signal with its verbatim quote (Phase 10).
    NARRATIVE_SIGNAL = "narrative_signal"
    #: A narrative section that could not be located -- an absence of reading,
    #: which is not the same as an absence of signals.
    NARRATIVE_COVERAGE = "narrative_coverage"
    #: A Phase 5 provenance or completeness caveat on the inputs.
    DATA_QUALITY_CAVEAT = "data_quality_caveat"


#: Two-letter tags that make an evidence ID scannable in a prompt and in a
#: review UI. Stable by contract: changing one invalidates every stored
#: citation, so these are append-only.
KIND_TAGS: dict[EvidenceKind, str] = {
    EvidenceKind.RATIO_TREND: "RT",
    EvidenceKind.HEALTH_SIGNAL: "HS",
    EvidenceKind.DIMENSION_STATUS: "DS",
    EvidenceKind.RATIO_CHANGE: "RC",
    EvidenceKind.MODEL_SCORE: "MS",
    EvidenceKind.MODEL_DRIVER: "MD",
    EvidenceKind.MODEL_CAVEAT: "MC",
    EvidenceKind.NARRATIVE_SIGNAL: "NS",
    EvidenceKind.NARRATIVE_COVERAGE: "NC",
    EvidenceKind.DATA_QUALITY_CAVEAT: "DQ",
}


class Concern(str, Enum):
    """One layer's read on one dimension, in a vocabulary all layers share.

    The contradiction and corroboration rules need to compare a
    `DimensionStatus`, a signed SHAP contribution and a regex hit, which have
    nothing in common until they are projected onto the same three-valued axis.
    This enum is that projection and nothing more -- it is **not** a severity
    scale, has no ordering, and is never aggregated. `reads.py` documents how
    each layer maps onto it, and every mapping is deliberately coarse, because
    a finer one would be inventing precision the sources do not have.
    """

    #: This layer sees something on this dimension that deserves attention.
    ELEVATED = "elevated"
    #: This layer looked and found nothing notable.
    QUIET = "quiet"
    #: This layer could not form a read -- missing data, no coverage, or the
    #: dimension is outside what it measures. Never collapsed into `QUIET`,
    #: which is the mistake that makes a combination layer lie.
    UNKNOWN = "unknown"


class ContradictionCode(str, Enum):
    """The explicit contradiction rules (FR-15).

    Each is a named, testable condition over two cited sides, not a similarity
    threshold. A rule earns its place by describing a disagreement that an
    analyst would want to resolve *before* trusting either side.
    """

    #: The model ranks the company high while the deterministic layer sees
    #: nothing deteriorating. The model is reacting to something the ratios do
    #: not show -- which, given Phase 9's missingness finding, is as likely to
    #: be a pipeline artefact as a discovery.
    MODEL_ELEVATED_HEALTH_QUIET = "model_elevated_health_quiet"
    #: The filer states a high-specificity distress condition about itself and
    #: the model ranks it unremarkable.
    NARRATIVE_SEVERE_MODEL_QUIET = "narrative_severe_model_quiet"
    #: The filer states a high-specificity distress condition and no health
    #: dimension is deteriorating.
    NARRATIVE_SEVERE_HEALTH_QUIET = "narrative_severe_health_quiet"
    #: The same filing both asserts and denies the same condition -- two
    #: verbatim quotes from one document that cannot both be read plainly.
    NARRATIVE_SELF_CONTRADICTION = "narrative_self_contradiction"
    #: On one dimension, the model's attribution raises risk while the health
    #: layer reads that dimension as improving (or the mirror image).
    DIMENSION_DISAGREEMENT = "dimension_disagreement"
    #: The model ranks the company high and most of that score is attributed to
    #: missingness indicators: the ranking is driven by what the filing did not
    #: contain, so it is not evidence about the company's finances.
    SCORE_NOT_EVIDENCE_BACKED = "score_not_evidence_backed"
    #: The narrative layer reports no signals for a section it never located.
    #: "Nothing found" versus "did not look" -- the fail-safe NFR.
    ABSENCE_NOT_OBSERVED = "absence_not_observed"


class CorroborationCode(str, Enum):
    """Independent agreement across layers.

    Worth naming separately from contradiction because it is the only place
    this project can honestly raise its confidence: the three layers share no
    inputs beyond the filing itself, so agreement between them is not the same
    evidence counted twice.
    """

    #: All three independent layers point the same way on this company.
    ALL_LAYERS_ELEVATED = "all_layers_elevated"
    #: The deterministic trend layer and the filer's own words agree on one
    #: dimension.
    HEALTH_AND_NARRATIVE = "health_and_narrative"
    #: The model's leading attributed dimension is one the health layer
    #: independently reads as deteriorating.
    MODEL_AND_HEALTH = "model_and_health"
    #: The model ranks the company high and the filer states a
    #: high-specificity distress condition.
    MODEL_AND_NARRATIVE = "model_and_narrative"


class EvidenceItem(BaseModel):
    """One citable, checkable fact produced by one layer.

    Everything a Phase 12 draft is allowed to assert has to trace to one of
    these. The fields split three ways: identity (`evidence_id`,
    `identity_key`), what a reader sees (`summary`, `quote`), and what code
    checks (`numbers`, `detail`, `filed`).
    """

    model_config = ConfigDict(frozen=True)

    #: `EV-<tag>-<8 hex>`, deterministic in the item's content. Stable across
    #: runs and machines; changes when any cited value changes.
    evidence_id: str
    #: The same item across periods: layer, kind and subject, with no values
    #: and no period. What FR-11's change report diffs on.
    identity_key: str
    layer: LayerId
    kind: EvidenceKind
    #: liquidity / leverage / profitability / coverage / cash_flow, or `None`
    #: for cross-cutting items.
    dimension: str | None = None
    #: This item's read on its dimension, where it has one.
    concern: Concern = Concern.UNKNOWN
    #: A deterministic factual sentence built from the fields below. Never an
    #: interpretation beyond what the source object already states.
    summary: str
    #: Every figure that appears in `summary`, in order. Phase 12's validator
    #: checks a drafted number against this rather than against prose.
    numbers: tuple[float, ...] = ()
    #: The fiscal period this item describes, where it describes one.
    period_label: str | None = None
    #: Filing identity. `filed` is load-bearing: the as-of gate checks it.
    accession: str | None = None
    form: str | None = None
    filed: date | None = None
    #: Verbatim source text, for narrative items only. Never reflowed.
    quote: str | None = None
    #: The machine-readable payload a rule or a UI branches on. Values are
    #: restricted to JSON scalars so an assessment round-trips through Phase
    #: 13's persistence unchanged.
    detail: dict[str, str | float | int | bool | None] = Field(default_factory=dict)

    @property
    def is_verbatim(self) -> bool:
        """True when this item carries source text a reader can check character
        for character, rather than a computed restatement."""
        return self.quote is not None


class ContradictionFinding(BaseModel):
    """Two cited sides that cannot both be taken at face value (FR-15).

    `left` and `right` are evidence IDs, never copies -- a finding that
    restated its own evidence could drift from it. The rule states *what*
    disagrees; it deliberately does not say which side is right, because in
    every case here that is a judgement requiring information this layer does
    not have.
    """

    model_config = ConfigDict(frozen=True)

    code: ContradictionCode
    #: The dimension the disagreement is about, when it is about one.
    dimension: str | None
    left_layer: LayerId
    right_layer: LayerId
    left: tuple[str, ...]
    right: tuple[str, ...]
    #: A factual sentence naming both sides. No adjudication.
    explanation: str
    #: What a reader should check to resolve it -- the one place this schema
    #: gives direction, and it is a next action, never a conclusion.
    resolution_hint: str

    @property
    def cited(self) -> tuple[str, ...]:
        return self.left + self.right


class CorroborationFinding(BaseModel):
    """Independent layers agreeing, with every side cited."""

    model_config = ConfigDict(frozen=True)

    code: CorroborationCode
    dimension: str | None
    #: The layers that independently agree. A count, not a score: two layers is
    #: a different claim from three, and nothing here turns that into a number
    #: on a scale.
    layers: tuple[LayerId, ...]
    supporting: tuple[str, ...]
    explanation: str

    @property
    def cited(self) -> tuple[str, ...]:
        return self.supporting


class LayerAbsence(BaseModel):
    """Why a layer contributed nothing.

    An assessment missing its narrative layer because the filing's sections
    could not be located and one missing it because no signals fired are
    different products, and only this record keeps them apart. Phase 12 is
    required to render absences; Phase 13 stores them.
    """

    model_config = ConfigDict(frozen=True)

    layer: LayerId
    reason: str


class Assessment(BaseModel):
    """Everything the project knows about one company as of one date.

    The as-of date is not decoration. FR-05 requires an assessment to be
    reproducible from filings available on that date, which is also what makes
    a stored assessment auditable after the fact -- `assemble` enforces it over
    every evidence item's `filed`, and `asof.py` explains why enforcing it here
    rather than trusting the callers is the only version that holds.
    """

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    #: The replay date (FR-05): no evidence in this assessment was filed after
    #: it.
    as_of: date
    #: The latest fiscal period any layer reported on.
    period_label: str | None = None

    evidence: tuple[EvidenceItem, ...] = ()
    contradictions: tuple[ContradictionFinding, ...] = ()
    corroborations: tuple[CorroborationFinding, ...] = ()

    layers_present: tuple[LayerId, ...] = ()
    layers_absent: tuple[LayerAbsence, ...] = ()

    #: Component versions behind this assessment (FR-21): catalog version,
    #: model name, ratio catalog revision. Recorded so a stored assessment can
    #: be explained years later.
    pipeline_versions: dict[str, str] = Field(default_factory=dict)

    def by_id(self, evidence_id: str) -> EvidenceItem | None:
        for item in self.evidence:
            if item.evidence_id == evidence_id:
                return item
        return None

    def for_layer(self, layer: LayerId) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.evidence if item.layer is layer)

    def for_dimension(self, dimension: str) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.evidence if item.dimension == dimension)

    def of_kind(self, kind: EvidenceKind) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.evidence if item.kind is kind)

    def validate_citations(self, evidence_ids: object) -> tuple[str, ...]:
        """The IDs in `evidence_ids` that this assessment does not contain.

        The mechanism behind FR-17, kept here rather than in Phase 12 so that
        the check lives with the thing it checks. An empty result means every
        citation resolves; it does **not** mean the claim attached to them is
        supported, which is a separate check Phase 12 owns.
        """
        known = {item.evidence_id for item in self.evidence}
        return tuple(str(cited) for cited in evidence_ids if str(cited) not in known)

    def known_numbers(self) -> frozenset[float]:
        """Every figure any evidence item states.

        Phase 12's validator asks "does this drafted number appear anywhere in
        the evidence", and this is that set. Membership is necessary, not
        sufficient -- a number can be real and still be attached to the wrong
        claim, which is why citations are checked per claim as well.
        """
        return frozenset(number for item in self.evidence for number in item.numbers)

    @property
    def disagrees(self) -> bool:
        return bool(self.contradictions)
