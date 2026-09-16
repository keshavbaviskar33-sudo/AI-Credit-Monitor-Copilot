"""Regression tests for the Phase 5 audit's findings.

Each test reproduces a failure the audit found by running the resolver
against the golden set, using that filing's real reported figures. These are
the plausible-but-wrong financial values that pass type checks and look
reasonable in a ratio: wrong equity scope, a debt component read as the total,
a validation that confirms a value with the identity it was derived from.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from credit_risk_copilot.financials.models import (
    CanonicalFact,
    CanonicalFilingFacts,
    Confidence,
    FactStatus,
    Origin,
    Period,
    PeriodType,
    StatementType,
)
from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.financials.validation import run_validations

ACCN = "0000000000-26-000001"
END = "2025-12-31"


def _instant(val: float, unit: str = "USD") -> tuple[str, dict[str, Any]]:
    return unit, {"end": END, "val": val, "accn": ACCN, "fy": 2025, "fp": "FY", "form": "10-K"}


def _filing(tags: dict[str, list[tuple[str, dict[str, Any]]]]) -> CanonicalFilingFacts:
    usgaap: dict[str, Any] = {}
    for tag, entries in tags.items():
        units: dict[str, list[dict[str, Any]]] = {}
        for unit, entry in entries:
            units.setdefault(unit, []).append(entry)
        usgaap[tag] = {"units": units}
    return resolve_filing(
        {"facts": {"us-gaap": usgaap}},
        cik=1,
        company="Audit Co",
        accession=ACCN,
        form="10-K",
        filed="2026-02-01",
        period_end=END,
    )


# --- Equity scope and the liabilities derivation ---------------------------


def test_derived_liabilities_use_total_equity_not_parent_equity() -> None:
    """Tesla FY2025. Deriving liabilities as assets minus *parent* equity
    overstates them by the noncontrolling interest: 55,669M instead of the
    54,941M Tesla reports. The correct identity uses total equity."""
    filing = _filing(
        {
            "Assets": [_instant(137_806e6)],
            "StockholdersEquity": [_instant(82_137e6)],
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
                _instant(82_807e6)
            ],
            "MinorityInterest": [_instant(670e6)],
        }
    )
    liabilities = filing.get("total_liabilities", "FY2025")

    assert liabilities is not None
    assert liabilities.status is FactStatus.DERIVED
    assert liabilities.value == 137_806e6 - 82_807e6  # 54,999M, not 55,669M
    assert liabilities.formula == "total_assets - total_equity"


def test_parent_and_total_equity_are_separate_facts_not_a_conflict() -> None:
    """They used to share one fallback chain, which reported 9 false
    conflicts across the golden set and left debt/equity uncomputable."""
    filing = _filing(
        {
            "StockholdersEquity": [_instant(82_137e6)],
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
                _instant(82_807e6)
            ],
        }
    )
    parent = filing.get("shareholders_equity", "FY2025")
    total = filing.get("total_equity", "FY2025")

    assert parent is not None and parent.status is FactStatus.FOUND
    assert total is not None and total.status is FactStatus.FOUND
    assert parent.value == 82_137e6
    assert total.value == 82_807e6


def test_total_equity_rebuilds_from_parent_plus_nci_when_untagged() -> None:
    filing = _filing(
        {"StockholdersEquity": [_instant(1_000e6)], "MinorityInterest": [_instant(50e6)]}
    )
    total = filing.get("total_equity", "FY2025")

    assert total is not None
    assert total.value == 1_050e6
    assert total.derived_from == ("shareholders_equity", "noncontrolling_interest")


def test_derivation_chains_resolve_regardless_of_declaration_order() -> None:
    """`total_liabilities` needs `total_equity`, which is itself derived and
    declared *after* it. A single derivation pass left this MISSING."""
    filing = _filing(
        {
            "Assets": [_instant(1_000e6)],
            "StockholdersEquity": [_instant(300e6)],
            "MinorityInterest": [_instant(20e6)],
        }
    )
    liabilities = filing.get("total_liabilities", "FY2025")

    assert liabilities is not None
    assert liabilities.status is FactStatus.DERIVED
    assert liabilities.value == 680e6  # 1,000 - (300 + 20)


# --- Debt: components are summed, not picked ------------------------------


def test_short_term_debt_sums_its_components() -> None:
    """Walmart FY2024: current portion of LTD 3,542M plus short-term
    borrowings 6,596M. Picking the first tag reported 3,542M as the whole."""
    filing = _filing(
        {
            "LongTermDebtCurrent": [_instant(3_542e6)],
            "ShortTermBorrowings": [_instant(6_596e6)],
        }
    )
    debt = filing.get("short_term_debt", "FY2025")

    assert debt is not None
    assert debt.value == 10_138e6
    assert debt.origin is Origin.DERIVED
    assert {p.concept for p in debt.provenance} == {"LongTermDebtCurrent", "ShortTermBorrowings"}


def test_a_zero_component_does_not_hide_the_other() -> None:
    """Pyxus FY2019: current LTD is 0 while short-term borrowings are 429M."""
    filing = _filing(
        {"LongTermDebtCurrent": [_instant(0)], "ShortTermBorrowings": [_instant(429e6)]}
    )
    debt = filing.get("short_term_debt", "FY2025")

    assert debt is not None
    assert debt.value == 429e6


def test_the_filers_own_current_debt_total_wins_over_summing() -> None:
    """Pfizer FY2025 tags DebtCurrent 3,154M alongside a 2,997M component --
    the filer's total is authoritative; summing would double-count."""
    filing = _filing(
        {"DebtCurrent": [_instant(3_154e6)], "LongTermDebtCurrent": [_instant(2_997e6)]}
    )
    debt = filing.get("short_term_debt", "FY2025")

    assert debt is not None
    assert debt.status is FactStatus.FOUND
    assert debt.value == 3_154e6


