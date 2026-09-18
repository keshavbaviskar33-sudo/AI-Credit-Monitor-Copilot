"""Tests for `health/direction.py` -- per-ratio economic-direction metadata
and the `TrendDirection` -> `EconomicDirection` interpretation (§8)."""

from __future__ import annotations

import pytest

from credit_risk_copilot.health.direction import RATIO_DIRECTIONS, economic_direction
from credit_risk_copilot.health.models import EconomicDirection, RatioDirection, TrendDirection
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS

_LEVERAGE_RATIOS = {"debt_to_equity", "debt_to_assets", "liabilities_to_assets"}


def test_every_ratio_in_the_catalog_has_a_direction() -> None:
    """A ratio catalog change (Phase 6) must never silently leave a ratio
    uninterpretable in Phase 7."""
    catalog_ids = {d.ratio_id for d in RATIO_DEFINITIONS}
    assert set(RATIO_DIRECTIONS) == catalog_ids


def test_only_the_three_leverage_ratios_are_lower_is_stronger() -> None:
    lower = {
        ratio_id
        for ratio_id, direction in RATIO_DIRECTIONS.items()
        if direction is RatioDirection.LOWER_IS_STRONGER
    }
    assert lower == _LEVERAGE_RATIOS


@pytest.mark.parametrize(
    ("direction", "ratio_direction", "expected"),
    [
        (TrendDirection.INCREASING, RatioDirection.HIGHER_IS_STRONGER, EconomicDirection.IMPROVING),
        (
            TrendDirection.DECREASING,
            RatioDirection.HIGHER_IS_STRONGER,
            EconomicDirection.DETERIORATING,
        ),
        (
            TrendDirection.INCREASING,
            RatioDirection.LOWER_IS_STRONGER,
            EconomicDirection.DETERIORATING,
        ),
        (TrendDirection.DECREASING, RatioDirection.LOWER_IS_STRONGER, EconomicDirection.IMPROVING),
    ],
)
def test_increasing_decreasing_depend_on_ratio_direction(
    direction: TrendDirection, ratio_direction: RatioDirection, expected: EconomicDirection
) -> None:
    assert economic_direction(direction, ratio_direction) is expected


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        (TrendDirection.STABLE, EconomicDirection.STABLE),
        (TrendDirection.NOT_MEANINGFUL, EconomicDirection.NOT_MEANINGFUL),
        (TrendDirection.INSUFFICIENT_DATA, EconomicDirection.INSUFFICIENT_DATA),
        (TrendDirection.DISCONTINUOUS_HISTORY, EconomicDirection.DISCONTINUOUS_HISTORY),
    ],
)
def test_directionless_states_are_the_same_regardless_of_ratio_direction(
    direction: TrendDirection, expected: EconomicDirection
) -> None:
    assert economic_direction(direction, RatioDirection.HIGHER_IS_STRONGER) is expected
    assert economic_direction(direction, RatioDirection.LOWER_IS_STRONGER) is expected
