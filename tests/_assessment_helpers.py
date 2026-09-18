"""Builders for Phase 11 (`assessment/`) tests.

Not a test module itself. Builds the three layer outputs directly rather than
running Phases 6-10, for the same reason `_health_helpers.py` builds
`RatioResult`s directly: `assessment/` consumes `FinancialHealthReport`,
`ModelExplanation` and `NarrativeRiskReport` and nothing below them, so its
tests should be able to state a scenario in one call instead of assembling a
filing.
"""

from __future__ import annotations

from datetime import date

from credit_risk_copilot.explain.schema import (
    Caveat,
    CaveatCode,
    DimensionAttribution,
    FeatureContribution,
    ModelExplanation,
)
from credit_risk_copilot.health.models import (
    DataQuality,
    DataQualityLevel,
    DimensionHealth,
    DimensionStatus,
    EconomicDirection,
    FinancialHealthReport,
    HistoryDepth,
    RatioTrend,
    Signal,
    SignalCode,
    TrendDirection,
)
from credit_risk_copilot.nlp.models import (
    Assertion,
    EvidenceQuote,
    NarrativeRiskReport,
    NarrativeRiskSignal,
    RiskSignalCode,
    SectionCoverage,
    Specificity,
)
from credit_risk_copilot.ratios.models import RatioResult, RatioStatus
from credit_risk_copilot.ratios.registry import RATIOS_BY_ID

FILED = date(2015, 3, 2)


def ratio_result(ratio_id: str, period_label: str, value: float | None) -> RatioResult:
    definition = RATIOS_BY_ID[ratio_id]
    return RatioResult(
        ratio_id=ratio_id,
        name=definition.name,
        category=definition.category,
        period_label=period_label,
        value=value,
        unit=definition.unit,
        status=RatioStatus.CALCULATED if value is not None else RatioStatus.MISSING_INPUT,
        formula=definition.formula,
        formula_display=definition.formula_display,
        inputs={},
    )


def trend(
    ratio_id: str,
    economic_direction: EconomicDirection,
    *,
    values: tuple[float, ...] = (1.0, 0.8),
    periods: tuple[str, ...] = ("FY2013", "FY2014"),
    persistence: int = 1,
) -> RatioTrend:
    direction = {
        EconomicDirection.DETERIORATING: TrendDirection.DECREASING,
        EconomicDirection.IMPROVING: TrendDirection.INCREASING,
        EconomicDirection.STABLE: TrendDirection.STABLE,
        EconomicDirection.INSUFFICIENT_DATA: TrendDirection.INSUFFICIENT_DATA,
        EconomicDirection.NOT_MEANINGFUL: TrendDirection.NOT_MEANINGFUL,
        EconomicDirection.DISCONTINUOUS_HISTORY: TrendDirection.DISCONTINUOUS_HISTORY,
    }[economic_direction]
    conclusive = economic_direction in (
        EconomicDirection.DETERIORATING,
        EconomicDirection.IMPROVING,
        EconomicDirection.STABLE,
    )
    return RatioTrend(
        ratio_id=ratio_id,
        results=tuple(ratio_result(ratio_id, p, v) for p, v in zip(periods, values, strict=True)),
        direction=direction,
        economic_direction=economic_direction,
        periods_available=len(values) if conclusive else 0,
        history_depth=HistoryDepth.ADEQUATE if conclusive else HistoryDepth.LIMITED,
        has_gap=False,
        gap_periods=(),
        absolute_change=(values[-1] - values[0]) if conclusive else None,
        percent_change=None,
        persistence=persistence if conclusive else 0,
        baseline_median=None,
        deviation_from_baseline=None,
        unusual_movement=False,
        negative_equity=False,
        data_quality=DataQualityLevel.GOOD,
        reason=None if conclusive else "test fixture: not conclusive",
    )


def health_report(
    *,
    company: str = "TEST CO",
    period_label: str = "FY2014",
    dimension_states: dict[str, EconomicDirection] | None = None,
    signals: tuple[Signal, ...] = (),
) -> FinancialHealthReport:
    """A report with one ratio per named dimension, in the given direction.

    One ratio per dimension is enough for every rule under test: the rules read
    a `DimensionStatus`, and Phase 7's own tests already cover how several
    ratios roll up into one.
    """
    states = dimension_states or {}
    representative = {
        "liquidity": "current_ratio",
        "leverage": "debt_to_equity",
        "profitability": "net_profit_margin",
        "coverage": "interest_coverage",
        "cash_flow": "ocf_to_revenue",
    }
    status_of = {
        EconomicDirection.DETERIORATING: DimensionStatus.DETERIORATING,
        EconomicDirection.IMPROVING: DimensionStatus.IMPROVING,
        EconomicDirection.STABLE: DimensionStatus.STABLE,
        EconomicDirection.INSUFFICIENT_DATA: DimensionStatus.INSUFFICIENT_DATA,
        EconomicDirection.NOT_MEANINGFUL: DimensionStatus.INSUFFICIENT_DATA,
        EconomicDirection.DISCONTINUOUS_HISTORY: DimensionStatus.INSUFFICIENT_DATA,
    }
    dimensions = {
        name: DimensionHealth(
            dimension=name,
            status=status_of[direction],
            ratio_trends=(trend(representative[name], direction),),
            signals=tuple(s for s in signals if s.category == name),
        )
        for name, direction in states.items()
    }
    return FinancialHealthReport(
        company=company,
        period_label=period_label,
        periods_considered=("FY2013", "FY2014"),
        analysis_window=5,
        dimensions=dimensions,
        signals=signals,
        changes_since_previous_period=(),
        data_quality=DataQuality(
            level=DataQualityLevel.GOOD,
            ratios_with_low_confidence_input=(),
            ratios_with_manual_correction=(),
            ratios_with_derived_input=(),
            ratios_with_limited_history=(),
        ),
    )


