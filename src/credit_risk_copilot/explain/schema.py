"""The explanation domain model: what the project says about a prediction.

This schema is deliberately **not** any attribution library's output type. A
SHAP `Explanation`, a coefficient vector and a permutation-importance array
are three different shapes, all of them library-specific, and none of them
carries the thing this product actually needs -- the chain from a model
contribution back to the filing it came from. `adapters.py` converts each of
them into the objects below; nothing outside `explain/` imports `shap` or
touches `sklearn` internals.

## The chain this schema exists to preserve

    model score
        -> FeatureContribution   (which input moved the score, and by how much)
        -> financial dimension   (liquidity / leverage / ... -- the analyst's view)
        -> ratio or canonical concept
        -> CanonicalFact         (value, status, origin)
        -> EvidenceLink          (accession, form, filing receipt date)

A contribution that cannot be traced to a filing is not suppressed -- it is
emitted with `evidence=()` and a caveat saying so, because "this number came
from somewhere we cannot show you" is itself information an analyst needs.

## Caveats are data, not prose

`ModelExplanation.caveats` is a tuple of structured `Caveat` objects rather
than a formatted string, for the same reason `RatioResult.warnings` became
structured in D-021: a downstream consumer (Phase 12's synthesis, Phase 13's
review UI) must be able to branch on "is this explanation trustworthy" without
substring-matching English. An explanation that would be misleading if quoted
without its caveats is required to carry them.

## No scores about scores

There is deliberately no "explanation quality score" or "trust score" here.
Caveats enumerate specific, checkable problems; collapsing them into a number
would hide exactly the distinctions the rest of this project keeps apart
(D-010, D-022).
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict


class CaveatCode(str, Enum):
    """Machine-readable reasons an explanation should not be read at face value."""

    #: The model's probabilities are not calibrated; the output is a ranking.
    NOT_CALIBRATED = "not_calibrated"
    #: The training base rate is a property of the sampling design, not of any
    #: real portfolio, so the score's *level* is not a portfolio probability
    #: even when its calibration slope looks acceptable ([D-033], [D-034]).
    BASE_RATE_NOT_PORTFOLIO = "base_rate_not_portfolio"
    #: A top contributor is a missingness indicator, i.e. the model is reacting
    #: to the *absence* of a figure rather than to its value.
    MISSINGNESS_DRIVEN = "missingness_driven"
    #: The training sample's comparison cohort is survivorship-selected, so
    #: part of the score may reflect sample construction (Phase 8 §7.6).
    COHORT_CONFOUNDED = "cohort_confounded"
    #: A contributing feature could not be traced to any filing.
    PROVENANCE_INCOMPLETE = "provenance_incomplete"
    #: A contributing input was Phase 5 `DERIVED` rather than directly tagged.
    DERIVED_INPUT = "derived_input"
    #: A contributing input carries Phase 5 `Confidence.LOW`.
    LOW_CONFIDENCE_INPUT = "low_confidence_input"
    #: The observation has little history behind it, so trend contributions
    #: rest on few periods.
    LIMITED_HISTORY = "limited_history"
    #: A contribution's size is not stable across the evaluation folds.
    UNSTABLE_ATTRIBUTION = "unstable_attribution"


class Caveat(BaseModel):
    """One specific, checkable reason for caution."""

    model_config = ConfigDict(frozen=True)

    code: CaveatCode
    message: str
    #: The feature or concept the caveat is about, when it is about one.
    subject: str | None = None


class EvidenceLink(BaseModel):
    """One canonical fact behind a contribution, and the filing it came from.

    This is the bottom of the chain: `accession` and `filed` are what let an
    analyst open the actual document, and `filed` is what lets them confirm the
    figure was available at the prediction date.
    """

    model_config = ConfigDict(frozen=True)

    concept: str
    period_label: str
    value: float | None
    #: Phase 5 `FactStatus` / `Origin` / `Confidence`, as their string values.
    status: str
    origin: str
    confidence: str
    #: The XBRL tag the value came from, when it was directly reported.
    xbrl_concept: str | None = None
    accession: str | None = None
    form: str | None = None
    filed: str | None = None


class FeatureContribution(BaseModel):
    """One model input's effect on one prediction.

    `contribution` is in the model's own additive units -- log-odds for the
    logistic family, the same units as the score's link function for any
    additive attribution method. It is **not** a probability and not a
    percentage of risk.
    """

    model_config = ConfigDict(frozen=True)

    feature: str
    #: Phase 8 feature family: scale / levels / ratios / trends / signals / quality.
    family: str
    #: The analyst-facing financial dimension, where the feature has one:
    #: liquidity / leverage / profitability / coverage / cash_flow. `None` for
    #: size, data-quality and cross-cutting features.
    dimension: str | None
    #: The feature's value for this observation; `None` when it was missing.
    value: float | None
    #: True when this is a `<name>__missing` indicator rather than a financial
    #: quantity -- the distinction §12 of the Phase 9 brief insists on.
    is_missingness_indicator: bool
    contribution: float
    #: What the contribution's sign means, stated rather than left to the
    #: reader: a positive log-odds contribution raises the modelled likelihood.
    raises_risk: bool
    #: `concept` | `ratio` | `trend` | `signal` | `dimension` | `derived` | `quality`
    source_kind: str
    source_id: str | None = None
    evidence: tuple[EvidenceLink, ...] = ()


class DimensionAttribution(BaseModel):
    """Contributions rolled up to a financial dimension.

    Grouping is not cosmetic. Financial features are heavily correlated --
    `debt_to_assets`, `debt_to_equity` and `liabilities_to_assets` move
    together -- and every additive attribution method splits a shared effect
    among correlated inputs in a way that is arbitrary at the individual-
    feature level and stable at the group level. A ranked list of 57 features
    invites over-reading; a ranked list of six dimensions does not.
    """

    model_config = ConfigDict(frozen=True)

    #: A financial dimension, a feature family, or `"missingness"`.
    group: str
    contribution: float
    #: This group's share of the total absolute contribution, so a reader can
    #: see concentration without comparing raw log-odds.
    share_of_absolute: float
    feature_count: int
    top_features: tuple[FeatureContribution, ...] = ()


class ModelExplanation(BaseModel):
    """Everything the project can say about one prediction.

    `score` is whatever the model emits. Whether it may be read as a
    probability is decided by the caveats, not by its range: a number in
    [0, 1] that fails calibration is a ranking key that happens to look like a
    probability, which is the most dangerous shape a risk output can take.
    """

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    prediction_date: date
    fiscal_period_label: str
    source_accession: str

    model_name: str
    model_family: str
    #: The attribution method that produced `contributions`.
    attribution_method: str

    score: float
    #: The model's baseline output before any contribution -- the logistic
    #: intercept, or an attribution method's expected value. Contributions are
    #: interpretable only relative to it.
    baseline: float
    #: Position within the scored population, when the caller supplies one.
    #: Expressed as a percentile because the product's own framing is "unusually
    #: high in the monitored ranking", not "n% likely to fail".
    score_percentile: float | None = None

    contributions: tuple[FeatureContribution, ...]
    by_dimension: tuple[DimensionAttribution, ...]
    caveats: tuple[Caveat, ...]

    def top_contributors(
        self, n: int = 5, *, raising: bool = True
    ) -> tuple[FeatureContribution, ...]:
        """The `n` largest contributions in one direction."""
        selected = [c for c in self.contributions if c.raises_risk == raising]
        return tuple(sorted(selected, key=lambda c: -abs(c.contribution))[:n])

    @property
    def missingness_share(self) -> float:
        """Share of total absolute contribution coming from missingness indicators.

        The headline number for §13 of the phase brief: how much of this
        prediction is about *what the filing did not contain* rather than what
        it said.
        """
        total = sum(abs(c.contribution) for c in self.contributions)
        if total == 0:
            return 0.0
        missing = sum(abs(c.contribution) for c in self.contributions if c.is_missingness_indicator)
        return missing / total

    def has_caveat(self, code: CaveatCode) -> bool:
        return any(caveat.code is code for caveat in self.caveats)
