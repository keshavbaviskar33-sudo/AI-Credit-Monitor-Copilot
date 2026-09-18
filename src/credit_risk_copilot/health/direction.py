"""Per-ratio economic direction metadata (§8 of the phase brief).

Ratio direction is not universal: a rising Debt-to-Equity is weaker, but a
rising Current Ratio is stronger. Encoding that generically ("if ratio
increases, risk += 1") would be wrong for roughly a third of the catalog, so
each `RatioDefinition` gets one explicit `RatioDirection` entry here instead.

Deliberately lives in `health/`, not `ratios/registry.py`: Phase 6 states
what a ratio equals, never whether that is stronger or weaker (`ratios.md`
§1 -- "Phase 6 does not decide whether a ratio value is good, bad, or a
warning sign. That is Phase 7."). Attaching this metadata to the Phase 6
registry would blur that boundary; a completeness test
(`test_health_direction.py`) instead checks every `RATIO_DEFINITIONS` id has
an entry here, so the two catalogs cannot silently drift apart.
"""

from __future__ import annotations

from credit_risk_copilot.health.models import EconomicDirection, RatioDirection, TrendDirection

#: One entry per ratio in `ratios/registry.py::RATIO_DEFINITIONS`. Only the
#: three leverage ratios are `LOWER_IS_STRONGER` -- more debt relative to
#: equity/assets is the conventional weaker state; every other ratio in this
#: catalog (liquidity, margins/returns, coverage, cash-flow-to-debt/revenue)
#: is `HIGHER_IS_STRONGER`, matching how each is defined (a larger cushion,
#: margin, coverage multiple or cash-generation ratio is the stronger state).
RATIO_DIRECTIONS: dict[str, RatioDirection] = {
    "current_ratio": RatioDirection.HIGHER_IS_STRONGER,
    "quick_ratio": RatioDirection.HIGHER_IS_STRONGER,
    "debt_to_equity": RatioDirection.LOWER_IS_STRONGER,
    "debt_to_assets": RatioDirection.LOWER_IS_STRONGER,
    "liabilities_to_assets": RatioDirection.LOWER_IS_STRONGER,
    "gross_margin": RatioDirection.HIGHER_IS_STRONGER,
    "operating_margin": RatioDirection.HIGHER_IS_STRONGER,
    "net_profit_margin": RatioDirection.HIGHER_IS_STRONGER,
    "roa": RatioDirection.HIGHER_IS_STRONGER,
    "roe": RatioDirection.HIGHER_IS_STRONGER,
    "interest_coverage": RatioDirection.HIGHER_IS_STRONGER,
    "ocf_to_debt": RatioDirection.HIGHER_IS_STRONGER,
    "ocf_to_revenue": RatioDirection.HIGHER_IS_STRONGER,
}

#: `TrendDirection` values that carry no economic meaning of their own --
#: passed straight through to the matching `EconomicDirection` regardless of
#: `RatioDirection`, because there is nothing to interpret (§8: these are
#: facts about data availability/interpretability, not about which way is
#: "up").
_DIRECTIONLESS: dict[TrendDirection, EconomicDirection] = {
    TrendDirection.STABLE: EconomicDirection.STABLE,
    TrendDirection.NOT_MEANINGFUL: EconomicDirection.NOT_MEANINGFUL,
    TrendDirection.INSUFFICIENT_DATA: EconomicDirection.INSUFFICIENT_DATA,
    TrendDirection.DISCONTINUOUS_HISTORY: EconomicDirection.DISCONTINUOUS_HISTORY,
}


def economic_direction(
    direction: TrendDirection, ratio_direction: RatioDirection
) -> EconomicDirection:
    """Interpret a raw `TrendDirection` through one ratio's `RatioDirection`
    (§8). Only `INCREASING`/`DECREASING` actually depend on `ratio_direction`
    -- every other `TrendDirection` means the same thing regardless of which
    way is economically stronger for this ratio."""
    if direction in _DIRECTIONLESS:
        return _DIRECTIONLESS[direction]
    is_increasing = direction is TrendDirection.INCREASING
    stronger = is_increasing == (ratio_direction is RatioDirection.HIGHER_IS_STRONGER)
    return EconomicDirection.IMPROVING if stronger else EconomicDirection.DETERIORATING