def health_signal(code: SignalCode, category: str, ratio_id: str) -> Signal:
    return Signal(
        code=code,
        category=category,
        ratio_id=ratio_id,
        trend=trend(ratio_id, EconomicDirection.DETERIORATING),
        evidence=f"{ratio_id} fell for 2 consecutive periods",
    )


def explanation(
    *,
    score: float = 0.4,
    percentile: float | None = 95.0,
    dimensions: dict[str, float] | None = None,
    missingness_contribution: float = 0.0,
    caveats: tuple[Caveat, ...] = (
        Caveat(code=CaveatCode.BASE_RATE_NOT_PORTFOLIO, message="Training base rate is a design."),
    ),
    prediction_date: date = FILED,
) -> ModelExplanation:
    """A model explanation whose attribution is stated per dimension.

    `dimensions` maps a dimension to its total contribution; shares are derived
    so that `share_of_absolute` is consistent with them, because the
    materiality floor in `contradictions.py` reads that field and a fixture
    with an incoherent share would test the floor against a number no real
    explanation could produce.
    """
    groups = dict(dimensions or {"leverage": 0.9})
    contributions: list[FeatureContribution] = []
    for name, value in groups.items():
        contributions.append(
            FeatureContribution(
                feature=f"ratio_{name}_proxy",
                family="ratios",
                dimension=name,
                value=1.0,
                is_missingness_indicator=False,
                contribution=value,
                raises_risk=value > 0,
                source_kind="ratio",
                source_id=name,
            )
        )
    if missingness_contribution:
        contributions.append(
            FeatureContribution(
                feature="ratio_gross_margin__missing",
                family="quality",
                dimension=None,
                value=1.0,
                is_missingness_indicator=True,
                contribution=missingness_contribution,
                raises_risk=missingness_contribution > 0,
                source_kind="quality",
                source_id="gross_margin",
            )
        )
    total = sum(abs(c.contribution) for c in contributions) or 1.0
    by_dimension = tuple(
        DimensionAttribution(
            group=name,
            contribution=value,
            share_of_absolute=abs(value) / total,
            feature_count=1,
            top_features=(),
        )
        for name, value in groups.items()
    )
    if missingness_contribution:
        by_dimension += (
            DimensionAttribution(
                group="missingness",
                contribution=missingness_contribution,
                share_of_absolute=abs(missingness_contribution) / total,
                feature_count=1,
                top_features=(),
            ),
        )
    return ModelExplanation(
        cik=1,
        company="TEST CO",
        prediction_date=prediction_date,
        fiscal_period_label="FY2014",
        source_accession="0000000000-15-000001",
        model_name="gradient_boosting_all",
        model_family="gradient_boosting",
        attribution_method="tree_shap",
        score=score,
        baseline=0.1,
        score_percentile=percentile,
        contributions=tuple(contributions),
        by_dimension=by_dimension,
        caveats=caveats,
    )


def narrative_signal(
    code: RiskSignalCode,
    assertion: Assertion,
    *,
    specificity: Specificity = Specificity.HIGH,
    text: str = "There is substantial doubt about our ability to continue as a going concern.",
    section_id: str = "item_7",
    char_start: int = 100,
) -> NarrativeRiskSignal:
    return NarrativeRiskSignal(
        code=code,
        label=code.value.replace("_", " ").capitalize(),
        assertion=assertion,
        specificity=specificity,
        pattern_id=f"test.{code.value}",
        quote=EvidenceQuote(
            text=text,
            char_start=char_start,
            char_end=char_start + len(text),
            section_id=section_id,
            trigger_start=0,
            trigger_end=5,
        ),
    )


def narrative_report(
    *,
    signals: tuple[NarrativeRiskSignal, ...] = (),
    missing_sections: tuple[str, ...] = (),
    located_sections: tuple[str, ...] = ("item_1a", "item_7"),
    filed: date = FILED,
) -> NarrativeRiskReport:
    coverage = tuple(
        SectionCoverage(section_id=s, located=True, characters=1000, sentences=50)
        for s in located_sections
    ) + tuple(
        SectionCoverage(section_id=s, located=False, reason="heading not found")
        for s in missing_sections
    )
    return NarrativeRiskReport(
        cik=1,
        company="TEST CO",
        accession="0000000000-15-000001",
        form="10-K",
        filed=filed.isoformat(),
        signals=signals,
        coverage=coverage,
    )
