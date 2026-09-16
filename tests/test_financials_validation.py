"""Tests for accounting-consistency checks (§17): flags, never rejections."""

from __future__ import annotations

from datetime import date

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
from credit_risk_copilot.financials.validation import run_validations

INSTANT_2025 = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))
INSTANT_2024 = Period(period_type=PeriodType.INSTANT, end=date(2024, 12, 31))
DURATION_2025 = Period(
    period_type=PeriodType.DURATION, start=date(2025, 1, 1), end=date(2025, 12, 31)
)


def _found(concept: str, value: float, statement: StatementType, period: Period) -> CanonicalFact:
    return CanonicalFact(
        concept=concept,
        statement=statement,
        period=period,
        value=value,
        status=FactStatus.FOUND,
        confidence=Confidence.HIGH,
        origin=Origin.REPORTED,
    )


def _filing(*facts: CanonicalFact) -> CanonicalFilingFacts:
    return CanonicalFilingFacts(
        cik=1,
        company="Test Co",
        accession="acc1",
        form="10-K",
        filed="2025-02-01",
        fiscal_year=2025,
        fiscal_period="FY",
        facts=tuple(facts),
    )


def test_balance_sheet_equation_passes_when_it_holds() -> None:
    filing = _filing(
        _found("total_assets", 1000, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("total_liabilities", 600, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("total_equity", 400, StatementType.BALANCE_SHEET, INSTANT_2025),
    )

    results = run_validations(filing)
    equation = next(r for r in results if r.rule == "balance_sheet_equation")
    assert equation.passed


def test_balance_sheet_equation_fails_when_it_does_not_hold() -> None:
    filing = _filing(
        _found("total_assets", 1000, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("total_liabilities", 600, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("total_equity", 100, StatementType.BALANCE_SHEET, INSTANT_2025),  # off by 300
    )

    results = run_validations(filing)
    equation = next(r for r in results if r.rule == "balance_sheet_equation")
    assert not equation.passed
    assert equation.details["difference"] == 300


def test_balance_sheet_equation_is_skipped_when_an_input_is_missing() -> None:
    filing = _filing(_found("total_assets", 1000, StatementType.BALANCE_SHEET, INSTANT_2025))

    results = run_validations(filing)
    assert not [r for r in results if r.rule == "balance_sheet_equation"]


def test_cash_tie_out_passes_when_it_holds() -> None:
    filing = _filing(
        _found("cash", 100, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("cash", 40, StatementType.BALANCE_SHEET, INSTANT_2024),
        _found("operating_cash_flow", 80, StatementType.CASH_FLOW, DURATION_2025),
        _found("investing_cash_flow", -30, StatementType.CASH_FLOW, DURATION_2025),
        _found("financing_cash_flow", 10, StatementType.CASH_FLOW, DURATION_2025),
    )

    results = run_validations(filing)
    tie_out = next(r for r in results if r.rule == "cash_tie_out")
    assert tie_out.passed  # 40 + 80 - 30 + 10 = 100


def test_cash_tie_out_flags_but_does_not_reject_a_mismatch() -> None:
    filing = _filing(
        _found("cash", 500, StatementType.BALANCE_SHEET, INSTANT_2025),  # way off
        _found("cash", 40, StatementType.BALANCE_SHEET, INSTANT_2024),
        _found("operating_cash_flow", 80, StatementType.CASH_FLOW, DURATION_2025),
        _found("investing_cash_flow", -30, StatementType.CASH_FLOW, DURATION_2025),
        _found("financing_cash_flow", 10, StatementType.CASH_FLOW, DURATION_2025),
    )

    results = run_validations(filing)
    tie_out = next(r for r in results if r.rule == "cash_tie_out")
    assert not tie_out.passed
    # Still a flag, not an exception or a mutated value -- the fact itself is untouched.
    cash_fact = next(f for f in filing.facts if f.concept == "cash" and f.period == INSTANT_2025)
    assert cash_fact.value == 500


def test_negative_equity_is_not_flagged_as_a_sign_error() -> None:
    """§17: unusual is not the same as wrong -- negative equity is common
    among distressed filers and must never be treated as an extraction error."""
    filing = _filing(
        _found("shareholders_equity", -200, StatementType.BALANCE_SHEET, INSTANT_2025),
    )

    results = run_validations(filing)
    assert not [r for r in results if r.rule == "sign_sanity"]


def test_negative_total_assets_is_flagged() -> None:
    filing = _filing(_found("total_assets", -50, StatementType.BALANCE_SHEET, INSTANT_2025))

    results = run_validations(filing)
    findings = [r for r in results if r.rule == "sign_sanity"]
    assert len(findings) == 1
    assert not findings[0].passed


def test_current_assets_exceeding_total_assets_is_flagged() -> None:
    filing = _filing(
        _found("total_assets", 100, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("current_assets", 150, StatementType.BALANCE_SHEET, INSTANT_2025),
    )

    results = run_validations(filing)
    findings = [r for r in results if r.rule == "sign_sanity"]
    assert any("exceeds" in f.message for f in findings)


def test_no_findings_for_a_clean_filing() -> None:
    filing = _filing(
        _found("total_assets", 1000, StatementType.BALANCE_SHEET, INSTANT_2025),
        _found("current_assets", 300, StatementType.BALANCE_SHEET, INSTANT_2025),
    )

    results = run_validations(filing)
    assert not [r for r in results if r.rule == "sign_sanity"]
