"""Tests for the two-pass resolution engine (direct tags, then derivation).

Uses a hand-built `companyfacts`-shaped fixture rather than the golden set
(gitignored, not guaranteed present in a fresh clone) -- same convention as
`tests/test_sec_edgar.py`'s fake filing index. `scripts/evaluate_canonicalization.py`
is where the real golden set is exercised (QM-01).
"""

from __future__ import annotations

from credit_risk_copilot.financials.models import Confidence, FactStatus, Origin
from credit_risk_copilot.financials.resolver import resolve_filing

ACCN = "0001234567-25-000001"


def _entry(val: float, *, end: str, start: str | None = None, **overrides: object) -> dict:
    entry = {
        "val": val,
        "end": end,
        "fy": 2025,
        "fp": "FY",
        "form": "10-K",
        "filed": "2025-02-01",
        "accn": ACCN,
    }
    if start is not None:
        entry["start"] = start
    entry.update(overrides)
    return entry


#: One filing, two fiscal years (2025 primary, 2024 comparative), built to
#: exercise: a direct tag, a fallback tag, a derivation, a derivation with a
#: fallback rule, a conflicting fallback chain, and a concept with nothing
#: at all (MISSING).
COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "Assets": {
                "units": {"USD": [_entry(1000, end="2025-12-31"), _entry(900, end="2024-12-31")]}
            },
            "StockholdersEquity": {
                "units": {"USD": [_entry(400, end="2025-12-31"), _entry(350, end="2024-12-31")]}
            },
            # Liabilities is deliberately absent -- forces the derivation.
            "AssetsCurrent": {"units": {"USD": [_entry(300, end="2025-12-31")]}},
            "LiabilitiesCurrent": {"units": {"USD": [_entry(200, end="2025-12-31")]}},
            # Revenues (the priority tag) is absent; only the ASC 606 fallback
            # is tagged -- the exact gap data_dictionary.md §6.1 measured.
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [_entry(500, end="2025-12-31", start="2025-01-01")]}
            },
            "CostOfGoodsAndServicesSold": {
                "units": {"USD": [_entry(300, end="2025-12-31", start="2025-01-01")]}
            },
            "OperatingIncomeLoss": {
                "units": {"USD": [_entry(150, end="2025-12-31", start="2025-01-01")]}
            },
            # FY2024: pretax income is tagged, so EBIT derives via rule 1.
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": {
                "units": {"USD": [_entry(130, end="2024-12-31", start="2024-01-01")]}
            },
            "InterestExpense": {
                "units": {
                    "USD": [
                        _entry(25, end="2025-12-31", start="2025-01-01"),
                        _entry(20, end="2024-12-31", start="2024-01-01"),
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {"USD": [_entry(100, end="2025-12-31", start="2025-01-01")]}
            },
            "CashAndCashEquivalentsAtCarryingValue": {
                "units": {"USD": [_entry(50, end="2025-12-31")]}
            },
            "LongTermDebtCurrent": {"units": {"USD": [_entry(50, end="2025-12-31")]}},
            "LongTermDebtNoncurrent": {"units": {"USD": [_entry(250, end="2025-12-31")]}},
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": [_entry(80, end="2025-12-31", start="2025-01-01")]}
            },
            # Two capex tags declared ALTERNATES, both present and genuinely
            # disagreeing -- must surface as CONFLICTING, not be picked.
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {"USD": [_entry(20, end="2025-12-31", start="2025-01-01")]}
            },
            "PaymentsForCapitalImprovements": {
                "units": {"USD": [_entry(999, end="2025-12-31", start="2025-01-01")]}
            },
        }
    }
}


def _resolve():
    return resolve_filing(
        COMPANY_FACTS,
        cik=1,
        company="Test Co",
        accession=ACCN,
        form="10-K",
        filed="2025-02-01",
        period_end="2025-12-31",
    )


def test_direct_tag_resolves_with_high_confidence() -> None:
    filing = _resolve()
    assets = filing.get("total_assets", "FY2025")

    assert assets is not None
    assert assets.status is FactStatus.FOUND
    assert assets.value == 1000
    assert assets.confidence is Confidence.HIGH
    assert assets.provenance[0].concept == "Assets"


def test_fallback_tag_resolves_revenue_when_the_priority_tag_is_dead() -> None:
    """The concrete R-11 case: `Revenues` absent, ASC 606 tag present."""
    filing = _resolve()
    revenue = filing.get("revenue", "FY2025")

    assert revenue is not None
    assert revenue.status is FactStatus.FOUND
    assert revenue.value == 500
    assert revenue.confidence is Confidence.MEDIUM  # not the first-priority tag
    assert revenue.provenance[0].concept == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_liabilities_is_derived_when_no_filer_tags_the_total() -> None:
    filing = _resolve()
    liabilities = filing.get("total_liabilities", "FY2025")

    assert liabilities is not None
    assert liabilities.status is FactStatus.DERIVED
    assert liabilities.origin is Origin.DERIVED
    assert liabilities.value == 600  # 1000 - 400
    assert liabilities.formula == "total_assets - total_equity"


