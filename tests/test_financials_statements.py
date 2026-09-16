"""Tests for deterministic statement classification (§6)."""

from __future__ import annotations

from credit_risk_copilot.extraction.models import DocumentLocation, Table
from credit_risk_copilot.financials.models import StatementType
from credit_risk_copilot.financials.statements import classify_table

LOCATION = DocumentLocation(char_start=0, char_end=1)


def table(*rows: tuple[str, ...], context: str | None = None, caption: str | None = None) -> Table:
    return Table(rows=rows, location=LOCATION, context=context, caption=caption)


def test_balance_sheet_title_in_context() -> None:
    t = table(("Cash", "50"), context="Apple Inc. | CONSOLIDATED BALANCE SHEETS | (In millions)")

    assert classify_table(t) is StatementType.BALANCE_SHEET


def test_income_statement_title_in_context() -> None:
    t = table(("Revenue", "500"), context="CONSOLIDATED STATEMENTS OF OPERATIONS")

    assert classify_table(t) is StatementType.INCOME_STATEMENT


def test_cash_flow_title_in_context() -> None:
    t = table(("Cash", "50"), context="CONSOLIDATED STATEMENTS OF CASH FLOWS")

    assert classify_table(t) is StatementType.CASH_FLOW


def test_equity_title_in_context() -> None:
    t = table(("Balance", "1"), context="CONSOLIDATED STATEMENTS OF STOCKHOLDERS' EQUITY")

    assert classify_table(t) is StatementType.EQUITY


def test_row_label_fallback_when_no_title_is_available() -> None:
    """§6: must not depend solely on section headings."""
    t = table(("Total assets", "1,000"), ("Total liabilities", "600"))

    assert classify_table(t) is StatementType.BALANCE_SHEET


def test_income_statement_row_label_fallback() -> None:
    t = table(("Revenue", "500"), ("Net income", "100"))

    assert classify_table(t) is StatementType.INCOME_STATEMENT


def test_unrelated_table_is_other_not_a_guess() -> None:
    t = table(("Item 1", "Item 2"), ("Alpha", "Beta"))

    assert classify_table(t) is StatementType.OTHER


def test_caption_alone_can_classify() -> None:
    t = table(("Cash", "50"), caption="Balance Sheet")

    assert classify_table(t) is StatementType.BALANCE_SHEET
