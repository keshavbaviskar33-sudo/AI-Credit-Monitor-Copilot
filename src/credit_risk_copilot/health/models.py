"""Financial-health result schema: the Phase 6 -> Phase 7 boundary.

Phase 6 answers "what does the ratio equal, for one period" -- a
`RatioResult`. Phase 7 answers "how is it changing, and what does that change
mean for financial health" -- deterministic trend statistics plus
early-warning signals, never a credit decision or a composite score (§1,
§2, §25 of the phase brief).

Design principles carried over from `ratios/models.py`, applied one layer up:

- **A trend is not a label.** `direction` (raw: did the number go up/down)
  and `economic_direction` (interpreted: does that mean stronger or weaker)
  are kept as two separate fields, never collapsed into one "risk" value
  (§8) -- `direction` alone can never tell you whether increasing is good.
- **Reference, don't copy.** `RatioTrend` holds the actual `RatioResult`
  tuple it was computed from, exactly as `RatioResult.inputs` holds the
  actual `CanonicalFact`s it consumed -- full provenance for free, one
  source of truth for the numbers.
- **Missing is not stable, and a sign-crossing ratio is not interpretable.**
  `TrendDirection` keeps `INSUFFICIENT_DATA`, `DISCONTINUOUS_HISTORY` and
  `NOT_MEANINGFUL` apart from `STABLE` -- collapsing any of them into
  `STABLE` would be exactly the failure §17 and §21 warn about.
- **No composite score.** There is no single "financial health" number
  anywhere in this module (§25, §33) -- only per-dimension, per-ratio,
  evidence-carrying structure.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.ratios.models import RatioChange, RatioResult


class TrendDirection(str, Enum):
    """What the raw number did across the analyzed window -- arithmetic
    only, no judgement about whether that is good or bad for the company
    (§8: direction is not meaning)."""

    #: The qualifying window's magnitude of change exceeded the stable
    #: threshold, moving up.
    INCREASING = "increasing"
    #: Same, moving down.
    DECREASING = "decreasing"
    #: Calculated throughout the window; the net move stayed within the
    #: stable-magnitude noise floor.
    STABLE = "stable"
    #: The ratio's conventional interpretation does not apply -- currently:
    #: a denominator that is negative on a ratio where that is legitimate
    #: (`NEGATIVE_EQUITY`, §21) appears anywhere in the window. Mirrors
    #: `docs/product_requirements.md` §6.1's own `not_meaningful` ratio
    #: status.
    NOT_MEANINGFUL = "not_meaningful"
    #: Fewer than `MIN_CONSECUTIVE_PERIODS_FOR_TREND` calculated periods are
    #: available, gap-free (`docs/scope.md` §2).
    INSUFFICIENT_DATA = "insufficient_data"
    #: At least one period between the earliest and latest calculated period
    #: in the window is not itself calculated -- a real gap, not a missing
    #: tail. Never bridged silently (§17): a trend is not computed across it.
    DISCONTINUOUS_HISTORY = "discontinuous_history"


class HistoryDepth(str, Enum):
    """How much history actually backs this trend -- named `history_depth`,
    not `confidence`, because it is a fact about sample size, not a
    statistical confidence claim this engine is not positioned to make
    (§29)."""

    #: Fewer than `MIN_CONSECUTIVE_PERIODS_FOR_TREND` gap-free calculated
    #: periods.
    LIMITED = "limited"
    #: At least `MIN_CONSECUTIVE_PERIODS_FOR_TREND`, gap-free.
    ADEQUATE = "adequate"


class RatioDirection(str, Enum):
    """Whether a *higher* or *lower* value is the economically stronger
    state for this ratio -- the "economic_direction" abstraction the phase
    brief asks for instead of a `risk_direction` field (§8), so this module
    never has to say the word "risk" to know which way is which."""

    HIGHER_IS_STRONGER = "higher_is_stronger"
    LOWER_IS_STRONGER = "lower_is_stronger"


class EconomicDirection(str, Enum):
    """`TrendDirection` interpreted through a ratio's `RatioDirection` --
    what the move means, not just what it was (§8). The only place "good"
    or "bad" is ever implied in this package, and even here only as
    improving/deteriorating relative to the company's own prior periods,
    never as a level judgement or a credit conclusion."""

    IMPROVING = "improving"
    STABLE = "stable"
    DETERIORATING = "deteriorating"
    NOT_MEANINGFUL = "not_meaningful"
    INSUFFICIENT_DATA = "insufficient_data"
    DISCONTINUOUS_HISTORY = "discontinuous_history"


class DimensionStatus(str, Enum):
    """One health dimension's (liquidity/leverage/profitability/coverage/
    cash_flow) aggregate state, from its own ratios' `EconomicDirection`s
    (§5, §26). Deliberately dimensional, never rolled into one score."""

    IMPROVING = "improving"
    STABLE = "stable"
    #: At least one ratio in the dimension is DETERIORATING and at least one
    #: is IMPROVING -- both are surfaced, never silently netted against each
    #: other into a false single direction.
    MIXED = "mixed"
    DETERIORATING = "deteriorating"
    #: No ratio in the dimension reached a conclusive (non-insufficient,
    #: non-discontinuous, non-not-meaningful) direction.
    INSUFFICIENT_DATA = "insufficient_data"


class DataQualityLevel(str, Enum):
    """The caveat level behind a trend or dimension's inputs (§18, §19).
    Ordered worst-to-best when rolling several ratios' levels into one:
    `LOW_CONFIDENCE` > `MANUALLY_ADJUSTED` > `DERIVED_INPUTS` > `GOOD` --
    mirrors `ratios/models.py`'s own documented status-priority convention
    (CONFLICTING beats MISSING beats bad denominator)."""

    GOOD = "good"
    #: At least one input was Phase 5 `DERIVED` rather than directly tagged.
    #: Routine, not a trust concern -- `docs/ratios.md` §3 notes `total_debt`
    #: and `ebit` are `DERIVED` for nearly every filer, so treating this as
    #: low-quality would mislabel most of the real corpus.
    DERIVED_INPUTS = "derived_inputs"
    #: At least one input was analyst-corrected -- a deliberate, presumably
    #: improving adjustment, not evidence of untrustworthy data. Kept apart
    #: from `LOW_CONFIDENCE` so a manual correction is never mistaken for a
    #: weaker one (§19).
    MANUALLY_ADJUSTED = "manually_adjusted"
    #: At least one input carries Phase 5 `Confidence.LOW`.
    LOW_CONFIDENCE = "low_confidence"


class SignalCode(str, Enum):
    """Machine-readable early-warning signal identifiers (§10). Kept small
    and high-value on purpose -- one code per dimension-direction pairing
    that the phase brief names explicitly, plus two cross-cutting codes.
    Persistence (how many consecutive periods) is a *field* on the signal,
    not a separate code per persistence level -- a second taxonomy axis
    would be exactly the "giant taxonomy" §10 warns against."""

    LIQUIDITY_DETERIORATION = "liquidity_deterioration"
    LEVERAGE_DETERIORATION = "leverage_deterioration"
    #: Gross/operating/net margin ratios trending down.
    MARGIN_COMPRESSION = "margin_compression"
    #: ROA/ROE trending down -- kept apart from `MARGIN_COMPRESSION` because
    #: a return ratio can deteriorate from asset/equity-base changes with
    #: margins flat, a distinct fact worth naming separately (§10 lists both
    #: as separate codes).
    PROFITABILITY_DETERIORATION = "profitability_deterioration"
    INTEREST_COVERAGE_DECLINE = "interest_coverage_decline"
    CASH_FLOW_WEAKENING = "cash_flow_weakening"
    #: A denominator-negative-equity ratio is present anywhere in the
    #: window (§21) -- the conventional direction interpretation for that
    #: ratio does not apply; this signal carries the raw fact instead.
    NEGATIVE_EQUITY = "negative_equity"
    #: The latest single-period move is a robust-z-score outlier against the
    #: ratio's own prior history (§13, §22) -- an observation, not a claim
    #: about direction or cause.
    UNUSUAL_MOVEMENT = "unusual_movement"
    #: At least `MULTI_DIMENSION_MIN_DIMENSIONS` of the five monitored
    #: dimensions are independently DETERIORATING for the same report
    #: (§15).
    MULTI_DIMENSION_DETERIORATION = "multi_dimension_deterioration"


class RatioTrend(BaseModel):
    """One ratio's deterministic historical-trend analysis (§6, §7, §16).

    `results` is the exact `RatioResult` tuple this trend was computed from,
    chronologically sorted by this module (never trusted from the caller's
    order -- see `trend.py`'s docstring for why). Every other field is a
    number or label derived from that tuple; nothing here re-states a value
    already on a `RatioResult`.
    """

    model_config = ConfigDict(frozen=True)

    ratio_id: str
    #: Chronologically sorted, one per period this ratio was evaluated for
    #: (calculated or not) -- the complete evidence trail.
    results: tuple[RatioResult, ...]
    direction: TrendDirection
    economic_direction: EconomicDirection
    #: Count of `CALCULATED` periods within `results` (not necessarily
    #: gap-free -- see `has_gap`).
    periods_available: int
    history_depth: HistoryDepth
    #: True when a non-`CALCULATED` period sits between the earliest and
    #: latest `CALCULATED` period in `results`.
    has_gap: bool
    gap_periods: tuple[str, ...]
    #: Populated only when `direction` is `INCREASING`/`DECREASING`/`STABLE`
    #: -- first-to-last value across the qualifying (gap-free, >= minimum
    #: periods) window (§39: matches the phase brief's own "change over two
    #: periods" framing).
    absolute_change: float | None
    percent_change: float | None
    #: Consecutive same-direction period-over-period moves ending at the
    #: latest period, within the qualifying window (§14). 0 when `direction`
    #: is not `INCREASING`/`DECREASING`.
    persistence: int
    #: Median of every `CALCULATED` value in `results` *excluding* the
    #: latest one (§12) -- `None` below `MIN_PRIOR_VALUES_FOR_BASELINE`.
    baseline_median: float | None
    #: Latest `CALCULATED` value minus `baseline_median`; `None` whenever
    #: either is `None`.
    deviation_from_baseline: float | None
    #: Robust (median/MAD) z-score flag on the latest single-period move
    #: (§13, §22) -- `False` whenever there are too few prior deltas to
    #: judge (`UNUSUAL_MOVEMENT_MIN_PRIOR_DELTAS`).
    unusual_movement: bool
    #: True when any `CALCULATED` result in `results` carries a
    #: `WarningCode.NEGATIVE_EQUITY` warning (§21).
    negative_equity: bool
    data_quality: DataQualityLevel
    #: Populated whenever `direction` is not `INCREASING`/`DECREASING`/
    #: `STABLE` -- explains which condition applied and why, the same
    #: convention as `RatioResult.reason`.
    reason: str | None = None

    def explain(self) -> str:
        """A deterministic, purely factual explanation -- the trend
        equivalent of `RatioResult.explain()` (§39). Never a financial
        judgement beyond the disclosed direction/magnitude/persistence
        facts already on this object."""
        header = f"{self.ratio_id}: direction={self.direction.value}"
        lines = [header]
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        series = ", ".join(
            f"{r.period_label}={r.value if r.value is not None else 'n/a'}" for r in self.results
        )
        lines.append(f"History: {series}")
        if self.absolute_change is not None:
            # `percent_change` divides by the *signed* earliest value (the
            # same convention `RatioChange.percent_change` already uses), so
            # its sign can contradict `absolute_change`'s when that baseline
            # is negative (e.g. a net margin moving from -481% to -50% is a
            # real improvement, absolute_change positive, but the percent
            # figure still carries a negative sign). Printing both together
            # in that case reads as self-contradictory, so the percentage is
            # shown only when the two signs agree -- the field itself is
            # untouched, this only affects the human-readable line.
            signs_agree = self.percent_change is not None and (self.percent_change >= 0) == (
                self.absolute_change >= 0
            )
            lines.append(
                f"Change: {self.absolute_change:+.4g} ({self.percent_change:+.1%})"
                if signs_agree
                else f"Change: {self.absolute_change:+.4g}"
            )
        if self.persistence:
            lines.append(f"Persistence: {self.persistence} consecutive periods")
        return "\n".join(lines)


class Signal(BaseModel):
    """One structured early-warning signal (§10, §16, §39, §40) -- never a
    final risk decision. Every field traces to specific ratios, periods and
    values a human (or Phase 12's LLM) can verify directly."""

    model_config = ConfigDict(frozen=True)

    code: SignalCode
    #: The health dimension this signal belongs to, or `"cross_dimension"`
    #: for `MULTI_DIMENSION_DETERIORATION`.
    category: str
    #: `None` only for `MULTI_DIMENSION_DETERIORATION`, which is not about
    #: one ratio.
    ratio_id: str | None
    #: The `RatioTrend` this signal was raised from -- `None` only for
    #: `MULTI_DIMENSION_DETERIORATION`.
    trend: RatioTrend | None
    #: Populated only for `MULTI_DIMENSION_DETERIORATION` -- the dimensions
    #: that were independently `DETERIORATING`.
    affected_dimensions: tuple[str, ...] = ()
    #: A deterministic, factual sentence -- formula/values/periods already
    #: on `trend`, restated as prose for a human reader (never an
    #: interpretation beyond what the fields already state).
    evidence: str


class DimensionHealth(BaseModel):
    """One health dimension's aggregate status plus every ratio trend and
    signal that fed it (§5, §9, §26) -- kept dimensional, never merged into
    a single score."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    status: DimensionStatus
    ratio_trends: tuple[RatioTrend, ...]
    signals: tuple[Signal, ...]


class DataQuality(BaseModel):
    """Report-level data-quality rollup (§18, §19, §29) -- lists which
    ratios carry which caveat rather than collapsing to one score, so a
    caller can see exactly what is weaker, not just that something is."""

    model_config = ConfigDict(frozen=True)

    level: DataQualityLevel
    ratios_with_low_confidence_input: tuple[str, ...]
    ratios_with_manual_correction: tuple[str, ...]
    ratios_with_derived_input: tuple[str, ...]
    ratios_with_limited_history: tuple[str, ...]


class FinancialHealthReport(BaseModel):
    """The Phase 7 top-level output (§33, §49) -- interpretable dimensions,
    evidence-carrying signals, and a change summary, built entirely from
    Phase 6 `RatioResult`/`RatioChange` objects with no LLM and no
    prediction (§31, §32). Deliberately has no overall score field."""

    model_config = ConfigDict(frozen=True)

    company: str
    #: The most recent period considered across every ratio (inferred, not
    #: supplied) -- the "as of" period this report describes.
    period_label: str
    #: The periods that actually backed this report, after `analysis_window`
    #: was applied -- the *effective* window, which may be shorter than
    #: `analysis_window` when less history was supplied.
    periods_considered: tuple[str, ...]
    #: The requested cap on how many recent periods were analyzed (D-024);
    #: `None` means every supplied period was used. Recorded on the report so
    #: a downstream consumer never has to guess which span a direction,
    #: persistence count or signal refers to.
    analysis_window: int | None = None
    dimensions: dict[str, DimensionHealth]
    #: Every signal across every dimension plus any cross-dimension signal,
    #: flattened for a caller that wants "all signals" without walking
    #: `dimensions`.
    signals: tuple[Signal, ...]
    #: The most recent period-over-period `RatioChange` for every ratio that
    #: has one (§23, §24) -- reuses Phase 6's own arithmetic verbatim rather
    #: than recomputing it.
    changes_since_previous_period: tuple[RatioChange, ...]
    data_quality: DataQuality

    def trend(self, ratio_id: str) -> RatioTrend | None:
        """This report's `RatioTrend` for one ratio, or `None` if the ratio
        is not in the catalog this report was built with.

        A flat accessor so a consumer does not have to know which dimension
        a ratio belongs to in order to read its trend -- `dimensions` stays
        the structural view, this is the lookup view.
        """
        for dimension in self.dimensions.values():
            for ratio_trend in dimension.ratio_trends:
                if ratio_trend.ratio_id == ratio_id:
                    return ratio_trend
        return None
