"""The ratio catalog: what Phase 6 calculates, from what, and why (§5-§7).

Thirteen ratios across five categories. Every one is chosen because its
inputs are canonical concepts Phase 5 actually resolves and its formula is a
settled accounting definition -- not added merely to grow the count (§6).
Free cash flow itself, and a handful of other ratios the phase brief
mentions, are deliberately left out; see the per-concept `rationale` below
and `docs/ratios.md` for the full reasoning.

## Why a registry, not scattered formulas (§7)

Every ratio is one `RatioDefinition`: its inputs (canonical concept ids, in
formula order), a machine formula string, a human-readable formula for
`explain()`, its denominator concept (for the zero/negative checks in
`engine.py`), and a `compute` callable. `engine.py` is generic over this
list -- adding a ratio is one new entry here, never a new branch in the
calculation engine.

## Why "x" vs "%" (§21)

Ratios comparing two figures of the same broad nature at a similar scale
(current assets/liabilities, debt/equity, EBIT/interest expense) are
conventionally quoted as multiples ("1.74x"); ratios expressing one figure as
a share of another (debt as a fraction of assets, income as a fraction of
revenue/assets/equity, cash flow as a fraction of revenue/debt) are
conventionally quoted as percentages. This mirrors how the figures are
actually reported by analysts, not an arbitrary per-ratio choice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RatioDefinition:
    ratio_id: str
    name: str
    category: str
    #: Canonical concept ids, in the order `formula_display` and `explain()`
    #: present them.
    inputs: tuple[str, ...]
    #: Machine-readable formula, e.g. "total_debt / shareholders_equity".
    formula: str
    #: Human-readable formula for explanations, e.g. "Total Debt / Shareholders' Equity".
    formula_display: str
    unit: str  # "x" or "%"
    compute: Callable[[dict[str, float]], float]
    #: Which input is checked for zero/negative before `compute` runs.
    denominator_concept: str
    #: True only for equity-based ratios, where a negative denominator is a
    #: real, meaningful state (distressed filers) rather than a data error
    #: (§10). Calculated with a warning instead of `INVALID_DENOMINATOR`.
    denominator_may_be_negative: bool = False
    rationale: str = ""
    #: `None` for every ratio with exactly one possible calculation method.
    #: Set explicitly only where a documented choice exists between methods
    #: -- currently `"ending_balance"` on `roa`/`roe` (D-020) -- so the
    #: choice is machine-readable on every result, not only in this
    #: docstring/`docs/ratios.md`.
    calculation_method: str | None = None


RATIO_DEFINITIONS: tuple[RatioDefinition, ...] = (
    # --- Liquidity -----------------------------------------------------------
    RatioDefinition(
        ratio_id="current_ratio",
        name="Current Ratio",
        category="liquidity",
        inputs=("current_assets", "current_liabilities"),
        formula="current_assets / current_liabilities",
        formula_display="Current Assets / Current Liabilities",
        unit="x",
        compute=lambda v: v["current_assets"] / v["current_liabilities"],
        denominator_concept="current_liabilities",
        rationale="Standard short-term solvency measure; both inputs are 12/12-complete canonical concepts.",
    ),
    RatioDefinition(
        ratio_id="quick_ratio",
        name="Quick Ratio",
        category="liquidity",
        inputs=("cash", "accounts_receivable", "current_liabilities"),
        formula="(cash + accounts_receivable) / current_liabilities",
        formula_display="(Cash + Accounts Receivable) / Current Liabilities",
        unit="x",
        compute=lambda v: (v["cash"] + v["accounts_receivable"]) / v["current_liabilities"],
        denominator_concept="current_liabilities",
        rationale=(
            "The canonical schema has no short-term-investments/marketable-securities "
            "concept, so this is cash + receivables over current liabilities, not the "
            "textbook 'all current assets except inventory and prepaids' formulation. "
            "Narrower than the textbook definition, not wider -- it will never overstate "
            "quick assets. Documented in docs/ratios.md as a named limitation."
        ),
    ),
    # --- Leverage --------------------------------------------------------------
    RatioDefinition(
        ratio_id="debt_to_equity",
        name="Debt-to-Equity",
        category="leverage",
        inputs=("total_debt", "shareholders_equity"),
        formula="total_debt / shareholders_equity",
        formula_display="Total Debt / Shareholders' Equity",
        unit="x",
        compute=lambda v: v["total_debt"] / v["shareholders_equity"],
        denominator_concept="shareholders_equity",
        denominator_may_be_negative=True,
        rationale=(
            "Core leverage ratio. Uses parent shareholders_equity (not total_equity), "
            "matching canonical_schema.md §16's guidance to use the shareholder-level "
            "equity concept for shareholder-facing ratios."
        ),
    ),
    RatioDefinition(
        ratio_id="debt_to_assets",
        name="Debt-to-Assets",
        category="leverage",
        inputs=("total_debt", "total_assets"),
        formula="total_debt / total_assets",
        formula_display="Total Debt / Total Assets",
        unit="%",
        compute=lambda v: v["total_debt"] / v["total_assets"],
        denominator_concept="total_assets",
        rationale="Leverage independent of the equity/NCI split; total_assets is 12/12-complete.",
    ),
    RatioDefinition(
        ratio_id="liabilities_to_assets",
        name="Liabilities-to-Assets",
        category="leverage",
        inputs=("total_liabilities", "total_assets"),
        formula="total_liabilities / total_assets",
        formula_display="Total Liabilities / Total Assets",
        unit="%",
        compute=lambda v: v["total_liabilities"] / v["total_assets"],
        denominator_concept="total_assets",
        rationale=(
            "Broader leverage measure than debt/assets: total_liabilities includes "
            "non-debt obligations (payables, deferred revenue, pension liabilities) that "
            "total_debt deliberately excludes."
        ),
    ),
    # --- Profitability -----------------------------------------------------------
    RatioDefinition(
        ratio_id="gross_margin",
        name="Gross Margin",
        category="profitability",
        inputs=("gross_profit", "revenue"),
        formula="gross_profit / revenue",
        formula_display="Gross Profit / Revenue",
        unit="%",
        compute=lambda v: v["gross_profit"] / v["revenue"],
        denominator_concept="revenue",
        rationale=(
            "gross_profit exists in the canonical schema specifically to support this "
            "ratio (concept_map.py's own rationale); not usable for filers presenting "
            "costs by nature rather than by function, where cost_of_goods_sold is absent."
        ),
    ),
    RatioDefinition(
        ratio_id="operating_margin",
        name="Operating Margin",
        category="profitability",
        inputs=("operating_income", "revenue"),
        formula="operating_income / revenue",
        formula_display="Operating Income / Revenue",
        unit="%",
        compute=lambda v: v["operating_income"] / v["revenue"],
        denominator_concept="revenue",
        rationale="operating_income is an 11/12-complete direct tag; no cost-presentation gap.",
    ),
    RatioDefinition(
        ratio_id="net_profit_margin",
        name="Net Profit Margin",
        category="profitability",
        inputs=("net_income", "revenue"),
        formula="net_income / revenue",
        formula_display="Net Income / Revenue",
        unit="%",
        compute=lambda v: v["net_income"] / v["revenue"],
        denominator_concept="revenue",
        rationale="Both inputs are 12/12-complete; the most widely comparable margin.",
    ),
    RatioDefinition(
        ratio_id="roa",
        name="Return on Assets",
        category="profitability",
        inputs=("net_income", "total_assets"),
        formula="net_income / total_assets",
        formula_display="Net Income / Total Assets",
        unit="%",
        compute=lambda v: v["net_income"] / v["total_assets"],
        denominator_concept="total_assets",
        calculation_method="ending_balance",
        rationale=(
            "MVP uses ending total_assets, not average(beginning, ending) -- a deliberate "
            "simplification (D-020): it keeps every ratio a single-period calculation with "
            "no cross-period dependency, and is always computable from one balance sheet "
            "rather than requiring the prior year to have also resolved. See docs/ratios.md."
        ),
    ),
    RatioDefinition(
        ratio_id="roe",
        name="Return on Equity",
        category="profitability",
        inputs=("net_income", "shareholders_equity"),
        formula="net_income / shareholders_equity",
        formula_display="Net Income / Shareholders' Equity",
        unit="%",
        compute=lambda v: v["net_income"] / v["shareholders_equity"],
        denominator_concept="shareholders_equity",
        denominator_may_be_negative=True,
        calculation_method="ending_balance",
        rationale="Same ending-balance MVP choice as ROA (D-020); equity may legitimately be negative.",
    ),
    # --- Coverage --------------------------------------------------------------
    RatioDefinition(
        ratio_id="interest_coverage",
        name="Interest Coverage",
        category="coverage",
        inputs=("ebit", "interest_expense"),
        formula="ebit / interest_expense",
        formula_display="EBIT / Interest Expense",
        unit="x",
        compute=lambda v: v["ebit"] / v["interest_expense"],
        denominator_concept="interest_expense",
        rationale=(
            "EBIT, not EBITDA: the canonical schema has no depreciation/amortisation "
            "concept, so EBITDA is not available without adding one. interest_expense is "
            "a positive magnitude under the schema's sign convention (canonical_schema.md "
            "§14), so this is never divided by a signed value."
        ),
    ),
    # --- Cash flow --------------------------------------------------------------
    RatioDefinition(
        ratio_id="ocf_to_debt",
        name="Operating Cash Flow to Debt",
        category="cash_flow",
        inputs=("operating_cash_flow", "total_debt"),
        formula="operating_cash_flow / total_debt",
        formula_display="Operating Cash Flow / Total Debt",
        unit="%",
        compute=lambda v: v["operating_cash_flow"] / v["total_debt"],
        denominator_concept="total_debt",
        rationale=(
            "Chosen over any free_cash_flow-based ratio: free_cash_flow's capital_expenditures "
            "input is left deliberately CONFLICTING for filers whose PP&E and capital-"
            "improvement tags overlap (canonical_schema.md §15), which would make an "
            "FCF-based ratio unavailable exactly where debt coverage matters most."
        ),
    ),
    RatioDefinition(
        ratio_id="ocf_to_revenue",
        name="Operating Cash Flow to Revenue",
        category="cash_flow",
        inputs=("operating_cash_flow", "revenue"),
        formula="operating_cash_flow / revenue",
        formula_display="Operating Cash Flow / Revenue",
        unit="%",
        compute=lambda v: v["operating_cash_flow"] / v["revenue"],
        denominator_concept="revenue",
        rationale="Cash-conversion quality of revenue; both inputs are near-universally complete.",
    ),
)

RATIOS_BY_ID: dict[str, RatioDefinition] = {r.ratio_id: r for r in RATIO_DEFINITIONS}
