"""Structural tests on the ratio catalog itself, and small invariant/property
checks on the core arithmetic (§23) -- kept as plain parametrised tests
rather than pulling in `hypothesis`, which is not already a project
dependency and would be adopted for one module's sake (§23's own warning
against tooling added merely for appearance)."""

from __future__ import annotations

from datetime import date

import pytest

from credit_risk_copilot.financials.models import (
    CanonicalFact,
    Confidence,
    FactStatus,
    Origin,
    Period,
    PeriodType,
    StatementType,
)
from credit_risk_copilot.ratios.engine import calculate_ratio
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS, RATIOS_BY_ID

_KNOWN_CATEGORIES = {"liquidity", "leverage", "profitability", "coverage", "cash_flow"}
_KNOWN_UNITS = {"x", "%"}


def test_ratio_ids_are_unique() -> None:
    ids = [d.ratio_id for d in RATIO_DEFINITIONS]
    assert len(ids) == len(set(ids))


def test_every_ratio_has_a_known_category_and_unit() -> None:
    for d in RATIO_DEFINITIONS:
        assert d.category in _KNOWN_CATEGORIES, d.ratio_id
        assert d.unit in _KNOWN_UNITS, d.ratio_id


def test_denominator_concept_is_always_one_of_the_declared_inputs() -> None:
    for d in RATIO_DEFINITIONS:
        assert d.denominator_concept in d.inputs, d.ratio_id


def test_every_ratio_has_a_nonempty_rationale() -> None:
    for d in RATIO_DEFINITIONS:
        assert d.rationale.strip(), f"{d.ratio_id} has no documented rationale"


def test_registry_lookup_is_consistent_with_the_tuple() -> None:
    assert set(RATIOS_BY_ID) == {d.ratio_id for d in RATIO_DEFINITIONS}
    for ratio_id, definition in RATIOS_BY_ID.items():
        assert definition.ratio_id == ratio_id


def test_compute_only_reads_its_declared_inputs() -> None:
    """A compute lambda that reaches for a concept not in `inputs` would be
    an invisible bug -- this proves each one only needs exactly its declared
    concepts by calling it with nothing else available."""
    for d in RATIO_DEFINITIONS:
        values = dict.fromkeys(d.inputs, 100.0)
        d.compute(values)  # raises KeyError if it reaches outside `inputs`


# --- Invariant / property checks on the core arithmetic (§23) ------------------

_INSTANT = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))
_DURATION = Period(period_type=PeriodType.DURATION, start=date(2025, 1, 1), end=date(2025, 12, 31))
_INSTANT_CONCEPTS = {
    "cash",
    "accounts_receivable",
    "current_assets",
    "total_assets",
    "current_liabilities",
    "total_debt",
    "shareholders_equity",
}


def _fact(concept: str, value: float) -> CanonicalFact:
    period = _INSTANT if concept in _INSTANT_CONCEPTS else _DURATION
    return CanonicalFact(
        concept=concept,
        statement=StatementType.BALANCE_SHEET,
        period=period,
        value=value,
        status=FactStatus.FOUND,
        confidence=Confidence.HIGH,
        origin=Origin.REPORTED,
    )


@pytest.mark.parametrize("multiplier", [1, 2, 3, 10])
def test_current_ratio_scales_linearly_with_the_numerator(multiplier: float) -> None:
    """If current assets = k * current liabilities, current ratio = k."""
    liabilities = 1000.0
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", multiplier * liabilities),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", liabilities),
    }
    result = calculate_ratio(
        lambda c, p: facts.get((c, p)), RATIOS_BY_ID["current_ratio"], "FY2025"
    )
    assert result.value == pytest.approx(multiplier)


@pytest.mark.parametrize(
    "assets,liabilities", [(1000, 500), (500, 1000), (700, 700), (1, 1_000_000)]
)
def test_debt_to_assets_and_liabilities_to_assets_are_bounded_by_construction(
    assets: float, liabilities: float
) -> None:
    """total_debt <= total_liabilities is not enforced by this schema, but
    when it holds, debt_to_assets must not exceed liabilities_to_assets --
    both share the same denominator, so the ordering is a pure arithmetic
    fact about the numerators."""
    total_assets = assets + liabilities  # ensures a positive, nonzero denominator
    debt = min(liabilities, assets)  # a debt figure guaranteed <= liabilities
    facts = {
        ("total_debt", "FY2025"): _fact("total_debt", debt),
        ("total_liabilities", "FY2025"): _fact("total_liabilities", liabilities),
        ("total_assets", "FY2025"): _fact("total_assets", total_assets),
    }
    get_fact = lambda c, p: facts.get((c, p))  # noqa: E731
    debt_to_assets = calculate_ratio(get_fact, RATIOS_BY_ID["debt_to_assets"], "FY2025")
    liabilities_to_assets = calculate_ratio(
        get_fact, RATIOS_BY_ID["liabilities_to_assets"], "FY2025"
    )

    assert debt_to_assets.value is not None and liabilities_to_assets.value is not None
    assert debt_to_assets.value <= liabilities_to_assets.value + 1e-9


def test_interest_coverage_doubles_when_ebit_doubles_at_fixed_interest_expense() -> None:
    interest_expense = 100.0
    facts_low = {
        ("ebit", "FY2025"): _fact("ebit", 200.0),
        ("interest_expense", "FY2025"): _fact("interest_expense", interest_expense),
    }
    facts_high = {
        ("ebit", "FY2025"): _fact("ebit", 400.0),
        ("interest_expense", "FY2025"): _fact("interest_expense", interest_expense),
    }
    low = calculate_ratio(
        lambda c, p: facts_low.get((c, p)), RATIOS_BY_ID["interest_coverage"], "FY2025"
    )
    high = calculate_ratio(
        lambda c, p: facts_high.get((c, p)), RATIOS_BY_ID["interest_coverage"], "FY2025"
    )

    assert high.value == pytest.approx(2 * low.value)
