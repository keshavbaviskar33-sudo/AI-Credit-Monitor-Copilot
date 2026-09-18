"""Mapping model features onto the dimensions an analyst already thinks in.

A ranked list of 57 features is not an explanation of a credit model; it is a
different presentation of the coefficient vector. Two things make it
misleading:

- **Correlation.** `debt_to_assets`, `debt_to_equity` and
  `liabilities_to_assets` measure one economic idea three ways. Every additive
  attribution method -- coefficients, SHAP, anything else -- splits a shared
  effect among them in a way that is arbitrary between them and stable across
  them. Ranking the three individually invites a reader to conclude something
  about which leverage measure "matters", which the data does not support.
- **Vocabulary.** An analyst reasons about liquidity, leverage, profitability,
  coverage and cash flow -- the same five dimensions Phase 7 already reports
  (`health/dimensions.py`). Explanations that speak in those terms can be
  challenged; explanations that speak in feature names can only be accepted.

So this module defines two grouping axes over the same features, plus one
cross-cutting group:

    dimension   liquidity / leverage / profitability / coverage / cash_flow
    family      scale / levels / ratios / trends / signals / quality
    missingness every `<name>__missing` indicator, regardless of the above

Dimensions are derived from Phase 6's own `RatioDefinition.category` wherever a
feature descends from a ratio, so the two catalogs cannot drift apart. Where a
feature has no financial dimension -- company size, data-quality measures --
that is recorded as `None` rather than forced into one.
"""

from __future__ import annotations

from credit_risk_copilot.health.models import SignalCode
from credit_risk_copilot.modeling.features import SPECS_BY_NAME
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS, RATIOS_BY_ID

#: Suffix `model.design_matrix` appends for a missingness indicator column.
MISSING_SUFFIX = "__missing"

#: The cross-cutting group name used for missingness indicators.
MISSINGNESS_GROUP = "missingness"

#: The five financial dimensions, taken from the Phase 6 catalog's own
#: categories rather than redeclared.
DIMENSIONS: tuple[str, ...] = tuple(dict.fromkeys(d.category for d in RATIO_DEFINITIONS))

#: `levels` features are hand-mapped because they are derived in Phase 8
#: rather than being catalog ratios, so no `category` exists to inherit. Each
#: assignment is the dimension an analyst would file the quantity under.
_LEVEL_DIMENSIONS: dict[str, str] = {
    "working_capital_to_assets": "liquidity",
    "cash_to_assets": "liquidity",
    "ebit_to_assets": "profitability",
    "revenue_to_assets": "profitability",
    "fcf_to_assets": "cash_flow",
    "retained_cash_flow_to_debt": "cash_flow",
}

#: Signal codes to dimensions. Mirrors `health/signals.py::_DETERIORATION_SIGNAL`
#: inverted; the two cross-cutting codes have no single dimension.
_SIGNAL_DIMENSIONS: dict[str, str | None] = {
    SignalCode.LIQUIDITY_DETERIORATION.value: "liquidity",
    SignalCode.LEVERAGE_DETERIORATION.value: "leverage",
    SignalCode.MARGIN_COMPRESSION.value: "profitability",
    SignalCode.PROFITABILITY_DETERIORATION.value: "profitability",
    SignalCode.INTEREST_COVERAGE_DECLINE.value: "coverage",
    SignalCode.CASH_FLOW_WEAKENING.value: "cash_flow",
    SignalCode.NEGATIVE_EQUITY.value: "leverage",
    SignalCode.UNUSUAL_MOVEMENT.value: None,
    SignalCode.MULTI_DIMENSION_DETERIORATION.value: None,
}


def base_feature(name: str) -> str:
    """The financial feature a column refers to, with any missingness suffix
    stripped. `ratio_roa__missing` and `ratio_roa` share a base feature, which
    is what lets a missingness indicator be filed under the same dimension as
    the value it is about."""
    return name[: -len(MISSING_SUFFIX)] if name.endswith(MISSING_SUFFIX) else name


def is_missingness_indicator(name: str) -> bool:
    return name.endswith(MISSING_SUFFIX)