def test_noncurrent_long_term_debt_is_preferred_over_the_broader_total() -> None:
    """Apple FY2025: LongTermDebt 90,678M = noncurrent 78,328M + current
    12,350M. The pair is not a contradiction, and total_debt must not
    double-count the current portion."""
    filing = _filing(
        {
            "LongTermDebt": [_instant(90_678e6)],
            "LongTermDebtNoncurrent": [_instant(78_328e6)],
            "LongTermDebtCurrent": [_instant(12_350e6)],
        }
    )
    long_term = filing.get("long_term_debt", "FY2025")
    total = filing.get("total_debt", "FY2025")

    assert long_term is not None
    assert long_term.status is FactStatus.FOUND
    assert long_term.value == 78_328e6
    assert [c.value for c in long_term.candidates] == [90_678e6]
    assert total is not None
    assert total.value == 90_678e6  # 12,350 + 78,328: no double count


# --- Scope differences are not conflicts ------------------------------------


def test_parent_and_consolidated_net_income_keep_the_preferred_value() -> None:
    """iHeartMedia FY2015: NetIncomeLoss -754.6M vs ProfitLoss -737.5M,
    differing by the noncontrolling interest. 13 such values were discarded."""
    filing = _filing(
        {
            "NetIncomeLoss": [("USD", {**_instant(-754_621e3)[1], "start": "2025-01-01"})],
            "ProfitLoss": [("USD", {**_instant(-737_490e3)[1], "start": "2025-01-01"})],
        }
    )
    net_income = filing.get("net_income", "FY2025")

    assert net_income is not None
    assert net_income.status is FactStatus.FOUND
    assert net_income.value == -754_621e3
    assert net_income.confidence is Confidence.MEDIUM
    assert [c.value for c in net_income.candidates] == [-737_490e3]
    assert net_income.reason is not None


# --- Units -------------------------------------------------------------------


def test_a_non_usd_fact_is_never_a_candidate() -> None:
    """A concept reported in two currencies must not have the foreign one
    picked (or flagged as conflicting) -- it is simply out of scope."""
    filing = _filing({"Assets": [_instant(900e6, unit="EUR"), _instant(1_000e6)]})
    assets = filing.get("total_assets", "FY2025")

    assert assets is not None
    assert assets.status is FactStatus.FOUND
    assert assets.value == 1_000e6
    assert assets.currency == "USD"


