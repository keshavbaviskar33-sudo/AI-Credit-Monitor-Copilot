"""The Phase 7 analysis window (D-024).

`analyze_financial_health` computes a direction as a first-to-last comparison
across the analyzed span, so *which* periods are in that span decides what the
report says. These tests pin the semantics the decision record claims: the
window counts period labels (not calculated values), is taken over the union
across ratios, defaults to a value that is a no-op for short histories, and
is recorded on the report.
"""

from __future__ import annotations

from credit_risk_copilot.health import analyze_financial_health
from credit_risk_copilot.health.models import DimensionStatus, TrendDirection
from credit_risk_copilot.health.thresholds import DEFAULT_ANALYSIS_WINDOW
from tests._health_helpers import missing, result


def _long_declining_history() -> dict[str, list]:
    """A ratio that fell steeply long ago and has been flat recently.

    FY2010-FY2015 halve the value; FY2016-FY2020 hold it steady. A window
    that reaches back to FY2010 sees a collapse; a 5-period window sees a
    stable ratio. Both readings are arithmetically correct -- the window is
    what decides which question is being answered.
    """
    values = {
        "FY2010": 4.00,
        "FY2011": 3.60,
        "FY2012": 3.10,
        "FY2013": 2.60,
        "FY2014": 2.20,
        "FY2015": 2.00,
        "FY2016": 2.00,
        "FY2017": 2.01,
        "FY2018": 2.00,
        "FY2019": 2.00,
        "FY2020": 2.00,
    }
    return {"current_ratio": [result("current_ratio", p, v) for p, v in values.items()]}


def test_default_window_ignores_a_collapse_outside_it() -> None:
    report = analyze_financial_health("Test Co", _long_declining_history())

    trend = report.trend("current_ratio")
    assert trend is not None
    assert trend.direction is TrendDirection.STABLE
    assert report.periods_considered == ("FY2016", "FY2017", "FY2018", "FY2019", "FY2020")


def test_unbounded_window_sees_the_whole_history() -> None:
    report = analyze_financial_health("Test Co", _long_declining_history(), analysis_window=None)

    trend = report.trend("current_ratio")
    assert trend is not None
    assert trend.direction is TrendDirection.DECREASING
    assert len(report.periods_considered) == 11
    assert report.dimensions["liquidity"].status is DimensionStatus.DETERIORATING


def test_window_is_a_no_op_when_history_is_shorter_than_it() -> None:
    """Every pre-Phase-8 caller supplies 2-4 periods from one filing, so the
    default must not change any of their results."""
    history = {
        "current_ratio": [
            result("current_ratio", "FY2023", 2.0),
            result("current_ratio", "FY2024", 1.5),
            result("current_ratio", "FY2025", 1.0),
        ]
    }

    default = analyze_financial_health("Test Co", history)
    unbounded = analyze_financial_health("Test Co", history, analysis_window=None)

    assert default.periods_considered == unbounded.periods_considered
    assert default.dimensions["liquidity"].status == unbounded.dimensions["liquidity"].status
    assert len(default.signals) == len(unbounded.signals)


def test_window_counts_periods_not_calculated_values_so_a_gap_stays_a_gap() -> None:
    """Taking the last N *calculated* periods would bridge FY2023 silently.
    Taking the last N *labels* keeps the gap visible."""
    history = {
        "current_ratio": [
            result("current_ratio", "FY2020", 3.0),
            result("current_ratio", "FY2021", 2.8),
            result("current_ratio", "FY2022", 2.6),
            missing("current_ratio", "FY2023"),
            result("current_ratio", "FY2024", 1.4),
            result("current_ratio", "FY2025", 1.2),
        ]
    }

    report = analyze_financial_health("Test Co", history, analysis_window=4)

    trend = report.trend("current_ratio")
    assert trend is not None
    assert report.periods_considered == ("FY2022", "FY2023", "FY2024", "FY2025")
    assert trend.direction is TrendDirection.DISCONTINUOUS_HISTORY
    assert trend.gap_periods == ("FY2023",)


def test_window_is_taken_over_the_union_of_periods_across_ratios() -> None:
    """A sparsely covered ratio must not reach further back than its
    neighbours -- every ratio in one report spans the same window."""
    history = {
        "current_ratio": [result("current_ratio", f"FY{y}", 2.0) for y in range(2016, 2026)],
        # Only two periods, both old: they sit outside a 5-period window
        # taken over the union (FY2021-FY2025), so this ratio contributes
        # nothing rather than trending across FY2017-FY2018.
        "quick_ratio": [
            result("quick_ratio", "FY2017", 1.0),
            result("quick_ratio", "FY2018", 0.4),
        ],
    }

    report = analyze_financial_health("Test Co", history, analysis_window=5)

    quick = report.trend("quick_ratio")
    assert quick is not None
    assert report.periods_considered == ("FY2021", "FY2022", "FY2023", "FY2024", "FY2025")
    assert quick.periods_available == 0
    assert quick.direction is TrendDirection.INSUFFICIENT_DATA


def test_analysis_window_is_recorded_on_the_report() -> None:
    history = _long_declining_history()

    assert analyze_financial_health("T", history).analysis_window == DEFAULT_ANALYSIS_WINDOW
    assert analyze_financial_health("T", history, analysis_window=None).analysis_window is None
    assert analyze_financial_health("T", history, analysis_window=7).analysis_window == 7
