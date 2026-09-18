"""End-to-end tests for `health/engine.py::analyze_financial_health`.

`test_matches_the_phase_brief_worked_example` builds the exact numbers from
the phase brief's own end-to-end example (§34: "FINANCIAL HEALTH -- FY2025")
through the real public entry point, so the test doubles as a check that the
whole pipeline reproduces the brief's own scenario end to end, not just each
module in isolation.
"""

from __future__ import annotations

from credit_risk_copilot.health.engine import analyze_financial_health
from credit_risk_copilot.health.models import DataQualityLevel, DimensionStatus, SignalCode
from credit_risk_copilot.ratios.models import RatioResult, RatioWarning, WarningCode
from tests._health_helpers import result


def _series(ratio_id: str, periods: list[str], values: list[float]) -> list[RatioResult]:
    return [result(ratio_id, p, v) for p, v in zip(periods, values, strict=True)]


def test_matches_the_phase_brief_worked_example() -> None:
    periods_3 = ["FY2023", "FY2024", "FY2025"]
    ratio_history = {
        "current_ratio": _series("current_ratio", periods_3, [1.82, 1.51, 1.18]),
        "debt_to_equity": _series("debt_to_equity", periods_3, [0.91, 1.23, 1.72]),
        "operating_margin": _series("operating_margin", periods_3, [0.121, 0.104, 0.072]),
        "ocf_to_debt": _series("ocf_to_debt", periods_3, [0.41, 0.35, 0.22]),
        # give coverage a 3rd conclusive dimension so the phase brief's
        # MULTI_DIMENSION_DETERIORATION example (4-5 dimensions down at once)
        # is reachable through the real MULTI_DIMENSION_MIN_DIMENSIONS gate.
        "interest_coverage": _series("interest_coverage", periods_3, [8.0, 6.0, 4.0]),
    }

    health = analyze_financial_health("Example Corp", ratio_history)

    assert health.company == "Example Corp"
    assert health.period_label == "FY2025"
    assert health.periods_considered == ("FY2023", "FY2024", "FY2025")

    assert health.dimensions["liquidity"].status is DimensionStatus.DETERIORATING
    assert health.dimensions["leverage"].status is DimensionStatus.DETERIORATING
    assert health.dimensions["profitability"].status is DimensionStatus.DETERIORATING
    assert health.dimensions["cash_flow"].status is DimensionStatus.DETERIORATING
    assert health.dimensions["coverage"].status is DimensionStatus.DETERIORATING

    codes = {s.code for s in health.signals}
    assert SignalCode.LIQUIDITY_DETERIORATION in codes
    assert SignalCode.LEVERAGE_DETERIORATION in codes
    assert SignalCode.MARGIN_COMPRESSION in codes
    assert SignalCode.CASH_FLOW_WEAKENING in codes
    assert SignalCode.INTEREST_COVERAGE_DECLINE in codes
    assert SignalCode.MULTI_DIMENSION_DETERIORATION in codes

    # Leverage persistence: 0.91 -> 1.23 -> 1.72, two consecutive increases.
    leverage_trend = next(
        t for t in health.dimensions["leverage"].ratio_trends if t.ratio_id == "debt_to_equity"
    )
    assert leverage_trend.persistence == 2

    # "WHAT CHANGED SINCE FY2024?" -- the most recent period-over-period
    # change for each ratio, reused verbatim from Phase 6's own arithmetic.
    changes = {c.ratio_id: c for c in health.changes_since_previous_period}
    assert changes["debt_to_equity"].from_period == "FY2024"
    assert changes["debt_to_equity"].to_period == "FY2025"
    assert changes["debt_to_equity"].from_value == 1.23
    assert changes["debt_to_equity"].to_value == 1.72

    assert health.data_quality is not None  # every field is reachable, no crash