def test_derived_fact_carries_its_inputs_provenance() -> None:
    """A derived fact must not look evidence-free just because it has no
    XBRL tag of its own (§15)."""
    filing = _resolve()
    liabilities = filing.get("total_liabilities", "FY2025")

    assert liabilities is not None
    assert liabilities.derived_from == ("total_assets", "total_equity")
    assert {p.concept for p in liabilities.provenance} == {"Assets", "StockholdersEquity"}


def test_total_debt_derives_as_the_sum_of_its_two_components() -> None:
    filing = _resolve()
    debt = filing.get("total_debt", "FY2025")

    assert debt is not None
    assert debt.status is FactStatus.DERIVED
    assert debt.value == 300  # 50 + 250


def test_gross_profit_derives_from_revenue_minus_cogs() -> None:
    filing = _resolve()
    gross_profit = filing.get("gross_profit", "FY2025")

    assert gross_profit is not None
    assert gross_profit.status is FactStatus.DERIVED
    assert gross_profit.value == 200  # 500 - 300


def test_ebit_prefers_the_pretax_plus_interest_rule_when_available() -> None:
    filing = _resolve()
    ebit_2024 = filing.get("ebit", "FY2024")

    assert ebit_2024 is not None
    assert ebit_2024.status is FactStatus.DERIVED
    assert ebit_2024.value == 150  # 130 + 20
    assert ebit_2024.formula.startswith("pretax_income")


def test_ebit_falls_back_to_operating_income_when_pretax_is_missing() -> None:
    filing = _resolve()
    ebit_2025 = filing.get("ebit", "FY2025")

    assert ebit_2025 is not None
    assert ebit_2025.status is FactStatus.DERIVED
    assert ebit_2025.value == 150  # operating_income substitute
    assert "operating_income" in ebit_2025.formula


def test_two_disagreeing_tags_surface_as_conflicting_not_a_silent_pick() -> None:
    filing = _resolve()
    capex = filing.get("capital_expenditures", "FY2025")

    assert capex is not None
    assert capex.status is FactStatus.CONFLICTING
    assert capex.value is None
    assert {c.value for c in capex.candidates} == {20, 999}


def test_a_conflicting_input_propagates_as_missing_not_a_guess() -> None:
    """free_cash_flow needs capital_expenditures, which is CONFLICTING here --
    it must not derive from one of the disputed candidates."""
    filing = _resolve()
    fcf = filing.get("free_cash_flow", "FY2025")

    assert fcf is not None
    assert fcf.status is FactStatus.MISSING
    assert fcf.value is None


def test_a_quarterly_footnote_under_the_same_tag_does_not_corrupt_the_annual_figure() -> None:
    """Regression for a real bug found evaluating this against the golden
    set: iHeartMedia's 2016 10-K tags `Revenues` for each of 2015 Q1-Q4 *and*
    full-year 2015 under one concept and accession (a "selected quarterly
    financial data" footnote). An earlier version keyed a period only by
    `end.year`, so a quarter's revenue silently landed in the same bucket as
    the annual figure -- `revenue` for "FY2015" must resolve to the full-year
    value only.
    """
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _entry(1_344_564_000, end="2015-03-31", start="2015-01-01"),  # Q1
                            _entry(1_599_859_000, end="2015-06-30", start="2015-04-01"),  # Q2
                            _entry(1_579_514_000, end="2015-09-30", start="2015-07-01"),  # Q3
                            _entry(1_717_579_000, end="2015-12-31", start="2015-10-01"),  # Q4
                            _entry(6_241_516_000, end="2015-12-31", start="2015-01-01"),  # FY
                        ]
                    }
                }
            }
        }
    }

    filing = resolve_filing(
        facts,
        cik=1,
        company="Test Co",
        accession=ACCN,
        form="10-K",
        filed="2016-02-23",
        period_end="2015-12-31",
    )
    revenue = filing.get("revenue", "FY2015")

    assert revenue is not None
    assert revenue.status is FactStatus.FOUND
    assert revenue.value == 6_241_516_000


def test_missing_concept_states_a_reason_instead_of_zero() -> None:
    filing = _resolve()
    interest_2025_only_year_without_tag = filing.get("accounts_receivable", "FY2025")

    assert interest_2025_only_year_without_tag is not None
    assert interest_2025_only_year_without_tag.status is FactStatus.MISSING
    assert interest_2025_only_year_without_tag.value is None
    assert interest_2025_only_year_without_tag.reason is not None
    assert "No sufficiently reliable source found" in interest_2025_only_year_without_tag.reason


def test_filing_carries_its_own_declared_fiscal_context() -> None:
    filing = _resolve()

    assert filing.fiscal_year == 2025
    assert filing.fiscal_period == "FY"


def test_completeness_reflects_resolved_vs_missing() -> None:
    filing = _resolve()

    assert 0.0 < filing.completeness < 1.0
