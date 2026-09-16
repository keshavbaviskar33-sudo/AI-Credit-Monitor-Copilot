"""The canonical concept set: what Phase 5 resolves, and from what (§5, §11).

## Why these concepts and no others

The set below is the minimum needed for the ratios the roadmap already
commits to (Phase 6): current/quick ratio, debt/equity, debt/assets, interest
coverage, net/operating margin, ROA, and free cash flow. Nothing here exists
for a ratio that is not planned; `cost_of_goods_sold`, `pretax_income` and
`accounts_receivable`/`inventory` are the exception -- they are not
ratio-final themselves but are the minimum needed to *derive* gross profit,
EBIT and the quick ratio without inventing a new lookup later. `revenue`
losing `SalesRevenueNet` from its fallback chain, and `Liabilities` gaining a
derivation, are direct responses to the measured gaps in
`data_dictionary.md` §6.1 (R-11): a single-tag lookup was shown to fail for
half the golden set on exactly these two fields.

## Why fallback chains, not one tag per concept

`SalesRevenueNet` is tagged by 0/12 golden-set filers -- it is deprecated, and
a schema built on the Phase 3 concept list before this was measured would
return `missing_input` for revenue on modern filers. Each concept instead
carries an ordered tuple of XBRL tags.

## Why a chain needs a *policy*, not just an order (the Phase 5 audit's finding)

The first version of this module treated every chain the same way: take the
highest-priority present tag, and call it `CONFLICTING` if two present tags
disagree. Auditing that against the golden set showed the assumption behind
it is false -- **the tags in a chain are not all alternates for one idea**,
and three genuinely different relationships were being collapsed into one:

| Relationship | Example | Right answer |
|---|---|---|
| True alternates | `InventoryNet` / `InventoryNetCurrent` | First present wins; a disagreement is a real conflict |
| Different scope | `NetIncomeLoss` (parent) vs. `ProfitLoss` (incl. NCI) | Priority order *is* the accounting choice; the difference is expected, not a conflict |
| Additive components | `LongTermDebtCurrent` + `ShortTermBorrowings` | Must be **summed**; picking one understates the total |

Treating scope differences as conflicts cost 32 resolvable values across the
12-filing golden set (`net_income` 13, `shareholders_equity` 9, `revenue` 5,
`operating_cash_flow` 3). Treating components as alternates was worse than
lossy: Walmart's short-term debt is `LongTermDebtCurrent` 3,542M **plus**
`ShortTermBorrowings` 6,596M, and picking the first tag alone would have
reported 3,542M as the whole -- a 65% understatement feeding straight into a
leverage ratio. `TagResolution` below makes the relationship explicit per
concept so the resolver stops guessing which one it is.

## Why derivation rules, not blind summation

A derived concept states its formula explicitly (`origin=DERIVED`,
`formula=...` on the resulting `CanonicalFact`) so it is never mistaken for a
reported figure (§16, §11: "do not assume that all candidates can simply be
summed" -- these sums are the ones verified to be the intended accounting
relationship, not a guess).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from credit_risk_copilot.financials.models import PeriodType, StatementType


class TagResolution(str, Enum):
    """How to combine a concept's XBRL tags when more than one is reported.

    See the module docstring for the measurement that made this necessary.
    """

    #: The tags mean the same thing. Highest-priority present tag wins; if two
    #: disagree beyond rounding, that is a genuine `CONFLICTING` fact.
    ALTERNATES = "alternates"
    #: The tags measure deliberately different scopes of the same idea
    #: (parent-only vs. consolidated, total vs. continuing-operations-only,
    #: revenue net of assessed tax vs. gross of it). Priority order encodes
    #: which scope this schema wants, so a difference is *expected* -- the
    #: preferred value is kept and the alternative is recorded alongside it,
    #: rather than both being discarded as a conflict.
    PREFERRED_SCOPE = "preferred_scope"
    #: The tags are additive parts of the canonical concept. `total_tag`, when
    #: the filer reports it, is the whole and wins outright; otherwise every
    #: present component is summed. Never "pick the first one".
    COMPONENTS = "components"


@dataclass(frozen=True)
class DerivationRule:
    """One way to compute a concept from other already-resolved concepts.

    A concept may list more than one rule (e.g. EBIT from pretax income +
    interest expense, or -- if either is missing -- from operating income);
    `resolver.py` tries them in order and uses the first whose inputs are all
    resolved.
    """

    formula: str
    inputs: tuple[str, ...]
    compute: Callable[[dict[str, float]], float]


@dataclass(frozen=True)
class ConceptDefinition:
    concept: str
    label: str
    statement: StatementType
    period_nature: PeriodType
    #: XBRL tags tried in priority order, most standard/common first.
    #: Namespace is always "us-gaap" here -- extension concepts, when a filer
    #: uses one, surface separately via `XbrlFact.is_extension` rather than
    #: being guessed at by name.
    xbrl_tags: tuple[str, ...]
    rationale: str
    derivations: tuple[DerivationRule, ...] = field(default_factory=tuple)
    #: How `xbrl_tags` relate to each other. Defaults to the strictest reading
    #: (they are synonyms, so disagreement is a conflict) -- a concept that
    #: needs anything looser has to say so explicitly.
    tag_resolution: TagResolution = TagResolution.ALTERNATES
    #: `COMPONENTS` only: the tag that reports the whole, preferred over
    #: summing the parts when the filer tags it.
    total_tag: str | None = None
    #: `COMPONENTS` only: the additive parts. Each group is one economic
    #: component, given as alternative ways a filer may tag it; the first
    #: alternative with any tag present is used, and its present tags are
    #: summed. Alternatives within a group are never added together -- that
    #: is what prevents double counting the same component under two names.
    component_groups: tuple[tuple[tuple[str, ...], ...], ...] = ()


CONCEPT_DEFINITIONS: tuple[ConceptDefinition, ...] = (
    # --- Income statement --------------------------------------------------
    ConceptDefinition(
        concept="revenue",
        label="Revenue",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
            "SalesRevenueServicesNet",
        ),
        rationale=(
            "Universal input to every profitability and monitoring ratio. "
            "`SalesRevenueNet` deliberately excluded: 0/12 golden-set filers "
            "tag it (data_dictionary.md §6.1) -- it is deprecated by the ASC "
            "606 contract-revenue tags, which are included instead. "
            "PREFERRED_SCOPE because the ASC 606 pair differs by assessed "
            "(sales) tax: a filer tagging both is not contradicting itself, "
            "and this schema wants the net-of-tax reading first."
        ),
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="cost_of_goods_sold",
        label="Cost of Goods/Services Sold",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"),
        rationale=(
            "Not ratio-final on its own; kept only so gross_profit can be "
            "derived. PREFERRED_SCOPE: `CostOfRevenue` routinely includes "
            "service/delivery costs that `CostOfGoodsAndServicesSold` may "
            "not, so a filer tagging both reports two different scopes."
        ),
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="gross_profit",
        label="Gross Profit",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=("GrossProfit",),
        rationale="Direct tag exists for most filers; derived as a fallback for the rest.",
        derivations=(
            DerivationRule(
                formula="revenue - cost_of_goods_sold",
                inputs=("revenue", "cost_of_goods_sold"),
                compute=lambda v: v["revenue"] - v["cost_of_goods_sold"],
            ),
        ),
    ),
    ConceptDefinition(
        concept="operating_income",
        label="Operating Income",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=("OperatingIncomeLoss",),
        rationale="11/12 golden-set coverage (data_dictionary.md §6.1); used directly for margin.",
    ),
    ConceptDefinition(
        concept="interest_expense",
        label="Interest Expense",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "InterestExpense",
            "InterestExpenseNonoperating",
            "InterestExpenseDebt",
            "InterestAndDebtExpense",
        ),
        rationale=(
            "Denominator of interest coverage (Phase 6); no reliable "
            "derivation exists. PREFERRED_SCOPE: `InterestExpenseDebt` is "
            "interest on debt only and `InterestAndDebtExpense` bundles "
            "amortised issuance costs -- narrower and broader readings of the "
            "same line, not synonyms."
        ),
        # `InterestExpenseNonoperating` replaced `InterestExpense` in many
        # 2024+ filings: Tesla and UPS tag only it, so interest coverage was
        # uncomputable for both -- the `SalesRevenueNet` pattern again.
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="pretax_income",
        label="Income Before Income Taxes",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItems"
            "NoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAnd"
            "IncomeLossFromEquityMethodInvestments",
        ),
        rationale="Kept only as an EBIT derivation input, not ratio-final itself.",
    ),
    ConceptDefinition(
        concept="ebit",
        label="Earnings Before Interest and Taxes",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(),
        rationale=(
            "Filers essentially never tag EBIT directly; it is always derived. "
            "Two rules are tried because `pretax_income` (its more precise "
            "input) is tagged inconsistently -- `operating_income` is a "
            "reasonable, near-universal substitute when it is not."
        ),
        derivations=(
            DerivationRule(
                formula="pretax_income + interest_expense",
                inputs=("pretax_income", "interest_expense"),
                compute=lambda v: v["pretax_income"] + v["interest_expense"],
            ),
            DerivationRule(
                formula="operating_income (substitute: no pretax_income/interest_expense)",
                inputs=("operating_income",),
                compute=lambda v: v["operating_income"],
            ),
        ),
    ),
    ConceptDefinition(
        concept="net_income",
        label="Net Income",
        statement=StatementType.INCOME_STATEMENT,
        period_nature=PeriodType.DURATION,
        xbrl_tags=("NetIncomeLoss", "ProfitLoss"),
        rationale=(
            "12/12 golden-set coverage; the proximate driver of the modelled "
            "event. PREFERRED_SCOPE, and this is the case that exposed why "
            "the policy is needed: `NetIncomeLoss` is profit attributable to "
            "the parent, `ProfitLoss` is consolidated profit including "
            "noncontrolling interests. Filers with an NCI tag both, and they "
            "differ by exactly that interest -- treating the pair as "
            "contradictory discarded 13 perfectly good values across the "
            "golden set. Parent-attributable is the right scope for a "
            "shareholder-level return, so it leads."
        ),
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    # --- Balance sheet -------------------------------------------------------
    ConceptDefinition(
        concept="cash",
        label="Cash and Cash Equivalents",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=(
            "CashAndCashEquivalentsAtCarryingValue",
            "CashAndCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations",
            "Cash",
        ),
        rationale="12/12 golden-set coverage; numerator of the cash ratio and FCF context.",
    ),
    ConceptDefinition(
        concept="accounts_receivable",
        label="Accounts Receivable, Net",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
        rationale="Kept only so the quick ratio can exclude inventory from current assets.",
    ),
    ConceptDefinition(
        concept="inventory",
        label="Inventory, Net",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("InventoryNet", "InventoryNetCurrent"),
        rationale="Kept only so the quick ratio can exclude inventory from current assets.",
    ),
    ConceptDefinition(
        concept="current_assets",
        label="Total Current Assets",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("AssetsCurrent",),
        rationale="12/12 golden-set coverage; numerator of the current ratio.",
    ),
    ConceptDefinition(
        concept="total_assets",
        label="Total Assets",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("Assets",),
        rationale="12/12 golden-set coverage; ROA denominator and balance-sheet-equation input.",
    ),
    ConceptDefinition(
        concept="current_liabilities",
        label="Total Current Liabilities",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("LiabilitiesCurrent",),
        rationale="12/12 golden-set coverage; denominator of the current ratio.",
    ),
    ConceptDefinition(
        concept="total_liabilities",
        label="Total Liabilities",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("Liabilities",),
        rationale=(
            "Only 6/12 golden-set filers tag the total directly -- many "
            "present it purely as a presentation subtotal (data_dictionary.md "
            "§6.1). Derived from the balance-sheet identity for the rest, "
            "using **total** equity including noncontrolling interests: the "
            "identity is Assets = Liabilities + Equity(all holders), so "
            "subtracting parent-only equity overstates liabilities by exactly "
            "the NCI. Measured on Tesla FY2025: reported liabilities 54,941M "
            "vs. 55,669M from the parent-only form -- a 728M error that would "
            "have flowed straight into every leverage ratio, and which the "
            "balance-sheet validation could not see because it was checking "
            "the same identity the value came from."
        ),
        derivations=(
            DerivationRule(
                formula="total_assets - total_equity",
                inputs=("total_assets", "total_equity"),
                compute=lambda v: v["total_assets"] - v["total_equity"],
            ),
        ),
    ),
    ConceptDefinition(
        concept="short_term_debt",
        label="Short-Term / Current Debt",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=(
            "DebtCurrent",
            "LongTermDebtCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "ShortTermBorrowings",
            "CommercialPaper",
            "OtherShortTermBorrowings",
            "NotesPayableCurrent",
        ),
        total_tag="DebtCurrent",
        component_groups=(
            # The current portion of long-term debt, with or without finance leases.
            (("LongTermDebtCurrent",), ("LongTermDebtAndCapitalLeaseObligationsCurrent",)),
            # Short-term borrowings: the filer's own total, else its parts.
            (
                ("ShortTermBorrowings",),
                ("CommercialPaper", "OtherShortTermBorrowings"),
                ("NotesPayableCurrent",),
            ),
        ),
        tag_resolution=TagResolution.COMPONENTS,
        rationale=(
            "Half of total_debt, and the concept the audit found most wrongly "
            "modelled. Current debt is two economic components -- the current "
            "portion of long-term debt, and short-term borrowings -- and each "
            "can be tagged more than one way. Picking a single tag silently "
            "understates it: Walmart FY2026 reports `LongTermDebtCurrent` "
            "3,542M and `ShortTermBorrowings` 6,596M (a flat chain returned "
            "3,542M); Apple FY2025 reports term debt 12,350M and "
            "`CommercialPaper` 7,979M (a 39% understatement, returned as a "
            "confident FOUND); Peabody FY2015 tags only "
            "`LongTermDebtAndCapitalLeaseObligationsCurrent` 5,930M -- debt "
            "reclassified as current on default, which a flat chain missed "
            "entirely. `DebtCurrent`, when tagged, is the filer's own total "
            "and wins; Pfizer's confirms the structure (3,154M = 2,997M "
            "current LTD + 157M other borrowings + 0 commercial paper)."
        ),
    ),
    ConceptDefinition(
        concept="long_term_debt",
        label="Long-Term Debt",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=(
            "LongTermDebtNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermDebt",
        ),
        rationale=(
            "PREFERRED_SCOPE, not alternates, and the distinction is "
            "load-bearing: `LongTermDebt` is frequently the filer's **total** "
            "long-term borrowings *including* the current portion, while "
            "`LongTermDebtNoncurrent` is the noncurrent line only. Apple "
            "FY2025 tags all three and the arithmetic proves it -- "
            "`LongTermDebt` 90,678M = `LongTermDebtNoncurrent` 78,328M + "
            "`LongTermDebtCurrent` 12,350M. Reading that 14% gap as a "
            "contradiction discarded the value entirely; the noncurrent tag "
            "is the one this schema wants, because `total_debt` adds "
            "`short_term_debt` back on top and the broader tag would "
            "double-count the current portion."
        ),
        # `LongTermDebtAndCapitalLeaseObligations` is the noncurrent line
        # including finance leases. Coca-Cola and Peabody tag only this, so
        # without it neither had a long-term debt figure at all. It ranks
        # above `LongTermDebt`, which is often the total incl. current portion.
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="total_debt",
        label="Total Debt",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("DebtLongtermAndShorttermCombinedAmount",),
        rationale=(
            "Leverage-ratio numerator. No standard filer ever tags this "
            "directly except via the rare combined-amount tag, so the "
            "derivation (sum of the two components) is the primary path, not "
            "a fallback -- both components must resolve, or this stays MISSING "
            "rather than silently reporting only one half as the total."
        ),
        derivations=(
            DerivationRule(
                formula="short_term_debt + long_term_debt",
                inputs=("short_term_debt", "long_term_debt"),
                compute=lambda v: v["short_term_debt"] + v["long_term_debt"],
            ),
        ),
    ),
    ConceptDefinition(
        concept="shareholders_equity",
        label="Total Stockholders' Equity",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("StockholdersEquity",),
        rationale=(
            "Equity attributable to the parent's own shareholders -- the "
            "debt/equity denominator, and legitimately negative for "
            "distressed filers. The include-NCI tag used to sit in this chain "
            "as a fallback; the audit split it out into `total_equity` "
            "because the two are different measures, not substitutes, and "
            "pairing them produced 9 false conflicts across the golden set."
        ),
        derivations=(
            DerivationRule(
                formula="total_equity - noncontrolling_interest",
                inputs=("total_equity", "noncontrolling_interest"),
                compute=lambda v: v["total_equity"] - v["noncontrolling_interest"],
            ),
        ),
    ),
    ConceptDefinition(
        concept="noncontrolling_interest",
        label="Noncontrolling Interests",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("MinorityInterest",),
        rationale=(
            "Equity held by outside owners of consolidated subsidiaries "
            "(10/12 golden-set filers tag it). Not ratio-final; it exists so "
            "`total_equity` can be reconstructed when a filer tags the parent "
            "line and the NCI line but no combined total. Absent does **not** "
            "mean zero -- it means untagged, so `total_equity` falls back to "
            "parent equity with that assumption stated in its formula."
        ),
    ),
    ConceptDefinition(
        concept="total_equity",
        label="Total Equity (including noncontrolling interests)",
        statement=StatementType.BALANCE_SHEET,
        period_nature=PeriodType.INSTANT,
        xbrl_tags=("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
        rationale=(
            "The equity side of the balance-sheet identity, and therefore the "
            "correct input to the `total_liabilities` derivation -- "
            "Assets = Liabilities + Equity holds for *all* equity holders, "
            "not just the parent's. Tagged directly by 11/12 golden-set "
            "filers; otherwise reconstructed from its two parts."
        ),
        derivations=(
            DerivationRule(
                formula="shareholders_equity + noncontrolling_interest",
                inputs=("shareholders_equity", "noncontrolling_interest"),
                compute=lambda v: v["shareholders_equity"] + v["noncontrolling_interest"],
            ),
            DerivationRule(
                formula="shareholders_equity (no noncontrolling interest reported)",
                inputs=("shareholders_equity",),
                compute=lambda v: v["shareholders_equity"],
            ),
        ),
    ),
    # --- Cash flow statement -------------------------------------------------
    ConceptDefinition(
        concept="operating_cash_flow",
        label="Net Cash from Operating Activities",
        statement=StatementType.CASH_FLOW,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        rationale="Core monitoring signal on its own, and the FCF/cash-tie-out input.",
        # Total vs. continuing-operations-only: the two differ by any
        # discontinued operations, so they are scopes, not synonyms.
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="capital_expenditures",
        label="Purchases of Property, Plant and Equipment",
        statement=StatementType.CASH_FLOW,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForCapitalImprovements",
            "PaymentsToAcquireProductiveAssets",
        ),
        rationale=(
            "Reported as a positive payment amount; FCF subtracts it. "
            "Deliberately left as strict ALTERNATES after the audit, unlike "
            "debt: these tags *can* be additive, but they also overlap in "
            "practice (some filers report capital improvements inside the "
            "PP&E line as well). Pyxus FY2019 tags PP&E 48M and capital "
            "improvements 53M -- nearly equal, so neither 'sum' nor 'pick "
            "one' is defensible from the data. A visible CONFLICTING fact is "
            "safer than a free-cash-flow figure that silently double-counts."
        ),
    ),
    ConceptDefinition(
        concept="investing_cash_flow",
        label="Net Cash from Investing Activities",
        statement=StatementType.CASH_FLOW,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "NetCashProvidedByUsedInInvestingActivities",
            "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
        ),
        rationale="Cash-tie-out input (§17): beginning cash + CFO + CFI + CFF ≈ ending cash.",
        # Total vs. continuing-operations-only: the two differ by any
        # discontinued operations, so they are scopes, not synonyms.
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="financing_cash_flow",
        label="Net Cash from Financing Activities",
        statement=StatementType.CASH_FLOW,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(
            "NetCashProvidedByUsedInFinancingActivities",
            "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
        ),
        rationale="Cash-tie-out input.",
        # Total vs. continuing-operations-only: the two differ by any
        # discontinued operations, so they are scopes, not synonyms.
        tag_resolution=TagResolution.PREFERRED_SCOPE,
    ),
    ConceptDefinition(
        concept="free_cash_flow",
        label="Free Cash Flow",
        statement=StatementType.CASH_FLOW,
        period_nature=PeriodType.DURATION,
        xbrl_tags=(),
        rationale=(
            "No filer tags FCF; it is a standard, unambiguous derivation "
            "(§28 -- this is the one transformation explicitly named as "
            "belonging here rather than Phase 6, because it is a settled "
            "industry definition, unlike a scored ratio)."
        ),
        derivations=(
            DerivationRule(
                formula="operating_cash_flow - capital_expenditures",
                inputs=("operating_cash_flow", "capital_expenditures"),
                compute=lambda v: v["operating_cash_flow"] - v["capital_expenditures"],
            ),
        ),
    ),
)

#: Declaration order carries no meaning: `resolver.py` runs derivation to a
#: fixpoint, so a derived input (`total_equity` feeding `total_liabilities`)
#: resolves regardless of where either concept is declared.
CONCEPTS_BY_ID: dict[str, ConceptDefinition] = {c.concept: c for c in CONCEPT_DEFINITIONS}
