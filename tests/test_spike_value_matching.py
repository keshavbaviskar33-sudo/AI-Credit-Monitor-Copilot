"""Tests for the R-19 spike's value matching.

The spike decides whether an XBRL reference value appears in an extracted
cell, so a gap here shows up as an *extraction* failure that never happened.
That is not hypothetical: the first run scored Peabody's 2015 10-K at 2/48
because the matcher only produced whole-unit renderings and that filing prints
in millions with one decimal ("14,133.4"). These tests exist so the metric
cannot quietly mis-measure the thing it is there to measure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "table_extraction_spike",
    Path(__file__).resolve().parents[1] / "scripts" / "table_extraction_spike.py",
)
assert _SPEC is not None and _SPEC.loader is not None
spike = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(spike)

candidates = spike._candidate_strings


def test_whole_units_are_rendered_with_comma_grouping() -> None:
    assert "1,234" in candidates(1234.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (364_980_000_000, "364,980"),  # Apple: reports in millions, no decimals
        (14_133_400_000, "14,133.4"),  # Peabody: millions, one decimal
        (916_900_000, "916.9"),
        (1_378_000_000, "1,378.0"),
    ],
)
def test_scaled_presentations_are_matched(value: int, expected: str) -> None:
    """A filing reports in units, thousands or millions, and may carry decimals."""
    assert expected in candidates(float(value))


def test_the_peabody_regression_specifically() -> None:
    """Total assets of $14,133,400,000 printed as "14,133.4" in a millions table."""
    assert "14,133.4" in candidates(14_133_400_000.0)


def test_negatives_match_accounting_conventions() -> None:
    rendered = candidates(-1_234_000.0)

    assert "(1,234,000)" in rendered
    assert "-1,234,000" in rendered
    # Deliberately generous: statements often carry the sign in the row label.
    assert "1,234,000" in rendered


def test_negative_decimal_presentations_are_matched() -> None:
    assert "(1,234.5)" in candidates(-1_234_500_000.0)


def test_scales_that_would_lose_digits_are_not_offered() -> None:
    """1,234 in millions is 0.001234 -- no filing prints that, and offering it
    would invite coincidental matches against unrelated cells."""
    rendered = candidates(1234.0)

    assert not any(r.startswith("0.") for r in rendered)


def test_zero_is_handled() -> None:
    assert "0" in candidates(0.0)
