"""Tests for numeric-string normalisation (§10, §9)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from credit_risk_copilot.financials.numeric import (
    detect_scale,
    parse_numeric,
    render_candidates,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,250", Decimal("1250")),
        ("1,250.5", Decimal("1250.5")),
        ("$1,234", Decimal("1234")),
        ("0", Decimal("0")),
    ],
)
def test_plain_numbers_parse(text: str, expected: Decimal) -> None:
    assert parse_numeric(text).value == expected


def test_parentheses_mean_negative() -> None:
    result = parse_numeric("(1,250)")

    assert result.value == Decimal("-1250")
    assert result.is_negative_paren


@pytest.mark.parametrize("text", ["-", "—", "–", "N/A", "n/a", "NM", "nm"])
def test_ambiguous_markers_are_not_zero(text: str) -> None:
    """§10: a dash or N/A must never be silently read as 0."""
    result = parse_numeric(text)

    assert result.value is None
    assert result.is_blank_marker
    assert result.reason is not None


def test_a_row_label_is_not_a_number() -> None:
    """A label that lands in a numeric column must not parse as 0 either."""
    result = parse_numeric("Total assets")

    assert result.value is None
    assert not result.is_blank_marker


def test_empty_cell_is_not_a_number() -> None:
    result = parse_numeric("")

    assert result.value is None
    assert not result.is_blank_marker


class TestDetectScale:
    def test_millions_declaration(self) -> None:
        assert detect_scale("(In millions, except per share data)") == "millions"

    def test_thousands_declaration(self) -> None:
        assert detect_scale("$ in thousands") == "thousands"

    def test_no_declaration_is_unknown_not_units(self) -> None:
        """§9: absence of a stated scale must not be read as 'confirmed units'."""
        assert detect_scale(None) is None
        assert detect_scale("Apple Inc. | CONSOLIDATED BALANCE SHEETS") is None


class TestRenderCandidates:
    def test_generates_scaled_and_parenthesised_forms(self) -> None:
        candidates = render_candidates(-1250000000.0)

        assert "1,250.0" in candidates  # millions, one decimal
        assert "(1,250.0)" in candidates
        assert "-1,250.0" in candidates
        assert "1,250,000,000" in candidates  # raw units

    def test_positive_value_has_no_negative_forms(self) -> None:
        candidates = render_candidates(12400.0)

        assert "12,400" in candidates
        assert not any(c.startswith("(") or c.startswith("-") for c in candidates)
