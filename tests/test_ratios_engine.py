"""Tests for the Phase 6 calculation engine.

Builds `CanonicalFact` objects directly rather than going through
`resolver.resolve_filing` -- the whole point of the Phase 5/6 boundary
(`docs/canonical_schema.md` §16, phase brief §38) is that the ratio engine
only ever sees canonical facts, never XBRL/HTML/PDF. Real-corpus exercise
lives in `scripts/evaluate_ratios.py`, mirroring how `evaluate_canonicalization.py`
is where Phase 5's golden set is actually exercised rather than in tests.
"""

from __future__ import annotations

from datetime import date

from credit_risk_copilot.financials.models import (
    CanonicalFact,
    Confidence,
    FactStatus,
    ManualCorrection,
    Origin,
    Period,
    PeriodType,
    StatementType,
)
from credit_risk_copilot.ratios.engine import (
    calculate_ratio,
    calculate_ratio_history,
    calculate_ratios,
    ratio_history_changes,
    ratios_for_filing,
    ratios_from_facts,
)
from credit_risk_copilot.ratios.models import RatioStatus, WarningCode
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS, RATIOS_BY_ID

INSTANT_2025 = Period(period_type=PeriodType.INSTANT, end=date(2025, 12, 31))
INSTANT_2024 = Period(period_type=PeriodType.INSTANT, end=date(2024, 12, 31))
DURATION_2025 = Period(
    period_type=PeriodType.DURATION, start=date(2025, 1, 1), end=date(2025, 12, 31)
)
DURATION_2024 = Period(
    period_type=PeriodType.DURATION, start=date(2024, 1, 1), end=date(2024, 12, 31)
)

_INSTANT_CONCEPTS = {
    "cash",
    "accounts_receivable",
    "inventory",
    "current_assets",
    "total_assets",
    "current_liabilities",
    "total_liabilities",
    "short_term_debt",
    "long_term_debt",
    "total_debt",
    "shareholders_equity",
    "noncontrolling_interest",
    "total_equity",
}


def _period(period_label: str, concept: str) -> Period:
    year = int(period_label[2:6])
    if concept in _INSTANT_CONCEPTS:
        return {2025: INSTANT_2025, 2024: INSTANT_2024}[year]
    return {2025: DURATION_2025, 2024: DURATION_2024}[year]


def _fact(
    concept: str,
    value: float | None,
    *,
    period_label: str = "FY2025",
    status: FactStatus = FactStatus.FOUND,
    confidence: Confidence = Confidence.HIGH,
    origin: Origin = Origin.REPORTED,
    formula: str | None = None,
    reason: str | None = None,
    correction: ManualCorrection | None = None,
) -> CanonicalFact:
    return CanonicalFact(
        concept=concept,
        statement=StatementType.BALANCE_SHEET,
        period=_period(period_label, concept),
        value=value,
        status=status,
        confidence=confidence,
        origin=origin,
        formula=formula,
        reason=reason,
        correction=correction,
    )


def _facts_getter(facts: dict[tuple[str, str], CanonicalFact]):
    def get_fact(concept: str, period_label: str) -> CanonicalFact | None:
        return facts.get((concept, period_label))

    return get_fact


# --- Normal calculation -----------------------------------------------------


def test_current_ratio_calculates_normally() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", 1000),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["current_ratio"], "FY2025")

    assert result.status is RatioStatus.CALCULATED
    assert result.value == 2.0
    assert result.warnings == ()


