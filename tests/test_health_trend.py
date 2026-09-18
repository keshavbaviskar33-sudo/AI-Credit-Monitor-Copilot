"""Tests for `health/trend.py` -- the deterministic trend engine.

Numeric fixtures for the direction/magnitude/persistence tests are taken
directly from the phase brief's own worked examples (§16, §39: Debt-to-Equity
0.92x -> 1.10x -> 1.34x -> 1.72x, "change over two periods: +68.6%") so the
tests double as a check that this engine reproduces the brief's own numbers,
not just internally-consistent ones.
"""

from __future__ import annotations

import pytest

from credit_risk_copilot.health.models import (
    DataQualityLevel,
    EconomicDirection,
    HistoryDepth,
    RatioDirection,
    TrendDirection,
)
from credit_risk_copilot.health.trend import compute_ratio_trend, fiscal_sort_key
from credit_risk_copilot.ratios.models import RatioWarning, WarningCode
from tests._health_helpers import missing, result

_HIGHER = RatioDirection.HIGHER_IS_STRONGER
_LOWER = RatioDirection.LOWER_IS_STRONGER


def test_fiscal_sort_key_reads_the_year() -> None:
    assert fiscal_sort_key("FY2025") == 2025
    assert fiscal_sort_key("FY2024") == 2024
    assert fiscal_sort_key("not-a-period") == 0


def test_increasing_leverage_matches_the_brief_worked_example() -> None:
    """debt_to_equity 1.02x -> 1.34x -> 1.72x (§39): "change over two
    periods: +68.6%"."""
    results = [
        result("debt_to_equity", "FY2023", 1.02),
        result("debt_to_equity", "FY2024", 1.34),
        result("debt_to_equity", "FY2025", 1.72),
    ]
    trend = compute_ratio_trend("debt_to_equity", results, _LOWER)

    assert trend.direction is TrendDirection.INCREASING
    assert trend.economic_direction is EconomicDirection.DETERIORATING  # lower is stronger
    assert trend.persistence == 2
    assert trend.absolute_change == pytest.approx(0.70)
    assert trend.percent_change == pytest.approx(0.686, abs=1e-3)
    assert trend.history_depth is HistoryDepth.ADEQUATE
    assert trend.periods_available == 3


def test_persistence_over_four_periods_matches_the_brief_worked_example() -> None:
    """debt_to_equity 0.92x -> 1.10x -> 1.34x -> 1.72x (§16): 3 consecutive
    increases."""
    results = [
        result("debt_to_equity", "FY2022", 0.92),
        result("debt_to_equity", "FY2023", 1.10),
        result("debt_to_equity", "FY2024", 1.34),
        result("debt_to_equity", "FY2025", 1.72),
    ]
    trend = compute_ratio_trend("debt_to_equity", results, _LOWER)

    assert trend.direction is TrendDirection.INCREASING
    assert trend.persistence == 3
    assert trend.periods_available == 4


