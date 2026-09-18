"""Deterministic financial-health and early-warning analysis (Phase 7).

Turns Phase 6's ratio history into interpretable trends, dimension status
and structured early-warning signals (`docs/financial_health.md`). No LLM,
no ML, no credit decision -- this package answers "what changed, and does
it deserve attention", never "should this borrower be approved" (Phase 12).

    health = analyze_financial_health(company, ratio_history)
    health.dimensions["leverage"].status        # DimensionStatus.DETERIORATING
    health.signals                              # every early-warning Signal
    health.changes_since_previous_period         # reused Phase 6 RatioChange
"""

from credit_risk_copilot.health.dimensions import DIMENSIONS, dimension_status, group_by_dimension
from credit_risk_copilot.health.direction import RATIO_DIRECTIONS, economic_direction
from credit_risk_copilot.health.engine import analyze_financial_health
from credit_risk_copilot.health.models import (
    DataQuality,
    DataQualityLevel,
    DimensionHealth,
    DimensionStatus,
    EconomicDirection,
    FinancialHealthReport,
    HistoryDepth,
    RatioDirection,
    RatioTrend,
    Signal,
    SignalCode,
    TrendDirection,
)
from credit_risk_copilot.health.signals import generate_signals
from credit_risk_copilot.health.trend import compute_ratio_trend, fiscal_sort_key

__all__ = [
    "DIMENSIONS",
    "RATIO_DIRECTIONS",
    "DataQuality",
    "DataQualityLevel",
    "DimensionHealth",
    "DimensionStatus",
    "EconomicDirection",
    "FinancialHealthReport",
    "HistoryDepth",
    "RatioDirection",
    "RatioTrend",
    "Signal",
    "SignalCode",
    "TrendDirection",
    "analyze_financial_health",
    "compute_ratio_trend",
    "dimension_status",
    "economic_direction",
    "fiscal_sort_key",
    "generate_signals",
    "group_by_dimension",
]