def test_a_ratio_absent_from_ratio_history_is_insufficient_data_not_a_crash() -> None:
    health = analyze_financial_health(
        "Sparse Co",
        {
            "current_ratio": _series(
                "current_ratio", ["FY2023", "FY2024", "FY2025"], [1.0, 1.2, 1.5]
            )
        },
    )
    # Every one of the 13 catalog ratios is represented, even ones never
    # supplied at all -- as INSUFFICIENT_DATA, never a crash or a silent gap.
    all_trends = [t for dim in health.dimensions.values() for t in dim.ratio_trends]
    assert len(all_trends) == 13
    debt_to_equity = next(t for t in all_trends if t.ratio_id == "debt_to_equity")
    assert debt_to_equity.direction.value == "insufficient_data"
    assert debt_to_equity.periods_available == 0
    # Its dimension is still INSUFFICIENT_DATA, not silently absent.
    assert health.dimensions["leverage"].status is DimensionStatus.INSUFFICIENT_DATA


def test_no_signals_when_every_dimension_is_stable_or_improving() -> None:
    """§38: no false positives from noise alone."""
    periods = ["FY2023", "FY2024", "FY2025"]
    ratio_history = {
        "current_ratio": _series("current_ratio", periods, [1.50, 1.51, 1.49]),
        "debt_to_equity": _series("debt_to_equity", periods, [1.00, 0.90, 0.80]),
    }
    health = analyze_financial_health("Stable Co", ratio_history)
    assert health.signals == ()
    assert health.dimensions["liquidity"].status is DimensionStatus.STABLE
    assert health.dimensions["leverage"].status is DimensionStatus.IMPROVING


def test_report_level_data_quality_priority() -> None:
    """LOW_CONFIDENCE beats MANUALLY_ADJUSTED beats DERIVED_INPUTS beats
    GOOD when rolling several ratios' levels into one (§18, §19), mirroring
    `RatioResult`'s own documented status-priority convention."""
    low_conf = (
        RatioWarning(code=WarningCode.LOW_CONFIDENCE_INPUT, concept="total_debt", message="m"),
    )
    manual = (RatioWarning(code=WarningCode.MANUAL_INPUT, concept="total_debt", message="m"),)
    derived = (RatioWarning(code=WarningCode.DERIVED_INPUT, concept="total_debt", message="m"),)
    periods = ["FY2023", "FY2024", "FY2025"]
    ratio_history = {
        "debt_to_equity": [
            result("debt_to_equity", p, 1.0 + i * 0.1, warnings=low_conf if i == 2 else ())
            for i, p in enumerate(periods)
        ],
        "roe": [
            result("roe", p, 0.1 + i * 0.01, warnings=manual if i == 2 else ())
            for i, p in enumerate(periods)
        ],
        "gross_margin": [
            result("gross_margin", p, 0.4 + i * 0.01, warnings=derived if i == 2 else ())
            for i, p in enumerate(periods)
        ],
    }
    health = analyze_financial_health("Co", ratio_history)
    assert health.data_quality.level is DataQualityLevel.LOW_CONFIDENCE
    assert health.data_quality.ratios_with_low_confidence_input == ("debt_to_equity",)
    assert health.data_quality.ratios_with_manual_correction == ("roe",)
    assert health.data_quality.ratios_with_derived_input == ("gross_margin",)

    # Without the low-confidence ratio, manual beats derived.
    health_no_low_conf = analyze_financial_health(
        "Co", {"roe": ratio_history["roe"], "gross_margin": ratio_history["gross_margin"]}
    )
    assert health_no_low_conf.data_quality.level is DataQualityLevel.MANUALLY_ADJUSTED

    # With only a derived input present, derived beats good.
    health_derived_only = analyze_financial_health(
        "Co", {"gross_margin": ratio_history["gross_margin"]}
    )
    assert health_derived_only.data_quality.level is DataQualityLevel.DERIVED_INPUTS


def test_dimensions_is_a_plain_dict_keyed_by_dimension_name() -> None:
    periods = ["FY2023", "FY2024", "FY2025"]
    health = analyze_financial_health(
        "Co", {"current_ratio": _series("current_ratio", periods, [1.0, 1.1, 1.2])}
    )
    assert isinstance(health.dimensions, dict)
    assert health.dimensions["liquidity"].status is DimensionStatus.IMPROVING
    assert set(health.dimensions) == {
        "liquidity",
        "leverage",
        "profitability",
        "coverage",
        "cash_flow",
    }