def test_a_concept_reported_only_in_another_unit_is_missing_not_misread() -> None:
    filing = _filing({"Assets": [_instant(1_000e6)], "Liabilities": [_instant(5, unit="shares")]})
    liabilities = filing.get("total_liabilities", "FY2025")

    assert liabilities is not None
    assert liabilities.value != 5


# --- Validation must not confirm a value with its own derivation -------------


def test_balance_sheet_check_is_not_reported_for_derived_liabilities() -> None:
    """11 of the original 19 'passes' were this: liabilities derived as
    assets - equity, then 'validated' against assets = liabilities + equity,
    with a difference of exactly zero every time."""
    filing = _filing({"Assets": [_instant(1_000e6)], "StockholdersEquity": [_instant(400e6)]})

    assert not [v for v in filing.validations if v.rule == "balance_sheet_equation"]


def test_balance_sheet_check_runs_when_all_three_sides_are_reported() -> None:
    filing = _filing(
        {
            "Assets": [_instant(1_000e6)],
            "Liabilities": [_instant(600e6)],
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
                _instant(400e6)
            ],
        }
    )
    checks = [v for v in filing.validations if v.rule == "balance_sheet_equation"]

    assert len(checks) == 1 and checks[0].passed


def test_parent_only_equity_no_longer_masks_an_nci_gap() -> None:
    """Checked against total equity, a reported balance sheet ties exactly;
    the old parent-only check 'passed' Tesla only because 728M fit inside the
    1% tolerance."""
    period = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))

    def fact(concept: str, value: float) -> CanonicalFact:
        return CanonicalFact(
            concept=concept,
            statement=StatementType.BALANCE_SHEET,
            period=period,
            value=value,
            status=FactStatus.FOUND,
            confidence=Confidence.HIGH,
            origin=Origin.REPORTED,
        )

    filing = CanonicalFilingFacts(
        cik=1,
        company="Audit Co",
        accession=ACCN,
        form="10-K",
        filed="2026-02-01",
        fiscal_year=2025,
        fiscal_period="FY",
        facts=(
            fact("total_assets", 137_806e6),
            fact("total_liabilities", 54_941e6),
            fact("total_equity", 82_807e6),
        ),
    )
    check = next(v for v in run_validations(filing) if v.rule == "balance_sheet_equation")

    assert check.passed
    assert abs(float(check.details["difference"] or 0)) < 100e6  # mezzanine NCI only


# --- Phantom periods, parent equity, and synonym tolerance -------------------


def test_a_roll_forward_opening_balance_does_not_fabricate_a_balance_sheet() -> None:
    """A statement of equity opens three years back with total equity only.
    That period is kept as a real fact, but it must not spawn a column of
    MISSING balance-sheet rows -- 17 of 45 golden-set balance-sheet slots
    were such phantoms."""
    old = {"end": "2022-12-31", "accn": ACCN, "fy": 2025, "fp": "FY", "form": "10-K"}
    filing = _filing(
        {
            "Assets": [_instant(1_000e6)],
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
                _instant(400e6),
                ("USD", {**old, "val": 350e6}),
            ],
        }
    )

    assert filing.get("total_equity", "FY2022") is not None
    assert filing.get("total_assets", "FY2022") is None
    assert filing.get("total_debt", "FY2022") is None
    assert filing.get("total_assets", "FY2025") is not None


def test_parent_equity_is_recovered_as_total_minus_nci() -> None:
    """iHeartMedia FY2015/16 tag total equity and NCI but not parent equity."""
    filing = _filing(
        {
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
                _instant(-10_000e6)
            ],
            "MinorityInterest": [_instant(50e6)],
        }
    )
    parent = filing.get("shareholders_equity", "FY2025")

    assert parent is not None
    assert parent.status is FactStatus.DERIVED
    assert parent.value == -10_050e6


def test_synonyms_differing_by_under_one_percent_are_still_a_conflict() -> None:
    """The original 1% tolerance let a 0.9% gap (iHeartMedia's 181M) pass as
    'the same number'. Genuine synonyms in one filing carry the same integer."""
    filing = _filing(
        {"InventoryNet": [_instant(20_720e6)], "InventoryNetCurrent": [_instant(20_539e6)]}
    )
    inventory = filing.get("inventory", "FY2025")

    assert inventory is not None
    assert inventory.status is FactStatus.CONFLICTING


