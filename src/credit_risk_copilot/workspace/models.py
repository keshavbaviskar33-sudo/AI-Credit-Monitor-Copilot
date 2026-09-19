"""View models for the analyst workspace: what the screen needs, in plain Python.

No Streamlit import anywhere in this package. The UI renders these objects; it
does not compute them. That split is what lets the hard part -- deciding what a
layer's read *is*, and what belongs on the desk -- be unit-tested without a
browser, and it keeps the presentation layer thin enough to replace.

## The design decision this schema encodes

There is no risk score here, and there is no confidence percentage, because
the system behind it produces neither. [D-010] refused a probability of
default, [D-022] a composite health score, [D-033] anything but a ranking
position, [D-036] a combined assessment number, and [D-049] a severity
vocabulary. A UI that displayed `72 / 100 · 84% confident` would be that
number arriving at last, disguised as a widget -- and it would be the one
element on the screen nobody could trace to a filing.

What replaces it is `LayerRead`: **three independent methods, side by side,
each with its own verdict and its own evidence.** An analyst learns more from
"the ratios are calm, the model ranks this company in the top 3%, and the
filer states going-concern doubt" than from any average of those three, and
the disagreement between them is a finding the average would destroy.

Research supports the same shape. Citation-and-provenance interfaces turn
output from *trust me* into *check me*, and showing the source passage beats
showing a trust meter -- so every read carries `evidence_ids`, and every
number on the screen resolves to an `EV-` item with a filing behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from credit_risk_copilot.assessment.models import (
    Concern,
    ContradictionFinding,
    CorroborationFinding,
    EvidenceItem,
    LayerId,
)
from credit_risk_copilot.review.models import AssessmentState, CreditWatchStatus

#: How each layer is introduced to the analyst. The wording is deliberate:
#: none of the three claims to measure "risk", because none of them does.
LAYER_TITLES: dict[LayerId, str] = {
    LayerId.FINANCIAL_HEALTH: "Financial trends",
    LayerId.PREDICTIVE_MODEL: "Model ranking",
    LayerId.NARRATIVE: "Filing language",
    LayerId.DATA_QUALITY: "Data quality",
}

LAYER_METHODS: dict[LayerId, str] = {
    LayerId.FINANCIAL_HEALTH: "Deterministic ratio trends over the analysis window",
    LayerId.PREDICTIVE_MODEL: "Gradient-boosted hazard model, ranked within its own year",
    LayerId.NARRATIVE: "Disclosure statements the filer makes about itself",
    LayerId.DATA_QUALITY: "Provenance and completeness of the underlying facts",
}

#: Concern rendered for a human. Word first, colour second -- the colour is a
#: reinforcement, never the only channel (accessibility, and the reason the
#: palette avoids red/green).
CONCERN_LABELS: dict[Concern, str] = {
    Concern.ELEVATED: "Elevated",
    Concern.QUIET: "Nothing flagged",
    Concern.UNKNOWN: "No read",
}

CONCERN_ICONS: dict[Concern, str] = {
    Concern.ELEVATED: ":material/error:",
    Concern.QUIET: ":material/check_circle:",
    Concern.UNKNOWN: ":material/help:",
}

CONCERN_COLORS: dict[Concern, str] = {
    Concern.ELEVATED: "orange",
    Concern.QUIET: "green",
    Concern.UNKNOWN: "gray",
}


@dataclass(frozen=True)
class LayerRead:
    """One analytical layer's verdict, in a vocabulary shared with the others.

    `headline` is a short clause an analyst can read at a glance; `detail`
    qualifies it. Both are built from the evidence rather than written here,
    and `evidence_ids` is what the UI turns into links -- a read with no
    citations would be exactly the unsourced claim this product exists to
    avoid.
    """

    layer: LayerId
    concern: Concern
    headline: str
    detail: str
    evidence_ids: tuple[str, ...] = ()
    #: False when the layer produced nothing. Kept apart from a `QUIET` read,
    #: because "we looked and found nothing" and "we did not look" are
    #: different answers and conflating them is the failure the whole
    #: pipeline is shaped to prevent.
    available: bool = True
    unavailable_reason: str | None = None

    @property
    def title(self) -> str:
        return LAYER_TITLES[self.layer]

    @property
    def method(self) -> str:
        return LAYER_METHODS[self.layer]


@dataclass(frozen=True)
class MetricPoint:
    """One period's value for one series."""

    period: str
    value: float | None


@dataclass(frozen=True)
class RatioSeries:
    """One ratio's history, for the trend charts.

    Built from the Phase 8 point-in-time panel, so every point is a value that
    was computable from filings available at that period -- the series is not
    a restated back-fill.
    """

    ratio_id: str
    name: str
    category: str
    formula: str
    points: tuple[MetricPoint, ...]
    #: Phase 7's reading for the latest window, where the assessment has one.
    economic_direction: str | None = None
    higher_is_stronger: bool = True

    @property
    def latest(self) -> float | None:
        for point in reversed(self.points):
            if point.value is not None:
                return point.value
        return None

    @property
    def observed(self) -> tuple[MetricPoint, ...]:
        return tuple(p for p in self.points if p.value is not None)

    @property
    def change(self) -> float | None:
        """First-to-last change across observed points."""
        observed = self.observed
        if len(observed) < 2:
            return None
        first = observed[0].value
        last = observed[-1].value
        return None if first is None or last is None else last - first


