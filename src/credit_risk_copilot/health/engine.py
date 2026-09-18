"""`analyze_financial_health`: the Phase 7 entry point (§49).

    health = analyze_financial_health(company, ratio_history)

`ratio_history` is exactly what Phase 6's `ratios_for_filing`,
`ratios_from_facts` or `calculate_ratio_history` already return --
`ratio_id -> RatioResult` per period -- so a caller needs nothing beyond
what it already has after Phase 6 runs. No LLM, no ML, no credit decision;
every field on the returned `FinancialHealthReport` traces back to a
`RatioResult` or `RatioChange` Phase 6 computed (§1, §2, §31, §32, §40).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from credit_risk_copilot.health.dimensions import dimension_status, group_by_dimension
from credit_risk_copilot.health.direction import RATIO_DIRECTIONS
from credit_risk_copilot.health.models import (
    DataQuality,
    DataQualityLevel,
    DimensionHealth,
    FinancialHealthReport,
    HistoryDepth,
    RatioTrend,
)
from credit_risk_copilot.health.signals import generate_signals
from credit_risk_copilot.health.thresholds import DEFAULT_ANALYSIS_WINDOW
from credit_risk_copilot.health.trend import compute_ratio_trend, fiscal_sort_key
from credit_risk_copilot.ratios.engine import ratio_history_changes
from credit_risk_copilot.ratios.models import RatioChange, RatioResult
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS, RatioDefinition


def _changes_since_previous_period(ratio_trends: Sequence[RatioTrend]) -> tuple[RatioChange, ...]:
    """The most recent period-over-period `RatioChange` for every ratio that
    has one (§23, §24) -- `trend.results` is already chronologically sorted,
    so this is `ratio_history_changes(...)[-1]` per ratio, nothing recomputed."""
    changes: list[RatioChange] = []
    for trend in ratio_trends:
        ratio_changes = ratio_history_changes(trend.results)
        if ratio_changes:
            changes.append(ratio_changes[-1])
    return tuple(changes)


def _data_quality_rollup(ratio_trends: Sequence[RatioTrend]) -> DataQuality:
    low_confidence = tuple(
        t.ratio_id for t in ratio_trends if t.data_quality is DataQualityLevel.LOW_CONFIDENCE
    )
    manually_adjusted = tuple(
        t.ratio_id for t in ratio_trends if t.data_quality is DataQualityLevel.MANUALLY_ADJUSTED
    )
    derived = tuple(
        t.ratio_id for t in ratio_trends if t.data_quality is DataQualityLevel.DERIVED_INPUTS
    )
    limited_history = tuple(
        t.ratio_id for t in ratio_trends if t.history_depth is HistoryDepth.LIMITED
    )
    if low_confidence:
        level = DataQualityLevel.LOW_CONFIDENCE
    elif manually_adjusted:
        level = DataQualityLevel.MANUALLY_ADJUSTED
    elif derived:
        level = DataQualityLevel.DERIVED_INPUTS
    else:
        level = DataQualityLevel.GOOD
    return DataQuality(
        level=level,
        ratios_with_low_confidence_input=low_confidence,
        ratios_with_manual_correction=manually_adjusted,
        ratios_with_derived_input=derived,
        ratios_with_limited_history=limited_history,
    )


def _windowed(
    ratio_history: Mapping[str, Sequence[RatioResult]], analysis_window: int | None
) -> tuple[Mapping[str, Sequence[RatioResult]], tuple[str, ...]]:
    """Restrict every ratio's series to the most recent `analysis_window`
    fiscal periods, and report the period labels kept (D-024).

    The window is taken over the *union* of period labels across every
    ratio, not per ratio, so all ratios in one report are compared over the
    same span -- otherwise a sparsely-covered ratio would silently reach
    further back than its neighbours and the dimension rollup would compare
    different spans against each other.

    Period labels are counted whether or not they calculated a value, so a
    gap inside the window stays a gap: taking "the last 5 *calculated*"
    periods would bridge a missing year silently, which is exactly what
    `DISCONTINUOUS_HISTORY` exists to prevent.
    """
    all_periods = sorted(
        {r.period_label for results in ratio_history.values() for r in results},
        key=fiscal_sort_key,
    )
    if analysis_window is None or len(all_periods) <= analysis_window:
        return ratio_history, tuple(all_periods)
    kept = tuple(all_periods[-analysis_window:])
    keep = set(kept)
    return (
        {
            ratio_id: [r for r in results if r.period_label in keep]
            for ratio_id, results in ratio_history.items()
        },
        kept,
    )


def analyze_financial_health(
    company: str,
    ratio_history: Mapping[str, Sequence[RatioResult]],
    *,
    definitions: Sequence[RatioDefinition] = RATIO_DEFINITIONS,
    analysis_window: int | None = DEFAULT_ANALYSIS_WINDOW,
) -> FinancialHealthReport:
    """Turn one company's ratio history into a `FinancialHealthReport`:
    per-dimension status, per-ratio trends, early-warning signals and a
    change summary (§33, §49). A ratio absent from `ratio_history` is
    treated the same as one present with an empty series -- `INSUFFICIENT_DATA`,
    never silently skipped, so every dimension the catalog defines is
    represented.

    `analysis_window` caps how many of the most recent fiscal periods are
    analyzed (D-024). It defaults to `DEFAULT_ANALYSIS_WINDOW`; pass `None`
    to analyze every period supplied. Supplying fewer periods than the
    window is not an error -- the usual `INSUFFICIENT_DATA`/`LIMITED`
    history handling applies unchanged, so a short history behaves exactly
    as it did before this parameter existed.
    """
    windowed, _ = _windowed(ratio_history, analysis_window)
    ratio_trends = tuple(
        compute_ratio_trend(
            definition.ratio_id,
            windowed.get(definition.ratio_id, ()),
            RATIO_DIRECTIONS[definition.ratio_id],
        )
        for definition in definitions
    )

    grouped = group_by_dimension(ratio_trends)
    dimension_statuses = {dim: dimension_status(trends) for dim, trends in grouped.items()}
    signals = generate_signals(ratio_trends, dimension_statuses)

    dimensions = {
        dim: DimensionHealth(
            dimension=dim,
            status=dimension_statuses[dim],
            ratio_trends=trends,
            signals=tuple(s for s in signals if s.category == dim),
        )
        for dim, trends in grouped.items()
    }

    periods_considered = tuple(
        sorted(
            {r.period_label for trend in ratio_trends for r in trend.results},
            key=fiscal_sort_key,
        )
    )
    period_label = max(periods_considered, key=fiscal_sort_key, default="")

    return FinancialHealthReport(
        company=company,
        period_label=period_label,
        periods_considered=periods_considered,
        analysis_window=analysis_window,
        dimensions=dimensions,
        signals=signals,
        changes_since_previous_period=_changes_since_previous_period(ratio_trends),
        data_quality=_data_quality_rollup(ratio_trends),
    )
