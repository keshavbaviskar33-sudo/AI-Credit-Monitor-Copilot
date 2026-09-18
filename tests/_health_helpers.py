"""Shared `RatioResult` builder for Phase 7 (`health/`) tests.

Not a test module itself (no `test_` prefix, so pytest does not collect it).
Builds `RatioResult` objects directly rather than going through
`ratios.engine.calculate_ratio` -- `health/` only ever consumes `RatioResult`
values (the Phase 6/7 boundary), so its own tests should not need to
construct `CanonicalFact`s at all, mirroring how `test_ratios_engine.py`
itself never imports anything from `extraction`/`resolver`.
"""

from __future__ import annotations

from credit_risk_copilot.ratios.models import RatioResult, RatioStatus, RatioWarning
from credit_risk_copilot.ratios.registry import RATIOS_BY_ID


def result(
    ratio_id: str,
    period_label: str,
    value: float | None,
    *,
    status: RatioStatus = RatioStatus.CALCULATED,
    warnings: tuple[RatioWarning, ...] = (),
    reason: str | None = None,
) -> RatioResult:
    definition = RATIOS_BY_ID[ratio_id]
    return RatioResult(
        ratio_id=ratio_id,
        name=definition.name,
        category=definition.category,
        period_label=period_label,
        value=value,
        unit=definition.unit,
        status=status,
        formula=definition.formula,
        formula_display=definition.formula_display,
        inputs={},
        warnings=warnings,
        reason=reason,
    )


def missing(ratio_id: str, period_label: str) -> RatioResult:
    return result(
        ratio_id,
        period_label,
        None,
        status=RatioStatus.MISSING_INPUT,
        reason="Missing required input(s).",
    )