@dataclass(frozen=True)
class DriverBar:
    """One dimension's contribution to the model's ranking.

    `share` is the share of total absolute attribution, which is the number
    worth reading: the raw contribution is on the model's own additive scale
    and means nothing on its own. The UI shows both and labels the units.
    """

    group: str
    contribution: float
    share: float
    feature_count: int
    raises_risk: bool
    evidence_id: str
    #: True for `missingness` and `data_quality` -- attribution that is about
    #: the *filing's completeness* rather than about the company. Rendered
    #: distinctly, because a model reacting to an absent tag is not a finding
    #: about leverage.
    is_filing_artefact: bool = False


@dataclass(frozen=True)
class NarrativeItem:
    """One disclosure the filer makes, with the sentence it was found in."""

    code: str
    label: str
    assertion: str
    specificity: str
    section: str | None
    occurrences: int
    quote: str | None
    evidence_id: str
    accession: str | None

    @property
    def is_asserted(self) -> bool:
        return self.assertion == "asserted"


@dataclass(frozen=True)
class CoverageGap:
    """A filing section the extractor could not locate."""

    section: str
    evidence_id: str
    note: str


@dataclass(frozen=True)
class CompanyCard:
    """A company at a glance, for the desk, the watchlist and comparison."""

    cik: int
    company: str
    as_of: date
    period_label: str | None
    assessment_id: str
    state: AssessmentState
    watch_status: CreditWatchStatus | None
    reads: tuple[LayerRead, ...]
    n_contradictions: int
    n_corroborations: int
    n_evidence: int
    draft_id: str | None = None
    draft_accepted: bool | None = None
    #: Named reasons this company is on the desk. Never a score: the analyst
    #: is told *why* it surfaced, and identical reasons are not ranked against
    #: each other.
    attention: tuple[str, ...] = ()

    def read(self, layer: LayerId) -> LayerRead | None:
        return next((r for r in self.reads if r.layer is layer), None)

    @property
    def elevated_layers(self) -> tuple[LayerId, ...]:
        return tuple(r.layer for r in self.reads if r.concern is Concern.ELEVATED)


@dataclass(frozen=True)
class CompanyWorkspace:
    """Everything the company page renders.

    Assembled once per company per as-of date so the page does no derivation
    of its own; if a figure is not on this object, the page may not show it.
    """

    card: CompanyCard
    evidence: tuple[EvidenceItem, ...]
    contradictions: tuple[ContradictionFinding, ...]
    corroborations: tuple[CorroborationFinding, ...]
    drivers: tuple[DriverBar, ...]
    caveats: tuple[tuple[str, str], ...]
    narrative: tuple[NarrativeItem, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    ratios: tuple[RatioSeries, ...]
    scale: dict[str, MetricPoint] = field(default_factory=dict)
    scale_history: dict[str, tuple[MetricPoint, ...]] = field(default_factory=dict)
    pipeline_versions: dict[str, str] = field(default_factory=dict)
    #: Model ranking position, when the model ran. A percentile within its own
    #: scoring year -- never a probability, which is why the field is named
    #: after what it is.
    score_percentile: float | None = None
    model_name: str | None = None

    def by_id(self, evidence_id: str) -> EvidenceItem | None:
        return next((e for e in self.evidence if e.evidence_id == evidence_id), None)

    def ratios_in(self, category: str) -> tuple[RatioSeries, ...]:
        return tuple(r for r in self.ratios if r.category == category)


#: The reasons a company reaches the desk. Each is a fact about the
#: assessment, phrased as what the analyst would do about it.
ATTENTION_DISAGREEMENT = "Layers disagree"
ATTENTION_ALL_ELEVATED = "All three layers elevated"
ATTENTION_UNREVIEWED = "Not yet reviewed"
ATTENTION_DRAFT_REJECTED = "Draft failed grounding"
ATTENTION_COVERAGE = "Filing sections unread"
ATTENTION_SEVERE_DISCLOSURE = "Filer states a severe condition"

ATTENTION_ORDER: tuple[str, ...] = (
    ATTENTION_SEVERE_DISCLOSURE,
    ATTENTION_ALL_ELEVATED,
    ATTENTION_DISAGREEMENT,
    ATTENTION_DRAFT_REJECTED,
    ATTENTION_COVERAGE,
    ATTENTION_UNREVIEWED,
)

ATTENTION_EXPLANATIONS: dict[str, str] = {
    ATTENTION_SEVERE_DISCLOSURE: (
        "The filing states a high-specificity condition about the company itself -- "
        "going-concern doubt, default, restructuring or a delisting notice."
    ),
    ATTENTION_ALL_ELEVATED: (
        "The ratio trends, the model ranking and the filer's own words all point the "
        "same way. Independent methods agreeing is the strongest signal this system "
        "produces."
    ),
    ATTENTION_DISAGREEMENT: (
        "Two layers reached incompatible readings. The disagreement is the finding; "
        "resolving it needs a human."
    ),
    ATTENTION_DRAFT_REJECTED: (
        "The AI draft cited evidence that does not exist, stated a number that is not "
        "in the evidence, or altered a quotation. It is shown with the failure, not "
        "hidden."
    ),
    ATTENTION_COVERAGE: (
        "At least one narrative section could not be located, so 'no disclosure "
        "signals' partly means 'not read'."
    ),
    ATTENTION_UNREVIEWED: "No analyst has recorded a decision on this assessment.",
}
