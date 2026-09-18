"""Phase 5/6/7 outputs -> named, traceable model features (§13, §14).

Every feature in this module is a pure function of objects the earlier phases
already produce -- `CanonicalFact`, `RatioResult`, `RatioTrend`, `Signal` --
computed from a single `as_of` view of a company. Nothing here re-derives a
ratio, re-reads XBRL, or invents an accounting relationship: if a number is
not already available from Phase 5, 6 or 7, it is not a feature.

## Families exist so the ablation can be honest

Features are grouped into six families that stack in the order the pipeline
built them (§19). The ablation adds one family at a time, which answers the
question the phase brief actually cares about -- *did Phases 6 and 7 create
predictive information that the raw facts did not already carry* -- rather
than producing a table of many unrelated model variants.

    scale    how big the company is
    levels   balance-sheet and earnings composition, normalised by assets
    ratios   the Phase 6 catalog, as calculated
    trends   the Phase 7 direction and magnitude of each ratio's movement
    signals  the Phase 7 early-warning codes and dimension statuses
    quality  how complete and trustworthy the underlying data is

## `None` means "not computable", and it is never a zero

A missing feature is preserved as `None` all the way into `dataset.py`, which
emits an explicit missingness indicator beside it where the absence carries
information (§15). Collapsing "we could not compute leverage" into "leverage
is 0" would make a company with unreadable filings look like a company with no
debt, which is precisely the failure mode that a credit early-warning system
cannot afford.

## Provenance

`FEATURE_SPECS` records, for every feature, which family it belongs to and
which canonical concept, ratio id or signal code it came from. Combined with
`ObservationKey.contributing_accessions` that gives the full chain the product
requires (§14):

    feature -> spec.source_id -> ratio/concept -> CanonicalFact.provenance
            -> accession -> filing date
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.financials.models import CanonicalFact, FactStatus, Origin
from credit_risk_copilot.health.models import (
    DimensionStatus,
    EconomicDirection,
    FinancialHealthReport,
    SignalCode,
    TrendDirection,
)
from credit_risk_copilot.ratios.models import RatioResult, RatioStatus, WarningCode
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS

FeatureValues = dict[str, float | None]

#: The order families are stacked in for the ablation.
FAMILY_ORDER: tuple[str, ...] = ("scale", "levels", "ratios", "trends", "signals", "quality")

#: Concepts whose presence is counted for `fact_coverage`. Deliberately the
#: inputs the ratio catalog actually consumes rather than all 26 canonical
#: concepts -- coverage of a concept no ratio uses does not affect what the
#: model can see.
_RATIO_INPUT_CONCEPTS: tuple[str, ...] = tuple(
    sorted({concept for d in RATIO_DEFINITIONS for concept in d.inputs})
)

_RATIO_IDS: tuple[str, ...] = tuple(d.ratio_id for d in RATIO_DEFINITIONS)
_DIMENSIONS: tuple[str, ...] = tuple(dict.fromkeys(d.category for d in RATIO_DEFINITIONS))


class FeatureSpec(BaseModel):
    """What one feature is and where it came from."""

    model_config = ConfigDict(frozen=True)

    name: str
    family: str
    description: str
    #: `concept` | `ratio` | `trend` | `signal` | `dimension` | `derived` | `quality`
    source_kind: str
    #: The canonical concept, ratio id or signal code behind this feature;
    #: `None` for aggregates that span several.
    source_id: str | None = None


def _spec(
    name: str, family: str, source_kind: str, description: str, source_id: str | None = None
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        family=family,
        description=description,
        source_kind=source_kind,
        source_id=source_id,
    )


def _build_specs() -> tuple[FeatureSpec, ...]:
    specs: list[FeatureSpec] = [
        _spec(
            "log_total_assets",
            "scale",
            "concept",
            "Natural log of total assets. Logged because assets span five orders of magnitude "
            "across the corpus and a linear model would otherwise be dominated by the largest "
            "filers.",
            "total_assets",
        ),
        _spec(
            "log_revenue",
            "scale",
            "concept",
            "Natural log of revenue, same reasoning as log_total_assets.",
            "revenue",
        ),
        _spec(
            "working_capital_to_assets",
            "levels",
            "derived",
            "(current_assets - current_liabilities) / total_assets. Liquidity relative to size; "
            "the classic distress ratio the Phase 6 catalog does not carry because the catalog "
            "reports current_ratio as a multiple instead.",
        ),
        _spec(
            "cash_to_assets",
            "levels",
            "derived",
            "cash / total_assets -- the most liquid buffer, normalised by size.",
        ),
        _spec(
            "ebit_to_assets",
            "levels",
            "derived",
            "ebit / total_assets: operating earning power before financing structure. Distinct "
            "from roa, which the catalog computes on net income and is therefore affected by "
            "interest and tax.",
        ),
        _spec(
            "revenue_to_assets",
            "levels",
            "derived",
            "revenue / total_assets -- asset turnover; how much activity the asset base supports.",
        ),
        _spec(
            "fcf_to_assets",
            "levels",
            "derived",
            "(operating_cash_flow - capital_expenditures) / total_assets: cash generation after "
            "maintaining the asset base.",
        ),
        _spec(
            "retained_cash_flow_to_debt",
            "levels",
            "derived",
            "operating_cash_flow / total_debt; `None` when the company reports no debt, since "
            "cash coverage of nothing is undefined rather than infinitely good. Overlaps "
            "ocf_to_debt by design -- kept in levels so the ablation can see whether the ratio "
            "family adds anything beyond the raw normalisation.",
        ),
    ]

    for ratio_id in _RATIO_IDS:
        specs.append(
            _spec(
                f"ratio_{ratio_id}",
                "ratios",
                "ratio",
                f"Phase 6 `{ratio_id}` at the most recent period with a calculated value.",
                ratio_id,
            )
        )

    for ratio_id in _RATIO_IDS:
        specs.append(
            _spec(
                f"trend_pct_{ratio_id}",
                "trends",
                "trend",
                f"Phase 7 `percent_change` for `{ratio_id}` across the analysis window; `None` "
                "when the trend is not meaningful, discontinuous or too short.",
                ratio_id,
            )
        )
    specs.extend(
        [
            _spec(
                "n_deteriorating_ratios",
                "trends",
                "trend",
                "How many catalog ratios reached economic_direction=DETERIORATING.",
            ),
            _spec(
                "n_improving_ratios",
                "trends",
                "trend",
                "How many catalog ratios reached economic_direction=IMPROVING.",
            ),
            _spec(
                "max_deterioration_persistence",
                "trends",
                "trend",
                "The longest run of consecutive deteriorating period-over-period moves across "
                "any ratio -- Phase 7's persistence field, maximised.",
            ),
            _spec(
                "n_unusual_movements",
                "trends",
                "trend",
                "How many ratios flagged Phase 7's robust-z unusual_movement.",
            ),
        ]
    )

    for code in SignalCode:
        specs.append(
            _spec(
                f"signal_{code.value}",
                "signals",
                "signal",
                f"1.0 when Phase 7 raised `{code.value}` for this report, else 0.0.",
                code.value,
            )
        )
    for dimension in _DIMENSIONS:
        specs.append(
            _spec(
                f"dim_deteriorating_{dimension}",
                "signals",
                "dimension",
                f"1.0 when the `{dimension}` dimension status is DETERIORATING, 0.0 when it "
                "reached any other conclusive status, `None` when INSUFFICIENT_DATA.",
                dimension,
            )
        )

    specs.extend(
        [
            _spec(
                "ratio_coverage",
                "quality",
                "quality",
                "Share of the catalog that produced a CALCULATED value at the latest period. "
                "A monitoring-relevant feature in its own right: filings get harder to read as "
                "companies deteriorate.",
            ),
            _spec(
                "fact_coverage",
                "quality",
                "quality",
                "Share of the canonical concepts the ratio catalog consumes that resolved to a "
                "value at the latest period.",
            ),
            _spec(
                "periods_available",
                "quality",
                "quality",
                "How many fiscal periods of history back this observation, after the Phase 7 "
                "analysis window.",
            ),
            _spec(
                "derived_input_share",
                "quality",
                "quality",
                "Share of calculated ratios carrying a DERIVED_INPUT warning. Routine rather "
                "than alarming (total_debt and ebit are derived for most filers), included so "
                "the ablation can show whether it carries signal or merely noise.",
            ),
            _spec(
                "n_conflicting_ratios",
                "quality",
                "quality",
                "How many ratios could not be calculated because an input was CONFLICTING.",
            ),
        ]
    )
    return tuple(specs)


FEATURE_SPECS: tuple[FeatureSpec, ...] = _build_specs()
SPECS_BY_NAME: dict[str, FeatureSpec] = {spec.name: spec for spec in FEATURE_SPECS}
FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURE_SPECS)


def feature_names_for_families(families: tuple[str, ...]) -> tuple[str, ...]:
    """Feature names belonging to `families`, in `FEATURE_NAMES` order."""
    selected = set(families)
    return tuple(name for name in FEATURE_NAMES if SPECS_BY_NAME[name].family in selected)


def _value(
    facts: Mapping[tuple[str, str], CanonicalFact], concept: str, period: str
) -> float | None:
    fact = facts.get((concept, period))
    return fact.effective_value if fact is not None else None


def _safe_log(value: float | None) -> float | None:
    """Natural log, defined only for strictly positive values.

    A non-positive total-assets or revenue figure is not a small company, it
    is a data problem or a genuinely unusual filer; either way the log is
    undefined and `None` is the honest answer.
    """
    if value is None or value <= 0:
        return None
    return math.log(value)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1.0:
        return None
    return numerator / denominator


def _latest_calculated(results: tuple[RatioResult, ...]) -> RatioResult | None:
    for result in reversed(results):
        if result.status is RatioStatus.CALCULATED:
            return result
    return None


def build_features(
    *,
    facts: Mapping[tuple[str, str], CanonicalFact],
    period_label: str,
    ratio_history: Mapping[str, tuple[RatioResult, ...]],
    report: FinancialHealthReport,
) -> FeatureValues:
    """Every feature for one observation.

    `facts` is a `CompanyFinancials.as_of(cutoff)` view, `period_label` the
    most recent fiscal period it covers, `ratio_history` the Phase 6 output
    over that view and `report` the Phase 7 analysis of that history. All four
    describe the same information cutoff; `dataset.py` is what guarantees that.
    """
    values: FeatureValues = {}

    total_assets = _value(facts, "total_assets", period_label)
    revenue = _value(facts, "revenue", period_label)
    values["log_total_assets"] = _safe_log(total_assets)
    values["log_revenue"] = _safe_log(revenue)

    current_assets = _value(facts, "current_assets", period_label)
    current_liabilities = _value(facts, "current_liabilities", period_label)
    working_capital = (
        current_assets - current_liabilities
        if current_assets is not None and current_liabilities is not None
        else None
    )
    operating_cash_flow = _value(facts, "operating_cash_flow", period_label)
    capital_expenditures = _value(facts, "capital_expenditures", period_label)
    free_cash_flow = (
        operating_cash_flow - capital_expenditures
        if operating_cash_flow is not None and capital_expenditures is not None
        else None
    )

    values["working_capital_to_assets"] = _ratio(working_capital, total_assets)
    values["cash_to_assets"] = _ratio(_value(facts, "cash", period_label), total_assets)
    values["ebit_to_assets"] = _ratio(_value(facts, "ebit", period_label), total_assets)
    values["revenue_to_assets"] = _ratio(revenue, total_assets)
    values["fcf_to_assets"] = _ratio(free_cash_flow, total_assets)
    values["retained_cash_flow_to_debt"] = _ratio(
        operating_cash_flow, _value(facts, "total_debt", period_label)
    )

    for ratio_id in _RATIO_IDS:
        latest = _latest_calculated(tuple(ratio_history.get(ratio_id, ())))
        values[f"ratio_{ratio_id}"] = latest.value if latest is not None else None

    deteriorating = improving = unusual = 0
    persistence = 0
    for ratio_id in _RATIO_IDS:
        trend = report.trend(ratio_id)
        if trend is None:
            values[f"trend_pct_{ratio_id}"] = None
            continue
        conclusive = trend.direction in (
            TrendDirection.INCREASING,
            TrendDirection.DECREASING,
            TrendDirection.STABLE,
        )
        values[f"trend_pct_{ratio_id}"] = trend.percent_change if conclusive else None
        if trend.economic_direction is EconomicDirection.DETERIORATING:
            deteriorating += 1
            persistence = max(persistence, trend.persistence)
        elif trend.economic_direction is EconomicDirection.IMPROVING:
            improving += 1
        if trend.unusual_movement:
            unusual += 1

    values["n_deteriorating_ratios"] = float(deteriorating)
    values["n_improving_ratios"] = float(improving)
    values["max_deterioration_persistence"] = float(persistence)
    values["n_unusual_movements"] = float(unusual)

    raised = {signal.code for signal in report.signals}
    for code in SignalCode:
        values[f"signal_{code.value}"] = 1.0 if code in raised else 0.0
    for dimension in _DIMENSIONS:
        health = report.dimensions.get(dimension)
        if health is None or health.status is DimensionStatus.INSUFFICIENT_DATA:
            values[f"dim_deteriorating_{dimension}"] = None
        else:
            values[f"dim_deteriorating_{dimension}"] = (
                1.0 if health.status is DimensionStatus.DETERIORATING else 0.0
            )

    values.update(_quality_features(facts, period_label, ratio_history, report))
    return values


def _quality_features(
    facts: Mapping[tuple[str, str], CanonicalFact],
    period_label: str,
    ratio_history: Mapping[str, tuple[RatioResult, ...]],
    report: FinancialHealthReport,
) -> FeatureValues:
    latest_results = [
        result
        for ratio_id in _RATIO_IDS
        for result in ratio_history.get(ratio_id, ())
        if result.period_label == period_label
    ]
    calculated = [r for r in latest_results if r.status is RatioStatus.CALCULATED]
    conflicting = [r for r in latest_results if r.status is RatioStatus.CONFLICTING_INPUT]

    resolved_concepts = sum(
        1
        for concept in _RATIO_INPUT_CONCEPTS
        if (fact := facts.get((concept, period_label))) is not None
        and fact.status is not FactStatus.MISSING
        and fact.effective_value is not None
    )
    derived_flagged = sum(
        1
        for r in calculated
        if any(w.code is WarningCode.DERIVED_INPUT for w in r.warnings)
        or any(
            (fact := r.inputs.get(concept)) is not None and fact.origin is Origin.DERIVED
            for concept in r.inputs
        )
    )

    return {
        "ratio_coverage": len(calculated) / len(_RATIO_IDS),
        "fact_coverage": resolved_concepts / len(_RATIO_INPUT_CONCEPTS),
        "periods_available": float(len(report.periods_considered)),
        "derived_input_share": (derived_flagged / len(calculated)) if calculated else None,
        "n_conflicting_ratios": float(len(conflicting)),
    }