def family_of(name: str) -> str:
    """The Phase 8 feature family, or `"missingness"` for an indicator column.

    An indicator is deliberately *not* filed under its base feature's family:
    §13 of the phase brief turns on being able to separate "the model reacted
    to leverage" from "the model reacted to leverage being unavailable", and
    that separation has to survive into the grouping.
    """
    if is_missingness_indicator(name):
        return MISSINGNESS_GROUP
    spec = SPECS_BY_NAME.get(name)
    return spec.family if spec else "unknown"


def dimension_of(name: str) -> str | None:
    """The financial dimension a feature belongs to, or `None`.

    `None` is a real answer, not a gap: company size and data-quality
    measures genuinely do not belong to liquidity or leverage, and assigning
    them to one would misrepresent what the model is reacting to.
    """
    base = base_feature(name)
    spec = SPECS_BY_NAME.get(base)
    if spec is None:
        return None

    if spec.family == "ratios" and spec.source_id:
        definition = RATIOS_BY_ID.get(spec.source_id)
        return definition.category if definition else None
    if spec.family == "trends":
        if spec.source_id and spec.source_id in RATIOS_BY_ID:
            return RATIOS_BY_ID[spec.source_id].category
        return None  # the trend aggregates span every dimension
    if spec.family == "levels":
        return _LEVEL_DIMENSIONS.get(base)
    if spec.family == "signals":
        if spec.source_kind == "dimension":
            return spec.source_id
        return _SIGNAL_DIMENSIONS.get(spec.source_id or "")
    # `scale` (company size) and `quality` (data availability) have none.
    return None


def group_of(name: str, *, axis: str = "dimension") -> str:
    """The group a feature falls in on one axis, as a non-null label.

    `axis="dimension"` buckets everything without a financial dimension into
    named residual groups (`size`, `data_quality`, `cross_cutting`,
    `missingness`) rather than a single `None` bucket, so a reader can tell
    "the model is reacting to company size" apart from "the model is reacting
    to something uncategorised".
    """
    if axis == "family":
        return family_of(name)
    if axis != "dimension":
        raise ValueError(f"Unknown grouping axis: {axis!r}")

    if is_missingness_indicator(name):
        return MISSINGNESS_GROUP
    dimension = dimension_of(name)
    if dimension is not None:
        return dimension
    family = family_of(name)
    if family == "scale":
        return "size"
    if family == "quality":
        return "data_quality"
    return "cross_cutting"


def ratio_inputs(name: str) -> tuple[str, ...]:
    """The canonical concepts behind a feature, for the provenance chain.

    This is the hop from a model feature to Phase 5 facts: a ratio feature
    resolves to its `RatioDefinition.inputs`, a concept feature to itself, and
    anything aggregate to nothing (an aggregate spans too many facts for a
    single evidence link to be meaningful).
    """
    base = base_feature(name)
    spec = SPECS_BY_NAME.get(base)
    if spec is None:
        return ()
    if spec.source_kind == "concept" and spec.source_id:
        return (spec.source_id,)
    if spec.family in {"ratios", "trends"} and spec.source_id in RATIOS_BY_ID:
        return RATIOS_BY_ID[spec.source_id].inputs
    if spec.family == "levels":
        return _LEVEL_CONCEPTS.get(base, ())
    return ()


#: Canonical concepts each Phase 8 `levels` feature is computed from, so a
#: derived feature can still reach a filing. Kept beside `_LEVEL_DIMENSIONS`
#: and mirroring `features.build_features`'s own arithmetic.
_LEVEL_CONCEPTS: dict[str, tuple[str, ...]] = {
    "working_capital_to_assets": ("current_assets", "current_liabilities", "total_assets"),
    "cash_to_assets": ("cash", "total_assets"),
    "ebit_to_assets": ("ebit", "total_assets"),
    "revenue_to_assets": ("revenue", "total_assets"),
    "fcf_to_assets": ("operating_cash_flow", "capital_expenditures", "total_assets"),
    "retained_cash_flow_to_debt": ("operating_cash_flow", "total_debt"),
}
