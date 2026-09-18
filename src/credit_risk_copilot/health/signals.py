"""Signal generation: `RatioTrend`s (+ dimension statuses) -> structured
`Signal`s (§10, §15, §21, §22, §38, §39, §40 of the phase brief).

Every signal is raised from a disclosed, deterministic condition on already-
computed `RatioTrend` fields -- nothing here recomputes arithmetic Phase 6
or `trend.py` already did, and nothing here claims a cause the data does not
support (§32, §46: "infer causes that aren't supported").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from credit_risk_copilot.health.models import (
    DimensionStatus,
    EconomicDirection,
    RatioTrend,
    Signal,
    SignalCode,
)
from credit_risk_copilot.health.thresholds import MULTI_DIMENSION_MIN_DIMENSIONS
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS

#: Which deterioration signal a ratio raises when its `economic_direction`
#: is `DETERIORATING` (§10). Two profitability signals, not one: a margin
#: ratio and a return ratio (ROA/ROE) can move independently (e.g. margins
#: flat, ROE down purely from an equity change), a distinct fact worth
#: naming separately rather than folding into one code.
_DETERIORATION_SIGNAL: dict[str, SignalCode] = {
    "current_ratio": SignalCode.LIQUIDITY_DETERIORATION,
    "quick_ratio": SignalCode.LIQUIDITY_DETERIORATION,
    "debt_to_equity": SignalCode.LEVERAGE_DETERIORATION,
    "debt_to_assets": SignalCode.LEVERAGE_DETERIORATION,
    "liabilities_to_assets": SignalCode.LEVERAGE_DETERIORATION,
    "gross_margin": SignalCode.MARGIN_COMPRESSION,
    "operating_margin": SignalCode.MARGIN_COMPRESSION,
    "net_profit_margin": SignalCode.MARGIN_COMPRESSION,
    "roa": SignalCode.PROFITABILITY_DETERIORATION,
    "roe": SignalCode.PROFITABILITY_DETERIORATION,
    "interest_coverage": SignalCode.INTEREST_COVERAGE_DECLINE,
    "ocf_to_debt": SignalCode.CASH_FLOW_WEAKENING,
    "ocf_to_revenue": SignalCode.CASH_FLOW_WEAKENING,
}

_CATEGORY_BY_RATIO: dict[str, str] = {d.ratio_id: d.category for d in RATIO_DEFINITIONS}


def _unusual_movement_evidence(trend: RatioTrend) -> str:
    calculated = [r for r in trend.results if r.value is not None]
    if len(calculated) >= 2:
        prior, latest = calculated[-2], calculated[-1]
        move = (
            f"{trend.ratio_id} moved from {prior.value:,.4g} ({prior.period_label}) to "
            f"{latest.value:,.4g} ({latest.period_label}) -- outside the pattern of its own "
            "prior period-over-period moves (robust z-score)."
        )
    else:  # pragma: no cover
        # Defensive only: `unusual_movement` is never `True` with fewer than
        # `UNUSUAL_MOVEMENT_MIN_PRIOR_DELTAS + 2` calculated periods
        # (`trend.py::_unusual_movement`), so this signal is never raised
        # with fewer than 2 calculated results to describe.
        move = f"{trend.ratio_id}'s latest move is outside the pattern of its own history."
    return move


def _ratio_signals(trend: RatioTrend) -> list[Signal]:
    category = _CATEGORY_BY_RATIO[trend.ratio_id]
    signals: list[Signal] = []
    if trend.economic_direction is EconomicDirection.DETERIORATING:
        signals.append(
            Signal(
                code=_DETERIORATION_SIGNAL[trend.ratio_id],
                category=category,
                ratio_id=trend.ratio_id,
                trend=trend,
                evidence=trend.explain(),
            )
        )
    if trend.negative_equity:
        signals.append(
            Signal(
                code=SignalCode.NEGATIVE_EQUITY,
                category=category,
                ratio_id=trend.ratio_id,
                trend=trend,
                evidence=trend.explain(),
            )
        )
    if trend.unusual_movement:
        signals.append(
            Signal(
                code=SignalCode.UNUSUAL_MOVEMENT,
                category=category,
                ratio_id=trend.ratio_id,
                trend=trend,
                evidence=_unusual_movement_evidence(trend),
            )
        )
    return signals


def _multi_dimension_signal(dimension_statuses: Mapping[str, DimensionStatus]) -> Signal | None:
    deteriorating = tuple(
        dim for dim, status in dimension_statuses.items() if status is DimensionStatus.DETERIORATING
    )
    if len(deteriorating) < MULTI_DIMENSION_MIN_DIMENSIONS:
        return None
    evidence = (
        f"{len(deteriorating)} of {len(dimension_statuses)} monitored dimensions are "
        f"independently deteriorating for this period: {', '.join(deteriorating)}. This "
        "states that multiple monitored dimensions moved in concerning directions under "
        "this engine's deterministic rules -- not a conclusion about overall credit risk."
    )
    return Signal(
        code=SignalCode.MULTI_DIMENSION_DETERIORATION,
        category="cross_dimension",
        ratio_id=None,
        trend=None,
        affected_dimensions=deteriorating,
        evidence=evidence,
    )


def generate_signals(
    ratio_trends: Sequence[RatioTrend], dimension_statuses: Mapping[str, DimensionStatus]
) -> tuple[Signal, ...]:
    """Every signal for one report: per-ratio signals from each trend, plus
    the cross-dimension signal if the breadth bar is met (§15)."""
    signals: list[Signal] = []
    for trend in ratio_trends:
        signals.extend(_ratio_signals(trend))
    multi_dimension = _multi_dimension_signal(dimension_statuses)
    if multi_dimension is not None:
        signals.append(multi_dimension)
    return tuple(signals)