def test_higher_is_stronger_ratio_increasing_is_improving() -> None:
    results = [
        result("current_ratio", "FY2023", 1.00),
        result("current_ratio", "FY2024", 1.20),
        result("current_ratio", "FY2025", 1.50),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.direction is TrendDirection.INCREASING
    assert trend.economic_direction is EconomicDirection.IMPROVING


def test_decreasing_liquidity_is_deteriorating() -> None:
    results = [
        result("current_ratio", "FY2023", 1.82),
        result("current_ratio", "FY2024", 1.51),
        result("current_ratio", "FY2025", 1.18),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.direction is TrendDirection.DECREASING
    assert trend.economic_direction is EconomicDirection.DETERIORATING
    assert trend.absolute_change == pytest.approx(-0.64)


def test_small_moves_stay_within_the_stable_threshold() -> None:
    results = [
        result("current_ratio", "FY2023", 1.00),
        result("current_ratio", "FY2024", 1.01),
        result("current_ratio", "FY2025", 1.02),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.direction is TrendDirection.STABLE
    assert trend.economic_direction is EconomicDirection.STABLE
    assert trend.persistence == 0


def test_persistence_distinguishes_persistent_from_noisy_series() -> None:
    """§6's own distinguishing example: a steadily increasing series should
    report full trailing persistence; a series that moved up-down-up should
    only count the trailing run."""
    persistent = [
        result("debt_to_equity", "FY2022", 0.8),
        result("debt_to_equity", "FY2023", 1.0),
        result("debt_to_equity", "FY2024", 1.3),
        result("debt_to_equity", "FY2025", 1.7),
    ]
    noisy = [
        result("debt_to_equity", "FY2022", 0.9),
        result("debt_to_equity", "FY2023", 1.2),
        result("debt_to_equity", "FY2024", 1.0),
        result("debt_to_equity", "FY2025", 1.1),
    ]
    persistent_trend = compute_ratio_trend("debt_to_equity", persistent, _LOWER)
    noisy_trend = compute_ratio_trend("debt_to_equity", noisy, _LOWER)

    assert persistent_trend.direction is TrendDirection.INCREASING
    assert persistent_trend.persistence == 3
    assert noisy_trend.direction is TrendDirection.INCREASING  # net move is still up overall
    assert noisy_trend.persistence == 1  # only the trailing increase counts


def test_missing_period_produces_discontinuous_history_not_a_trend() -> None:
    """§17: a gap must never look like stability, and a trend must never be
    computed across it."""
    results = [
        result("current_ratio", "FY2022", 1.2),
        missing("current_ratio", "FY2023"),
        result("current_ratio", "FY2024", 1.5),
        result("current_ratio", "FY2025", 1.7),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)

    assert trend.direction is TrendDirection.DISCONTINUOUS_HISTORY
    assert trend.economic_direction is EconomicDirection.DISCONTINUOUS_HISTORY
    assert trend.has_gap is True
    assert trend.gap_periods == ("FY2023",)
    assert trend.absolute_change is None
    assert trend.persistence == 0
    assert trend.reason is not None and "FY2023" in trend.reason


@pytest.mark.parametrize("n_periods", [0, 1, 2])
def test_fewer_than_three_consecutive_periods_is_insufficient_data(n_periods: int) -> None:
    periods = ["FY2023", "FY2024", "FY2025"][:n_periods]
    results = [result("current_ratio", p, 1.0 + i * 0.1) for i, p in enumerate(periods)]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)

    assert trend.direction is TrendDirection.INSUFFICIENT_DATA
    assert trend.economic_direction is EconomicDirection.INSUFFICIENT_DATA
    assert trend.periods_available == n_periods
    assert trend.history_depth is HistoryDepth.LIMITED
    assert trend.absolute_change is None


def test_negative_equity_is_not_meaningful_not_an_improvement() -> None:
    """§21: D/E numerically decreasing while equity stays negative must not
    be read as leverage improving."""
    warning = RatioWarning(
        code=WarningCode.NEGATIVE_EQUITY, concept="shareholders_equity", message="negative equity"
    )
    results = [
        result("debt_to_equity", "FY2023", -6.0, warnings=(warning,)),
        result("debt_to_equity", "FY2024", -5.0, warnings=(warning,)),
        result("debt_to_equity", "FY2025", -4.0, warnings=(warning,)),
    ]
    trend = compute_ratio_trend("debt_to_equity", results, _LOWER)

    assert trend.negative_equity is True
    assert trend.direction is TrendDirection.NOT_MEANINGFUL
    assert trend.economic_direction is EconomicDirection.NOT_MEANINGFUL
    assert trend.absolute_change is None
    assert trend.persistence == 0


def test_negative_equity_anywhere_in_the_window_suppresses_the_trend() -> None:
    """Even a single negative-equity period inside an otherwise ordinary
    window should stop this ratio's direction from being interpreted --
    a sign-crossing denominator breaks the arithmetic, not just the label."""
    warning = RatioWarning(
        code=WarningCode.NEGATIVE_EQUITY, concept="shareholders_equity", message="negative equity"
    )
    results = [
        result("debt_to_equity", "FY2023", 0.8),
        result("debt_to_equity", "FY2024", -3.0, warnings=(warning,)),
        result("debt_to_equity", "FY2025", 1.2),
    ]
    trend = compute_ratio_trend("debt_to_equity", results, _LOWER)
    assert trend.direction is TrendDirection.NOT_MEANINGFUL


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.0, 1.0, 1.0], TrendDirection.STABLE),
        ([1.0, 1.1, 1.21], TrendDirection.INCREASING),
        ([1.21, 1.1, 1.0], TrendDirection.DECREASING),
    ],
)
def test_direction_invariants(values: list[float], expected: TrendDirection) -> None:
    """§36: identical values -> STABLE; a monotonic series -> the matching
    direction."""
    results = [result("current_ratio", f"FY202{i}", v) for i, v in enumerate(values)]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.direction is expected


