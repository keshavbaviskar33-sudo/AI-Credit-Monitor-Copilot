"""Deterministic statement classification for a Phase 4 `Table` (§6).

Two tiers, cheapest first, per the phase brief's "don't depend solely on
section headings" and "avoid an LLM when rules suffice":

1. **Context/caption keywords.** `Table.context` -- the text immediately
   above a table -- is where filings put the statement title
   ("CONSOLIDATED BALANCE SHEETS"), per `extraction.md` §2a. This alone
   classifies the great majority of statement tables correctly.
2. **Row-label fallback.** When no title is available (a continuation table,
   or a title one paragraph further up than `context` captured), look for
   the row labels a given statement always contains -- "total assets" *and*
   "total liabilities" together only appear on a balance sheet, etc.

Anything matching neither is `OTHER`, not a guess -- consistent with the
extraction layer's "insufficient information is a valid answer".
"""

from __future__ import annotations

from credit_risk_copilot.extraction.models import Table
from credit_risk_copilot.financials.models import StatementType

#: Ordered so a table matching more than one tier (rare, e.g. a combined
#: statement of operations and comprehensive income) resolves predictably.
_TITLE_KEYWORDS: tuple[tuple[StatementType, tuple[str, ...]], ...] = (
    (
        StatementType.CASH_FLOW,
        ("statements of cash flows", "statement of cash flows", "cash flow statement"),
    ),
    (
        StatementType.EQUITY,
        (
            "statements of stockholders' equity",
            "statement of stockholders' equity",
            "statements of shareholders' equity",
            "statement of changes in equity",
        ),
    ),
    (StatementType.BALANCE_SHEET, ("balance sheet", "statements of financial position")),
    (
        StatementType.INCOME_STATEMENT,
        (
            "statements of operations",
            "statement of operations",
            "statements of income",
            "statement of income",
            "income statement",
        ),
    ),
)

#: Row labels that, together, are near-unique to one statement. Any one
#: label alone is too weak ("Total" appears everywhere); requiring both
#: anchors of a pair is what keeps this from over-firing on unrelated tables.
_ROW_LABEL_ANCHORS: tuple[tuple[StatementType, tuple[str, str]], ...] = (
    (StatementType.BALANCE_SHEET, ("total assets", "total liabilities")),
    (StatementType.INCOME_STATEMENT, ("net income", "revenue")),
    (StatementType.CASH_FLOW, ("operating activities", "investing activities")),
    (StatementType.EQUITY, ("balance at", "common stock")),
)


def _matching_text(table: Table) -> str:
    return " ".join(filter(None, (table.context, table.caption))).lower()


def _row_text(table: Table) -> str:
    return " ".join(cell.lower() for row in table.rows for cell in row if cell)


def classify_table(table: Table) -> StatementType:
    """Classify one table by statement. Never raises -- returns `OTHER` when
    nothing matches, since Phase 4's own tables are "returned even when they
    fail a screen" (`Table.looks_like_financial_data`'s convention)."""
    title_text = _matching_text(table)
    for statement, keywords in _TITLE_KEYWORDS:
        if any(keyword in title_text for keyword in keywords):
            return statement

    row_text = _row_text(table)
    for statement, (anchor_a, anchor_b) in _ROW_LABEL_ANCHORS:
        if anchor_a in row_text and anchor_b in row_text:
            return statement

    return StatementType.OTHER