def test_a_close_but_differently_scoped_value_is_kept_as_a_candidate() -> None:
    filing = _filing(
        {"LongTermDebtNoncurrent": [_instant(20_539e6)], "LongTermDebt": [_instant(20_720e6)]}
    )
    long_term = filing.get("long_term_debt", "FY2025")

    assert long_term is not None
    assert long_term.value == 20_539e6
    assert [c.value for c in long_term.candidates] == [20_720e6]


# --- Duplicates and signs ------------------------------------------------------


def test_one_tag_with_two_values_for_one_period_is_a_conflict_not_first_wins() -> None:
    filing = _filing({"Assets": [_instant(1_000e6), _instant(1_200e6)]})
    assets = filing.get("total_assets", "FY2025")

    assert assets is not None
    assert assets.status is FactStatus.CONFLICTING
    assert sorted(c.value for c in assets.candidates) == [1_000e6, 1_200e6]


def test_an_exact_duplicate_of_one_tag_is_not_a_conflict() -> None:
    filing = _filing({"Assets": [_instant(1_000e6), _instant(1_000e6)]})
    assets = filing.get("total_assets", "FY2025")

    assert assets is not None
    assert assets.status is FactStatus.FOUND


def test_a_negative_capex_is_flagged_because_fcf_would_silently_add_it() -> None:
    period = {"start": "2025-01-01"}
    filing = _filing(
        {
            "NetCashProvidedByUsedInOperatingActivities": [
                ("USD", {**_instant(500e6)[1], **period})
            ],
            "PaymentsToAcquirePropertyPlantAndEquipment": [
                ("USD", {**_instant(-100e6)[1], **period})
            ],
        }
    )
    flagged = [
        v
        for v in filing.validations
        if v.rule == "sign_sanity" and v.details.get("concept") == "capital_expenditures"
    ]

    assert flagged


# --- Debt component groups and newer tags ---------------------------------------


def test_commercial_paper_is_part_of_short_term_debt() -> None:
    """Apple FY2025: term debt 12,350M plus commercial paper 7,979M. Without
    commercial paper, short-term debt was understated 39% as a confident FOUND."""
    filing = _filing(
        {"LongTermDebtCurrent": [_instant(12_350e6)], "CommercialPaper": [_instant(7_979e6)]}
    )
    debt = filing.get("short_term_debt", "FY2025")

    assert debt is not None
    assert debt.value == 20_329e6


def test_alternative_tags_for_one_component_are_never_added_together() -> None:
    """A short-term borrowings total and its commercial-paper part are two
    names for one component; summing both would double count."""
    filing = _filing(
        {
            "LongTermDebtCurrent": [_instant(3_542e6)],
            "ShortTermBorrowings": [_instant(6_596e6)],
            "CommercialPaper": [_instant(4_000e6)],
        }
    )
    debt = filing.get("short_term_debt", "FY2025")

    assert debt is not None
    assert debt.value == 10_138e6


def test_debt_tagged_with_finance_leases_resolves() -> None:
    """Coca-Cola FY2025 tags only the debt-and-leases elements plus its
    borrowings parts; it had no debt figure before."""
    filing = _filing(
        {
            "LongTermDebtAndCapitalLeaseObligationsCurrent": [_instant(1_822e6)],
            "CommercialPaper": [_instant(1_495e6)],
            "OtherShortTermBorrowings": [_instant(56e6)],
            "LongTermDebtAndCapitalLeaseObligations": [_instant(42_119e6)],
        }
    )
    short = filing.get("short_term_debt", "FY2025")
    long_term = filing.get("long_term_debt", "FY2025")
    total = filing.get("total_debt", "FY2025")

    assert short is not None and short.value == 3_373e6
    assert long_term is not None and long_term.value == 42_119e6
    assert total is not None and total.value == 45_492e6


def test_nonoperating_interest_expense_element_resolves() -> None:
    """Tesla and UPS tag only InterestExpenseNonoperating."""
    filing = _filing(
        {"InterestExpenseNonoperating": [("USD", {**_instant(338e6)[1], "start": "2025-01-01"})]}
    )
    interest = filing.get("interest_expense", "FY2025")

    assert interest is not None
    assert interest.value == 338e6