def test_quick_ratio_sums_cash_and_receivables() -> None:
    facts = {
        ("cash", "FY2025"): _fact("cash", 300),
        ("accounts_receivable", "FY2025"): _fact("accounts_receivable", 200),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", 500),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["quick_ratio"], "FY2025")

    assert result.status is RatioStatus.CALCULATED
    assert result.value == 1.0  # (300 + 200) / 500


def test_interest_coverage_uses_ebit_over_interest_expense() -> None:
    facts = {
        ("ebit", "FY2025"): _fact(
            "ebit",
            270,
            status=FactStatus.DERIVED,
            origin=Origin.DERIVED,
            formula="pretax_income + interest_expense",
        ),
        ("interest_expense", "FY2025"): _fact("interest_expense", 100),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["interest_coverage"], "FY2025")

    assert result.status is RatioStatus.CALCULATED
    assert result.value == 2.7
    # ebit is DERIVED -- that is a real caveat and must surface.
    assert any(w.code is WarningCode.DERIVED_INPUT and w.concept == "ebit" for w in result.warnings)


# --- Missing input -----------------------------------------------------------


def test_missing_fact_produces_missing_input_status() -> None:
    facts = {("total_debt", "FY2025"): _fact("total_debt", 4200)}
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_equity"], "FY2025")

    assert result.status is RatioStatus.MISSING_INPUT
    assert result.value is None
    assert "shareholders_equity" in (result.reason or "")
    assert result.inputs["shareholders_equity"] is None
    assert result.missing_concepts == ("shareholders_equity",)
    assert result.conflicting_concepts == ()


def test_phase5_missing_status_also_counts_as_missing_input() -> None:
    """A Phase 5 `MISSING` placeholder (statement presented, line unresolved)
    is a different fact from no fact at all, but both mean 'no value'
    (canonical_schema.md §16) and must produce the same ratio status."""
    facts = {
        ("total_debt", "FY2025"): _fact("total_debt", 4200),
        ("shareholders_equity", "FY2025"): _fact(
            "shareholders_equity",
            None,
            status=FactStatus.MISSING,
            confidence=Confidence.LOW,
            reason="No sufficiently reliable source found.",
        ),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_equity"], "FY2025")

    assert result.status is RatioStatus.MISSING_INPUT
    assert result.inputs["shareholders_equity"] is not None  # the fact exists, just unresolved


# --- Conflicting input --------------------------------------------------------


def test_conflicting_input_takes_priority_over_missing() -> None:
    facts = {
        ("gross_profit", "FY2025"): _fact(
            "gross_profit",
            None,
            status=FactStatus.CONFLICTING,
            confidence=Confidence.LOW,
            reason="Tags disagree.",
        ),
        ("revenue", "FY2025"): _fact("revenue", 1000),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["gross_margin"], "FY2025")

    assert result.status is RatioStatus.CONFLICTING_INPUT
    assert "gross_profit" in (result.reason or "")
    assert result.conflicting_concepts == ("gross_profit",)
    assert result.missing_concepts == ()  # CONFLICTING, not MISSING -- must not double-count


def test_missing_concepts_is_empty_for_a_calculated_ratio() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", 1000),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["current_ratio"], "FY2025")

    assert result.missing_concepts == ()
    assert result.conflicting_concepts == ()


# --- Invalid denominator ------------------------------------------------------


def test_zero_denominator_is_invalid_not_infinite() -> None:
    facts = {
        ("total_debt", "FY2025"): _fact("total_debt", 4200),
        ("total_assets", "FY2025"): _fact("total_assets", 0),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_assets"], "FY2025")

    assert result.status is RatioStatus.INVALID_DENOMINATOR
    assert result.value is None


def test_negative_denominator_invalid_for_non_equity_ratio() -> None:
    """total_assets is conventionally non-negative; a negative value here is
    a data-quality signal, not a legitimate leverage measure."""
    facts = {
        ("total_liabilities", "FY2025"): _fact("total_liabilities", 100),
        ("total_assets", "FY2025"): _fact("total_assets", -50),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["liabilities_to_assets"], "FY2025")

    assert result.status is RatioStatus.INVALID_DENOMINATOR


def test_negative_equity_still_calculates_debt_to_equity_with_warning() -> None:
    """Negative equity is common among distressed filers and is exactly the
    signal a monitoring product must not hide (§10)."""
    facts = {
        ("total_debt", "FY2025"): _fact("total_debt", 2000),
        ("shareholders_equity", "FY2025"): _fact("shareholders_equity", -500),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_equity"], "FY2025")

    assert result.status is RatioStatus.CALCULATED
    assert result.value == -4.0
    assert any(
        w.code is WarningCode.NEGATIVE_EQUITY and w.concept == "shareholders_equity"
        for w in result.warnings
    )


def test_zero_equity_is_invalid_even_though_negative_is_allowed() -> None:
    facts = {
        ("total_debt", "FY2025"): _fact("total_debt", 2000),
        ("shareholders_equity", "FY2025"): _fact("shareholders_equity", 0),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_equity"], "FY2025")

    assert result.status is RatioStatus.INVALID_DENOMINATOR


# --- Quality warnings ----------------------------------------------------------


def test_interest_coverage_warns_when_interest_expense_is_small_relative_to_ebit() -> None:
    facts = {
        ("ebit", "FY2025"): _fact("ebit", 100_000),
        ("interest_expense", "FY2025"): _fact("interest_expense", 500),  # 0.5% of EBIT
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["interest_coverage"], "FY2025")

    assert result.status is RatioStatus.CALCULATED
    assert any(
        w.code is WarningCode.NEAR_ZERO_DENOMINATOR and w.concept == "interest_expense"
        for w in result.warnings
    )


def test_low_confidence_input_produces_a_warning() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000, confidence=Confidence.LOW),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", 1000),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["current_ratio"], "FY2025")

    assert any(
        w.code is WarningCode.LOW_CONFIDENCE_INPUT and w.concept == "current_assets"
        for w in result.warnings
    )


def test_manually_corrected_input_produces_a_warning_and_uses_corrected_value() -> None:
    correction = ManualCorrection(
        value=2500,
        reason="Analyst override",
        corrected_by="analyst@example.com",
        corrected_at="2026-01-01T00:00:00Z",
        previous_value=2000,
        previous_status=FactStatus.FOUND,
    )
    facts = {
        ("current_assets", "FY2025"): _fact(
            "current_assets", 2000, status=FactStatus.MANUALLY_CORRECTED, correction=correction
        ),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", 1000),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["current_ratio"], "FY2025")

    assert result.value == 2.5  # uses the corrected 2500, not the original 2000
    assert any(
        w.code is WarningCode.MANUAL_INPUT and w.concept == "current_assets"
        for w in result.warnings
    )


# --- Batch / multi-period -----------------------------------------------------


def test_calculation_method_is_explicit_for_roa_and_roe_and_absent_elsewhere() -> None:
    """D-020: ROA/ROE use ending balances, not averages -- this must be
    machine-readable on the result, not only documented in prose, so a
    caller can never mistake it for an average-balance figure."""
    facts = {
        ("net_income", "FY2025"): _fact("net_income", 620),
        ("total_assets", "FY2025"): _fact("total_assets", 10_000),
        ("shareholders_equity", "FY2025"): _fact("shareholders_equity", 4_000),
        ("current_assets", "FY2025"): _fact("current_assets", 2000),
        ("current_liabilities", "FY2025"): _fact("current_liabilities", 1000),
    }
    roa = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["roa"], "FY2025")
    roe = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["roe"], "FY2025")
    current_ratio = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["current_ratio"], "FY2025")

    assert roa.calculation_method == "ending_balance"
    assert roe.calculation_method == "ending_balance"
    assert current_ratio.calculation_method is None


def test_calculate_ratios_returns_every_definition() -> None:
    facts: dict[tuple[str, str], CanonicalFact] = {}
    result = calculate_ratios(_facts_getter(facts), "FY2025")
    assert {r.ratio_id for r in result} == {d.ratio_id for d in RATIO_DEFINITIONS}
    assert all(r.status is RatioStatus.MISSING_INPUT for r in result)


def test_multi_year_history_keeps_periods_separate() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000, period_label="FY2025"),
        ("current_liabilities", "FY2025"): _fact(
            "current_liabilities", 1000, period_label="FY2025"
        ),
        ("current_assets", "FY2024"): _fact("current_assets", 1500, period_label="FY2024"),
        ("current_liabilities", "FY2024"): _fact(
            "current_liabilities", 1000, period_label="FY2024"
        ),
    }
    history = calculate_ratio_history(_facts_getter(facts), ["FY2024", "FY2025"])
    series = history["current_ratio"]

    assert [r.period_label for r in series] == ["FY2024", "FY2025"]
    assert [r.value for r in series] == [1.5, 2.0]


