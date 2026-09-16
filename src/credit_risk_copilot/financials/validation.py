"""Accounting-consistency checks (§17): flags, never rejections.

Every check here only fires when it is actually computable -- missing inputs
produce no result rather than a false failure, matching §17's instruction
not to reject an unusual value merely for looking unusual. `balance_sheet_equation`
and `cash_tie_out` report a result (pass or fail) whenever their inputs are
present, so a caller can compute a real pass rate; `sign_sanity` is a battery
of small structural checks and only reports the ones that fire, since "8
checks, all clean, for every period" would just be noise.
"""

from __future__ import annotations

from credit_risk_copilot.financials.models import CanonicalFilingFacts, ValidationResult

#: Concepts that are non-negative by construction. Equity is excluded on
#: purpose -- negative equity is common among distressed filers (the golden
#: set's distressed cohort has several) and is exactly the signal later phases
#: need to see, not a value to flag. So are net income and the net cash flows,
#: whose sign carries meaning.
_NON_NEGATIVE_CONCEPTS = (
    "total_assets",
    "current_assets",
    "current_liabilities",
    "total_liabilities",
    "cash",
    "inventory",
    "accounts_receivable",
    # Debt balances, expenses and payments are positive magnitudes under the
    # XBRL convention this schema keeps (every golden-set value confirms it).
    # A negative here is a sign flip, and `free_cash_flow = operating_cash_flow
    # - capital_expenditures` would silently *add* capex if it ever got one.
    "short_term_debt",
    "long_term_debt",
    "total_debt",
    "interest_expense",
    "cost_of_goods_sold",
    "capital_expenditures",
)


def _balance_sheet_equation(
    filing: CanonicalFilingFacts, period_label: str
) -> ValidationResult | None:
    assets = filing.get("total_assets", period_label)
    liabilities = filing.get("total_liabilities", period_label)
    # Total equity, including noncontrolling interests: the identity holds
    # for all equity holders, and checking it against parent-only equity
    # "passes" NCI-bearing filers only because the tolerance hides the gap.
    equity = filing.get("total_equity", period_label)
    if not (assets and liabilities and equity):
        return None
    # A liabilities figure *derived* as assets - equity satisfies this
    # equation by construction. Scoring it would be circular -- the Phase 5
    # audit found 11 of the first 19 "passes" were exactly that, each with a
    # difference of precisely zero. Such a check proves nothing, so it is
    # not reported at all rather than reported as a pass.
    if {"total_assets", "total_equity"} <= set(liabilities.derived_from) or (
        {"total_assets", "total_liabilities"} <= set(equity.derived_from)
    ):
        return None
    total_assets, total_liabilities, total_equity = (
        assets.effective_value,
        liabilities.effective_value,
        equity.effective_value,
    )
    if total_assets is None or total_liabilities is None or total_equity is None:
        return None

    difference = total_assets - (total_liabilities + total_equity)
    tolerance = max(1.0, 0.01 * abs(total_assets))
    passed = abs(difference) <= tolerance
    return ValidationResult(
        rule="balance_sheet_equation",
        passed=passed,
        period_label=period_label,
        message=(
            "Assets ≈ Liabilities + Equity holds within 1%."
            if passed
            else f"Assets - (Liabilities + Equity) = {difference:,.0f}, outside 1% tolerance -- "
            "check for a unit/scale or extraction error before trusting these three facts."
        ),
        details={
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "difference": difference,
        },
    )


def _cash_tie_out(filing: CanonicalFilingFacts, period_label: str) -> ValidationResult | None:
    cash_now = filing.get("cash", period_label)
    if cash_now is None or cash_now.effective_value is None:
        return None
    ending_cash = cash_now.effective_value
    prior_label = f"FY{cash_now.period.fiscal_year - 1}"
    cash_prior = filing.get("cash", prior_label)
    cfo = filing.get("operating_cash_flow", period_label)
    cfi = filing.get("investing_cash_flow", period_label)
    cff = filing.get("financing_cash_flow", period_label)
    if cash_prior is None or cfo is None or cfi is None or cff is None:
        return None
    prior, operating, investing, financing = (
        cash_prior.effective_value,
        cfo.effective_value,
        cfi.effective_value,
        cff.effective_value,
    )
    if prior is None or operating is None or investing is None or financing is None:
        return None
    implied = prior + operating + investing + financing
    difference = ending_cash - implied
    # Generous tolerance: this identity ignores FX-translation effects on
    # cash, which real filings often report as a separate line this schema
    # does not carry. A miss here is a prompt to look closer, not proof of
    # an extraction error.
    tolerance = max(10.0, 0.05 * abs(ending_cash))
    passed = abs(difference) <= tolerance
    return ValidationResult(
        rule="cash_tie_out",
        passed=passed,
        period_label=period_label,
        message=(
            "Prior cash + CFO + CFI + CFF ≈ ending cash holds within 5%."
            if passed
            else f"Prior cash + CFO + CFI + CFF - ending cash = {difference:,.0f}, outside 5% "
            "tolerance. FX-translation effects on cash are not modelled here, so this flags "
            "for review rather than confirming an error."
        ),
        details={
            "prior_cash": prior,
            "operating_cash_flow": operating,
            "investing_cash_flow": investing,
            "financing_cash_flow": financing,
            "ending_cash": ending_cash,
            "difference": difference,
        },
    )


def _sign_sanity(filing: CanonicalFilingFacts, period_label: str) -> list[ValidationResult]:
    findings: list[ValidationResult] = []
    for concept in _NON_NEGATIVE_CONCEPTS:
        fact = filing.get(concept, period_label)
        if fact is None or fact.effective_value is None:
            continue
        if fact.effective_value < 0:
            findings.append(
                ValidationResult(
                    rule="sign_sanity",
                    passed=False,
                    period_label=period_label,
                    message=f"{concept} is negative ({fact.effective_value:,.0f}), which is "
                    "structurally implausible for this concept -- check for a sign or column error.",
                    details={"concept": concept, "value": fact.effective_value},
                )
            )

    for whole, part in (
        ("total_assets", "current_assets"),
        ("total_liabilities", "current_liabilities"),
    ):
        whole_fact, part_fact = filing.get(whole, period_label), filing.get(part, period_label)
        if not (whole_fact and part_fact):
            continue
        w, p = whole_fact.effective_value, part_fact.effective_value
        if w is None or p is None:
            continue
        if p > w * 1.001:
            findings.append(
                ValidationResult(
                    rule="sign_sanity",
                    passed=False,
                    period_label=period_label,
                    message=f"{part} ({p:,.0f}) exceeds {whole} ({w:,.0f}) -- a part cannot be "
                    "larger than its whole.",
                    details={"whole": whole, "whole_value": w, "part": part, "part_value": p},
                )
            )
    return findings


def run_validations(filing: CanonicalFilingFacts) -> tuple[ValidationResult, ...]:
    results: list[ValidationResult] = []
    for period_label in filing.period_labels:
        if (r := _balance_sheet_equation(filing, period_label)) is not None:
            results.append(r)
        if (r := _cash_tie_out(filing, period_label)) is not None:
            results.append(r)
        results.extend(_sign_sanity(filing, period_label))
    return tuple(results)
