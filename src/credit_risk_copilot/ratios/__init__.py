"""Deterministic financial ratio engine (Phase 6).

Turns Phase 5's canonical financial facts into typed, provenance-carrying
ratio results (`docs/ratios.md`). No LLM, no credit decision -- this package
answers "what does this ratio equal", never "is that good or bad" (Phase 7).

    ratios = ratios_for_filing(filing)              # every comparative period
    ratios["debt_to_equity"][0].value               # 1.74
    ratios["debt_to_equity"][0].explain()            # formula + inputs
"""

from credit_risk_copilot.ratios.engine import (
    calculate_ratio,
    calculate_ratio_history,
    calculate_ratios,
    ratio_history_changes,
    ratios_for_filing,
    ratios_from_facts,
)
from credit_risk_copilot.ratios.models import (
    RatioChange,
    RatioResult,
    RatioStatus,
    RatioWarning,
    WarningCode,
)
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS, RATIOS_BY_ID, RatioDefinition

__all__ = [
    "RATIOS_BY_ID",
    "RATIO_DEFINITIONS",
    "RatioChange",
    "RatioDefinition",
    "RatioResult",
    "RatioStatus",
    "RatioWarning",
    "WarningCode",
    "calculate_ratio",
    "calculate_ratio_history",
    "calculate_ratios",
    "ratio_history_changes",
    "ratios_for_filing",
    "ratios_from_facts",
]
