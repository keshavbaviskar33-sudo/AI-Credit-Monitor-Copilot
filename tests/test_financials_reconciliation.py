"""Tests for bounded document-evidence corroboration (§13, §20)."""

from __future__ import annotations

from datetime import date

from credit_risk_copilot.extraction import DocumentSource, HtmlDocumentExtractor
from credit_risk_copilot.financials.models import (
    CanonicalFact,
    Confidence,
    FactStatus,
    Origin,
    Period,
    PeriodType,
    StatementType,
)
from credit_risk_copilot.financials.reconciliation import corroborate_fact

PERIOD = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))
SOURCE = DocumentSource(uri="filing.htm", media_type="text/html")


def extract(html: str):
    return HtmlDocumentExtractor().extract(html.encode("utf-8"), SOURCE)


def _fact(value: float, status: FactStatus = FactStatus.FOUND) -> CanonicalFact:
    return CanonicalFact(
        concept="total_assets",
        statement=StatementType.BALANCE_SHEET,
        period=PERIOD,
        value=value,
        status=status,
        confidence=Confidence.MEDIUM,
        origin=Origin.REPORTED,
    )


def test_value_found_in_the_document_raises_confidence_and_adds_provenance() -> None:
    document = extract("<body><table><tr><td>Total assets</td><td>1,234</td></tr></table></body>")
    fact = _fact(1234.0)

    result = corroborate_fact(fact, document)

    assert result.confidence is Confidence.HIGH
    assert len(result.provenance) == 1
    assert result.provenance[0].source_type.value == "html"


def test_value_absent_from_the_document_is_not_downgraded() -> None:
    """HTML recall on the golden set is 85.1%, not 100% -- absence must never
    be read as a conflict (§13)."""
    document = extract("<body><table><tr><td>Total assets</td><td>9,999</td></tr></table></body>")
    fact = _fact(1234.0)

    result = corroborate_fact(fact, document)

    assert result.confidence is Confidence.MEDIUM  # unchanged
    assert result.provenance == ()


def test_missing_facts_are_never_searched_for() -> None:
    document = extract("<body><table><tr><td>Total assets</td><td>1,234</td></tr></table></body>")
    fact = _fact(1234.0, status=FactStatus.MISSING).model_copy(update={"value": None})

    result = corroborate_fact(fact, document)

    assert result == fact