def test_ratios_from_facts_adapts_a_company_as_of_dict() -> None:
    """`CompanyFinancials.as_of()` returns exactly this shape -- a plain
    dict keyed by (concept, period_label) -- with no need to import
    `financials.company` into the ratio engine."""
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000, period_label="FY2025"),
        ("current_liabilities", "FY2025"): _fact(
            "current_liabilities", 1000, period_label="FY2025"
        ),
    }
    history = ratios_from_facts(facts, ["FY2025"])
    assert history["current_ratio"][0].value == 2.0


class _FakeFiling:
    """Minimal stand-in for `CanonicalFilingFacts`: only `.get` and
    `.period_labels`, proving `ratios_for_filing` needs nothing more."""

    def __init__(self, facts: dict[tuple[str, str], CanonicalFact], period_labels: tuple[str, ...]):
        self._facts = facts
        self.period_labels = period_labels

    def get(self, concept: str, period_label: str) -> CanonicalFact | None:
        return self._facts.get((concept, period_label))


def test_ratios_for_filing_defaults_to_every_period_on_the_filing() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000, period_label="FY2025"),
        ("current_liabilities", "FY2025"): _fact(
            "current_liabilities", 1000, period_label="FY2025"
        ),
        ("current_assets", "FY2024"): _fact("current_assets", 1500, period_label="FY2024"),
        ("current_liabilities", "FY2024"): _fact(
            "current_liabilities", 1000, period_label="FY2024"
        ),
    }
    filing = _FakeFiling(facts, period_labels=("FY2024", "FY2025"))

    history = ratios_for_filing(filing)

    assert [r.period_label for r in history["current_ratio"]] == ["FY2024", "FY2025"]
    assert [r.value for r in history["current_ratio"]] == [1.5, 2.0]


