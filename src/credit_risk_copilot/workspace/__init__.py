"""View models for the analyst workspace (Phase 14).

Pure Python: nothing here imports Streamlit, so the decisions that matter --
what a layer's read *is*, why a company reaches the desk, which figures are
real -- are unit-tested without a browser and the UI stays replaceable.

    panel = load_panel()
    with ReviewStore(DEFAULT_DB) as store:
        cards = coverage(store, panel)                       # the desk
        workspace = build_workspace(store, history, panel)   # one company

The centrepiece is `three_reads()`: the financial trends, the model ranking
and the filer's own words, side by side, each with its own evidence. There is
no combined score anywhere in this package, because the system behind it does
not produce one.
"""

from credit_risk_copilot.workspace.build import (
    DEFAULT_DB,
    PANEL_PATH,
    SCALE_FIELDS,
    SEVERE_CODES,
    attention_reasons,
    build_card,
    build_workspace,
    caveats,
    coverage,
    coverage_gaps,
    describe,
    drivers,
    format_currency,
    format_percent,
    format_ratio,
    group_by_attention,
    load_panel,
    narrative_items,
    ratio_series,
    scale_history,
    state_label,
    three_reads,
)
from credit_risk_copilot.workspace.models import (
    ATTENTION_EXPLANATIONS,
    ATTENTION_ORDER,
    CONCERN_COLORS,
    CONCERN_ICONS,
    CONCERN_LABELS,
    LAYER_METHODS,
    LAYER_TITLES,
    CompanyCard,
    CompanyWorkspace,
    CoverageGap,
    DriverBar,
    LayerRead,
    MetricPoint,
    NarrativeItem,
    RatioSeries,
)

__all__ = [
    "ATTENTION_EXPLANATIONS",
    "ATTENTION_ORDER",
    "CONCERN_COLORS",
    "CONCERN_ICONS",
    "CONCERN_LABELS",
    "DEFAULT_DB",
    "LAYER_METHODS",
    "LAYER_TITLES",
    "PANEL_PATH",
    "SCALE_FIELDS",
    "SEVERE_CODES",
    "CompanyCard",
    "CompanyWorkspace",
    "CoverageGap",
    "DriverBar",
    "LayerRead",
    "MetricPoint",
    "NarrativeItem",
    "RatioSeries",
    "attention_reasons",
    "build_card",
    "build_workspace",
    "caveats",
    "coverage",
    "coverage_gaps",
    "describe",
    "drivers",
    "format_currency",
    "format_percent",
    "format_ratio",
    "group_by_attention",
    "load_panel",
    "narrative_items",
    "ratio_series",
    "scale_history",
    "state_label",
    "three_reads",
]
