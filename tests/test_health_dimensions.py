"""Tests for `health/dimensions.py` -- grouping ratio trends by dimension and
aggregating a dimension status from them (§5, §9, §26)."""

from __future__ import annotations

from credit_risk_copilot.health.dimensions import DIMENSIONS, dimension_status, group_by_dimension
from credit_risk_copilot.health.direction import RATIO_DIRECTIONS
from credit_risk_copilot.health.models import DimensionStatus
from credit_risk_copilot.health.trend import compute_ratio_trend
from tests._health_helpers import result


def _trend(ratio_id: str, values: list[float]):
    periods = ["FY2023", "FY2024", "FY2025"][: len(values)]
    results = [result(ratio_id, p, v) for p, v in zip(periods, values, strict=True)]
    return compute_ratio_trend(ratio_id, results, RATIO_DIRECTIONS[ratio_id])


def test_dimensions_are_exactly_the_ratio_catalog_categories() -> None:
    assert DIMENSIONS == ("liquidity", "leverage", "profitability", "coverage", "cash_flow")


def test_all_deteriorating_is_deteriorating() -> None:
    trends = [_trend("debt_to_equity", [1.0, 1.3, 1.8]), _trend("debt_to_assets", [0.2, 0.3, 0.4])]
    assert dimension_status(trends) is DimensionStatus.DETERIORATING


def test_all_improving_is_improving() -> None:
    trends = [_trend("current_ratio", [1.0, 1.3, 1.8]), _trend("quick_ratio", [0.5, 0.8, 1.2])]
    assert dimension_status(trends) is DimensionStatus.IMPROVING


def test_all_stable_is_stable() -> None:
    trends = [_trend("current_ratio", [1.0, 1.01, 1.02]), _trend("quick_ratio", [0.5, 0.51, 0.5])]
    assert dimension_status(trends) is DimensionStatus.STABLE


def test_one_deteriorating_one_improving_is_mixed() -> None:
    """Never silently netted into one direction (§26)."""
    trends = [_trend("current_ratio", [1.8, 1.3, 1.0]), _trend("quick_ratio", [0.5, 0.8, 1.2])]
    assert dimension_status(trends) is DimensionStatus.MIXED


def test_no_conclusive_ratio_is_insufficient_data() -> None:
    trends = [_trend("current_ratio", [1.0, 1.1]), _trend("quick_ratio", [0.5])]
    assert dimension_status(trends) is DimensionStatus.INSUFFICIENT_DATA


def test_empty_dimension_is_insufficient_data() -> None:
    assert dimension_status([]) is DimensionStatus.INSUFFICIENT_DATA


def test_group_by_dimension_buckets_by_category() -> None:
    trends = [
        _trend("current_ratio", [1.0, 1.1, 1.3]),
        _trend("debt_to_equity", [1.0, 1.1, 1.3]),
        _trend("interest_coverage", [5.0, 4.0, 3.0]),
    ]
    grouped = group_by_dimension(trends)
    assert set(grouped) == {"liquidity", "leverage", "coverage"}
    assert grouped["liquidity"] == (trends[0],)
    assert grouped["coverage"] == (trends[2],)


def test_group_by_dimension_omits_dimensions_with_no_trends() -> None:
    trends = [_trend("current_ratio", [1.0, 1.1, 1.3])]
    grouped = group_by_dimension(trends)
    assert "cash_flow" not in grouped
    assert "profitability" not in grouped