def test_ratios_for_filing_honours_an_explicit_period_subset() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000, period_label="FY2025"),
        ("current_liabilities", "FY2025"): _fact(
            "current_liabilities", 1000, period_label="FY2025"
        ),
    }
    filing = _FakeFiling(facts, period_labels=("FY2024", "FY2025"))

    history = ratios_for_filing(filing, periods=["FY2025"])

    assert [r.period_label for r in history["current_ratio"]] == ["FY2025"]


def test_ratio_history_changes_computes_deterministic_deltas() -> None:
    facts = {
        ("current_assets", "FY2024"): _fact("current_assets", 1000, period_label="FY2024"),
        ("current_liabilities", "FY2024"): _fact(
            "current_liabilities", 1000, period_label="FY2024"
        ),
        ("current_assets", "FY2025"): _fact("current_assets", 2000, period_label="FY2025"),
        ("current_liabilities", "FY2025"): _fact(
            "current_liabilities", 1000, period_label="FY2025"
        ),
    }
    series = calculate_ratio_history(_facts_getter(facts), ["FY2024", "FY2025"])["current_ratio"]
    changes = ratio_history_changes(series)

    assert len(changes) == 1
    change = changes[0]
    assert change.from_period == "FY2024"
    assert change.to_period == "FY2025"
    assert change.from_value == 1.0
    assert change.to_value == 2.0
    assert change.absolute_change == 1.0
    assert change.percent_change == 1.0  # 100% increase


def test_ratio_history_changes_skips_pairs_where_either_side_is_unavailable() -> None:
    facts = {
        ("current_assets", "FY2025"): _fact("current_assets", 2000, period_label="FY2025"),
        ("current_liabilities", "FY2025"): _fact(
            "current_liabilities", 1000, period_label="FY2025"
        ),
    }
    series = calculate_ratio_history(_facts_getter(facts), ["FY2024", "FY2025"])["current_ratio"]
    changes = ratio_history_changes(series)

    assert changes == ()  # FY2024 side is MISSING_INPUT


# --- Provenance and explanation ------------------------------------------------


def test_ratio_result_inputs_reference_the_actual_canonical_facts() -> None:
    fact_assets = _fact("current_assets", 2000)
    fact_liabilities = _fact("current_liabilities", 1000)
    facts = {
        ("current_assets", "FY2025"): fact_assets,
        ("current_liabilities", "FY2025"): fact_liabilities,
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["current_ratio"], "FY2025")

    assert result.inputs["current_assets"] is fact_assets
    assert result.inputs["current_liabilities"] is fact_liabilities


def test_explain_includes_formula_and_input_values_for_calculated_ratio() -> None:
    facts = {
        ("total_debt", "FY2025"): _fact("total_debt", 4200),
        ("shareholders_equity", "FY2025"): _fact("shareholders_equity", 2414),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_equity"], "FY2025")
    text = result.explain()

    assert "Debt-to-Equity" in text
    assert "Total Debt / Shareholders' Equity" in text
    assert "4,200" in text
    assert "2,414" in text


def test_explain_states_the_reason_when_unavailable() -> None:
    facts: dict[tuple[str, str], CanonicalFact] = {}
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["debt_to_equity"], "FY2025")
    text = result.explain()

    assert "missing_input" in text
    assert "total_debt" in text
    assert "shareholders_equity" in text


def test_explain_formats_a_percent_ratio_and_lists_warnings() -> None:
    facts = {
        ("net_income", "FY2025"): _fact("net_income", 620),
        ("total_assets", "FY2025"): _fact(
            "total_assets", 10_000, confidence=Confidence.LOW, reason="Extension concept."
        ),
    }
    result = calculate_ratio(_facts_getter(facts), RATIOS_BY_ID["roa"], "FY2025")
    text = result.explain()

    assert "6.2%" in text  # 620 / 10,000
    assert "Warning:" in text
    assert "low-confidence" in text
