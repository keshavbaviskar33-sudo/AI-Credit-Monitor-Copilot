"""Grouping ratio trends into health dimensions and aggregating a dimension
status from them (§5, §9, §26 of the phase brief).

Dimensions are exactly `ratios/registry.py::RatioDefinition.category`
(liquidity/leverage/profitability/coverage/cash_flow) -- derived from the
Phase 6 catalog, not redeclared here, so a new ratio's category is
automatically its dimension with no second list to keep in sync.
"""

from __future__ import annotations

from collections.abc import Sequence

from credit_risk_copilot.health.models import DimensionStatus, EconomicDirection, RatioTrend
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS

#: Every dimension, in the catalog's own declaration order (liquidity,
#: leverage, profitability, coverage, cash_flow) -- keeps report output
#: deterministic and matches the order `docs/ratios.md` already presents
#: the categories in.
DIMENSIONS: tuple[str, ...] = tuple(dict.fromkeys(d.category for d in RATIO_DEFINITIONS))


def dimension_status(ratio_trends: Sequence[RatioTrend]) -> DimensionStatus:
    """Aggregate one dimension's ratio trends into a single status (§26).

    Deterministic, disclosed rule, no hidden weighting: count how many
    ratios in the dimension reached a conclusive `IMPROVING`/`STABLE`/
    `DETERIORATING` `economic_direction` (`NOT_MEANINGFUL`,
    `INSUFFICIENT_DATA` and `DISCONTINUOUS_HISTORY` are inconclusive and
    excluded from the tally, not silently counted as `STABLE`). If both
    `DETERIORATING` and `IMPROVING` ratios are present, the dimension is
    `MIXED` -- never silently netted into one direction, because a
    dimension with both is genuinely ambiguous and hiding that would be
    exactly the false precision §5/§25 warn against.
    """
    deteriorating = sum(
        1 for t in ratio_trends if t.economic_direction is EconomicDirection.DETERIORATING
    )
    improving = sum(1 for t in ratio_trends if t.economic_direction is EconomicDirection.IMPROVING)
    stable = sum(1 for t in ratio_trends if t.economic_direction is EconomicDirection.STABLE)

    if deteriorating + improving + stable == 0:
        return DimensionStatus.INSUFFICIENT_DATA
    if deteriorating and improving:
        return DimensionStatus.MIXED
    if deteriorating:
        return DimensionStatus.DETERIORATING
    if improving:
        return DimensionStatus.IMPROVING
    return DimensionStatus.STABLE


def group_by_dimension(ratio_trends: Sequence[RatioTrend]) -> dict[str, tuple[RatioTrend, ...]]:
    """Every trend, bucketed by its ratio's `category`, in `DIMENSIONS`
    order. A dimension with no trends supplied is simply absent from the
    result -- callers decide whether that itself is worth reporting."""
    by_ratio_id = {d.ratio_id: d.category for d in RATIO_DEFINITIONS}
    grouped: dict[str, list[RatioTrend]] = {dim: [] for dim in DIMENSIONS}
    for trend in ratio_trends:
        category = by_ratio_id[trend.ratio_id]
        grouped[category].append(trend)
    return {dim: tuple(trends) for dim, trends in grouped.items() if trends}