def test_baseline_median_and_deviation() -> None:
    results = [
        result("current_ratio", "FY2022", 1.0),
        result("current_ratio", "FY2023", 1.2),
        result("current_ratio", "FY2024", 1.4),
        result("current_ratio", "FY2025", 2.0),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    # median of [1.0, 1.2, 1.4] (every calculated value except the latest)
    assert trend.baseline_median == pytest.approx(1.2)
    assert trend.deviation_from_baseline == pytest.approx(0.8)


def test_baseline_is_none_below_minimum_prior_values() -> None:
    results = [result("current_ratio", "FY2024", 1.0), result("current_ratio", "FY2025", 1.1)]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.baseline_median is None
    assert trend.deviation_from_baseline is None


def test_unusual_movement_flagged_on_a_genuine_outlier() -> None:
    results = [
        result("current_ratio", "FY2021", 1.00),
        result("current_ratio", "FY2022", 1.01),
        result("current_ratio", "FY2023", 1.04),
        result("current_ratio", "FY2024", 1.09),
        result("current_ratio", "FY2025", 1.59),  # a sudden jump vs. the prior pattern
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.unusual_movement is True


def test_unusual_movement_not_flagged_with_too_few_prior_deltas() -> None:
    """§28/§29: never fabricate significance from a tiny sample."""
    results = [
        result("current_ratio", "FY2023", 1.0),
        result("current_ratio", "FY2024", 1.1),
        result("current_ratio", "FY2025", 5.0),  # a big move, but only 1 prior delta exists
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.unusual_movement is False


def test_unusual_movement_not_flagged_when_latest_period_is_missing() -> None:
    results = [
        result("current_ratio", "FY2021", 1.00),
        result("current_ratio", "FY2022", 1.01),
        result("current_ratio", "FY2023", 1.04),
        result("current_ratio", "FY2024", 1.09),
        missing("current_ratio", "FY2025"),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.unusual_movement is False


@pytest.mark.parametrize(
    ("warnings", "expected"),
    [
        ((), DataQualityLevel.GOOD),
        (
            (RatioWarning(code=WarningCode.DERIVED_INPUT, concept="total_debt", message="m"),),
            DataQualityLevel.DERIVED_INPUTS,
        ),
        (
            (RatioWarning(code=WarningCode.MANUAL_INPUT, concept="total_debt", message="m"),),
            DataQualityLevel.MANUALLY_ADJUSTED,
        ),
        (
            (
                RatioWarning(
                    code=WarningCode.LOW_CONFIDENCE_INPUT, concept="total_debt", message="m"
                ),
            ),
            DataQualityLevel.LOW_CONFIDENCE,
        ),
    ],
)
def test_data_quality_propagates_from_ratio_warnings(
    warnings: tuple[RatioWarning, ...], expected: DataQualityLevel
) -> None:
    results = [
        result("debt_to_equity", "FY2023", 1.0),
        result("debt_to_equity", "FY2024", 1.1),
        result("debt_to_equity", "FY2025", 1.2, warnings=warnings),
    ]
    trend = compute_ratio_trend("debt_to_equity", results, _LOWER)
    assert trend.data_quality is expected


def test_low_confidence_beats_manual_and_derived_when_both_present() -> None:
    low_conf = RatioWarning(
        code=WarningCode.LOW_CONFIDENCE_INPUT, concept="total_debt", message="m"
    )
    derived = RatioWarning(code=WarningCode.DERIVED_INPUT, concept="total_debt", message="m")
    results = [
        result("debt_to_equity", "FY2024", 1.0, warnings=(derived,)),
        result("debt_to_equity", "FY2025", 1.1, warnings=(low_conf,)),
    ]
    trend = compute_ratio_trend("debt_to_equity", results, _LOWER)
    assert trend.data_quality is DataQualityLevel.LOW_CONFIDENCE


def test_zero_baseline_falls_back_to_absolute_epsilon() -> None:
    """When the window's earliest value is ~0, `percent_change` is undefined
    (mirrors `RatioChange`'s own convention) and direction falls back to
    comparing `absolute_change` against a tiny float-noise epsilon."""
    results = [
        result("net_profit_margin", "FY2023", 0.0),
        result("net_profit_margin", "FY2024", 0.03),
        result("net_profit_margin", "FY2025", 0.06),
    ]
    trend = compute_ratio_trend("net_profit_margin", results, _HIGHER)
    assert trend.percent_change is None
    assert trend.direction is TrendDirection.INCREASING


def test_zero_baseline_with_a_negligible_move_is_stable() -> None:
    results = [
        result("net_profit_margin", "FY2023", 0.0),
        result("net_profit_margin", "FY2024", 1e-8),
        result("net_profit_margin", "FY2025", 2e-8),
    ]
    trend = compute_ratio_trend("net_profit_margin", results, _HIGHER)
    assert trend.percent_change is None
    assert trend.direction is TrendDirection.STABLE


def test_unusual_movement_not_flagged_when_a_gap_sits_right_before_latest() -> None:
    """The latest period's own move must actually be in `changes` -- a gap
    immediately before it means there is no single-period move to judge."""
    results = [
        result("current_ratio", "FY2020", 1.00),
        result("current_ratio", "FY2021", 1.01),
        result("current_ratio", "FY2022", 1.02),
        result("current_ratio", "FY2023", 1.03),
        missing("current_ratio", "FY2024"),
        result("current_ratio", "FY2025", 5.00),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    assert trend.unusual_movement is False


def test_unusual_movement_with_identical_prior_deltas_flags_any_deviation() -> None:
    """When every prior delta is identical, MAD is 0 and the robust z-score
    is undefined -- any deviation from that perfectly flat pattern is by
    definition extreme."""
    results = [
        result("gross_margin", "FY2021", 0.40),
        result("gross_margin", "FY2022", 0.405),
        result("gross_margin", "FY2023", 0.410),
        result("gross_margin", "FY2024", 0.415),
        result("gross_margin", "FY2025", 0.60),
    ]
    trend = compute_ratio_trend("gross_margin", results, _HIGHER)
    assert trend.unusual_movement is True


def test_explain_omits_percent_change_when_its_sign_disagrees_with_absolute_change() -> None:
    """Found inspecting the real corpus (SandRidge FY2015): a negative
    baseline can make `percent_change`'s sign contradict `absolute_change`'s
    (matching `RatioChange.percent_change`'s own convention of dividing by
    the *signed* prior value). `direction` is still correctly `DECREASING`
    (taken from `absolute_change`), but the human-readable text must not
    print a positive percentage next to a negative absolute change."""
    results = [
        result("operating_margin", "FY2013", -0.0852),
        result("operating_margin", "FY2014", 0.3787),
        result("operating_margin", "FY2015", -6.0396),
    ]
    trend = compute_ratio_trend("operating_margin", results, _HIGHER)

    assert trend.direction is TrendDirection.DECREASING
    assert trend.absolute_change is not None and trend.absolute_change < 0
    assert trend.percent_change is not None and trend.percent_change > 0  # signs disagree

    explanation = trend.explain()
    assert "Change: -5.954" in explanation
    assert "%" not in explanation.split("Change:")[1].split("\n")[0]


def test_explain_shows_percent_change_when_signs_agree() -> None:
    results = [
        result("current_ratio", "FY2023", 1.00),
        result("current_ratio", "FY2024", 1.20),
        result("current_ratio", "FY2025", 1.50),
    ]
    trend = compute_ratio_trend("current_ratio", results, _HIGHER)
    explanation = trend.explain()
    assert "Change: +0.5" in explanation
    assert "%" in explanation.split("Change:")[1].split("\n")[0]


def test_out_of_order_input_is_sorted_before_analysis() -> None:
    """The engine must never trust the caller's ordering (see the module
    docstring's real-corpus example)."""
    scrambled = [
        result("current_ratio", "FY2025", 1.50),
        result("current_ratio", "FY2023", 1.00),
        result("current_ratio", "FY2024", 1.20),
    ]
    trend = compute_ratio_trend("current_ratio", scrambled, _HIGHER)
    assert [r.period_label for r in trend.results] == ["FY2023", "FY2024", "FY2025"]
    assert trend.direction is TrendDirection.INCREASING
    assert trend.absolute_change == pytest.approx(0.50)
