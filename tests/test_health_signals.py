"""Tests for `health/signals.py` -- turning `RatioTrend`s (+ dimension
statuses) into structured `Signal`s (§10, §15, §21, §22, §38)."""

from __future__ import annotations

import pytest

from credit_risk_copilot.health.dimensions import dimension_status, group_by_dimension
from credit_risk_copilot.health.direction import RATIO_DIRECTIONS
from credit_risk_copilot.health.models import DimensionStatus, RatioTrend, Signal, SignalCode
from credit_risk_copilot.health.signals import generate_signals
from credit_risk_copilot.health.trend import compute_ratio_trend
from credit_risk_copilot.ratios.models import RatioWarning, WarningCode
from tests._health_helpers import result


def _trend(ratio_id: str, values: list[float], **kwargs) -> RatioTrend:
    periods = ["FY2023", "FY2024", "FY2025"][: len(values)]
    results = [
        result(
            ratio_id, p, v, **({"warnings": kwargs["warnings"][i]} if "warnings" in kwargs else {})
        )
        for i, (p, v) in enumerate(zip(periods, values, strict=True))
    ]
    return compute_ratio_trend(ratio_id, results, RATIO_DIRECTIONS[ratio_id])


@pytest.mark.parametrize(
    ("ratio_id", "increasing_is_deteriorating", "code"),
    [
        ("current_ratio", False, SignalCode.LIQUIDITY_DETERIORATION),
        ("quick_ratio", False, SignalCode.LIQUIDITY_DETERIORATION),
        ("debt_to_equity", True, SignalCode.LEVERAGE_DETERIORATION),
        ("debt_to_assets", True, SignalCode.LEVERAGE_DETERIORATION),
        ("liabilities_to_assets", True, SignalCode.LEVERAGE_DETERIORATION),
        ("gross_margin", False, SignalCode.MARGIN_COMPRESSION),
        ("operating_margin", False, SignalCode.MARGIN_COMPRESSION),
        ("net_profit_margin", False, SignalCode.MARGIN_COMPRESSION),
        ("roa", False, SignalCode.PROFITABILITY_DETERIORATION),
        ("roe", False, SignalCode.PROFITABILITY_DETERIORATION),
        ("interest_coverage", False, SignalCode.INTEREST_COVERAGE_DECLINE),
        ("ocf_to_debt", False, SignalCode.CASH_FLOW_WEAKENING),
        ("ocf_to_revenue", False, SignalCode.CASH_FLOW_WEAKENING),
    ],
)
def test_deterioration_signal_fires_for_every_ratio(
    ratio_id: str, increasing_is_deteriorating: bool, code: SignalCode
) -> None:
    values = [1.0, 1.5, 2.0] if increasing_is_deteriorating else [2.0, 1.5, 1.0]
    trend = _trend(ratio_id, values)
    signals = generate_signals([trend], {})
    assert any(s.code is code and s.ratio_id == ratio_id for s in signals)


def test_no_signal_when_stable() -> None:
    trend = _trend("current_ratio", [1.0, 1.01, 1.02])
    signals = generate_signals([trend], {})
    assert signals == ()


def test_no_deterioration_signal_when_improving() -> None:
    trend = _trend("current_ratio", [1.0, 1.5, 2.0])  # higher current_ratio is improving
    signals = generate_signals([trend], {})
    codes = {s.code for s in signals}
    assert SignalCode.LIQUIDITY_DETERIORATION not in codes


def test_negative_equity_signal() -> None:
    warning = (
        RatioWarning(code=WarningCode.NEGATIVE_EQUITY, concept="shareholders_equity", message="m"),
    )
    trend = _trend("debt_to_equity", [-6.0, -5.0, -4.0], warnings=[warning, warning, warning])
    signals = generate_signals([trend], {})
    assert any(
        s.code is SignalCode.NEGATIVE_EQUITY and s.ratio_id == "debt_to_equity" for s in signals
    )
    # A sign-crossing denominator must never also claim leverage improved.
    assert not any(s.code is SignalCode.LEVERAGE_DETERIORATION for s in signals)


def test_unusual_movement_signal() -> None:
    values = [1.00, 1.01, 1.04, 1.09, 1.59]
    periods = ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]
    results = [result("current_ratio", p, v) for p, v in zip(periods, values, strict=True)]
    trend = compute_ratio_trend("current_ratio", results, RATIO_DIRECTIONS["current_ratio"])
    signals = generate_signals([trend], {})
    assert any(
        s.code is SignalCode.UNUSUAL_MOVEMENT and s.ratio_id == "current_ratio" for s in signals
    )


def test_multi_dimension_deterioration_requires_the_configured_minimum() -> None:
    statuses_two = {
        "liquidity": DimensionStatus.DETERIORATING,
        "leverage": DimensionStatus.DETERIORATING,
        "profitability": DimensionStatus.STABLE,
    }
    assert generate_signals([], statuses_two) == ()

    statuses_three = {**statuses_two, "coverage": DimensionStatus.DETERIORATING}
    signals = generate_signals([], statuses_three)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.code is SignalCode.MULTI_DIMENSION_DETERIORATION
    assert signal.category == "cross_dimension"
    assert signal.ratio_id is None
    assert set(signal.affected_dimensions) == {"liquidity", "leverage", "coverage"}


def test_dimension_status_and_generate_signals_integrate_end_to_end() -> None:
    """A small integration check across dimensions.py + signals.py, matching
    how engine.py actually wires them together."""
    trends = [
        _trend("current_ratio", [1.8, 1.5, 1.2]),  # liquidity: deteriorating
        _trend("debt_to_equity", [1.0, 1.3, 1.8]),  # leverage: deteriorating
        _trend("interest_coverage", [5.0, 4.0, 3.0]),  # coverage: deteriorating
        _trend("gross_margin", [0.4, 0.35, 0.3]),  # profitability: deteriorating
    ]
    grouped = group_by_dimension(trends)
    statuses = {dim: dimension_status(ts) for dim, ts in grouped.items()}
    signals = generate_signals(trends, statuses)

    codes = {s.code for s in signals}
    assert SignalCode.LIQUIDITY_DETERIORATION in codes
    assert SignalCode.LEVERAGE_DETERIORATION in codes
    assert SignalCode.INTEREST_COVERAGE_DECLINE in codes
    assert SignalCode.MARGIN_COMPRESSION in codes
    assert SignalCode.MULTI_DIMENSION_DETERIORATION in codes


def test_signal_is_a_frozen_model_with_deterministic_evidence() -> None:
    trend = _trend("current_ratio", [1.8, 1.5, 1.2])
    signals = generate_signals([trend], {})
    signal = signals[0]
    assert isinstance(signal, Signal)
    assert signal.evidence  # non-empty, factual
    assert "current_ratio" in signal.evidence
