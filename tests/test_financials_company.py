"""Tests for multi-filing aggregation and the as-filed / point-in-time rule (§27, D-008)."""

from __future__ import annotations

from datetime import date

from credit_risk_copilot.financials.company import CompanyFinancials
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

FY2024 = Period(period_type=PeriodType.INSTANT, end=date(2024, 12, 31))


def _fact(value: float) -> CanonicalFact:
    return CanonicalFact(
        concept="total_assets",
        statement=StatementType.BALANCE_SHEET,
        period=FY2024,
        value=value,
        status=FactStatus.FOUND,
        confidence=Confidence.HIGH,
        origin=Origin.REPORTED,
    )


def _filing(*, accession: str, filed: str, value: float) -> CanonicalFilingFacts:
    return CanonicalFilingFacts(
        cik=1,
        company="Test Co",
        accession=accession,
        form="10-K",
        filed=filed,
        fiscal_year=int(filed[:4]),
        fiscal_period="FY",
        facts=(_fact(value),),
    )


def test_as_of_uses_the_earliest_filing_that_reported_the_period() -> None:
    """D-008: an assessment as of T must use the value as originally filed,
    not a later restatement, even if the later filing is also <= T."""
    original = _filing(accession="acc-2025", filed="2025-02-01", value=900)
    restated = _filing(accession="acc-2026", filed="2026-02-01", value=950)
    company = CompanyFinancials(cik=1, company="Test Co", filings=(restated, original))

    snapshot = company.as_of(date(2026, 6, 1))

    assert snapshot[("total_assets", "FY2024")].value == 900


def test_as_of_ignores_filings_filed_after_the_cutoff() -> None:
    original = _filing(accession="acc-2025", filed="2025-02-01", value=900)
    restated = _filing(accession="acc-2026", filed="2026-02-01", value=950)
    company = CompanyFinancials(cik=1, company="Test Co", filings=(original, restated))

    snapshot = company.as_of(date(2025, 6, 1))

    assert snapshot[("total_assets", "FY2024")].value == 900
    assert len(snapshot) == 1


def test_restatements_are_surfaced_not_silently_resolved() -> None:
    original = _filing(accession="acc-2025", filed="2025-02-01", value=900)
    restated = _filing(accession="acc-2026", filed="2026-02-01", value=950)
    company = CompanyFinancials(cik=1, company="Test Co", filings=(original, restated))

    restatements = company.restatements()

    assert len(restatements) == 1
    assert restatements[0].original.value == 900
    assert restatements[0].restated[0].value == 950


def test_no_restatement_when_filings_agree() -> None:
    a = _filing(accession="acc-2025", filed="2025-02-01", value=900)
    b = _filing(accession="acc-2026", filed="2026-02-01", value=900)
    company = CompanyFinancials(cik=1, company="Test Co", filings=(a, b))

    assert company.restatements() == ()
