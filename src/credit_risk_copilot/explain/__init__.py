"""Phase 9: model explanation, grouped by financial dimension and traceable
back to filings.

    adapters.py   attribution methods (linear contributions, TreeSHAP) behind
                  one Protocol -- the only place `shap` is imported
    groups.py     model feature -> financial dimension / family / concepts
    schema.py     the domain explanation objects, library-independent
    local.py      one observation -> `ModelExplanation` with provenance

Nothing outside this package imports an attribution library, and nothing
inside it decides credit: an explanation says which input moved the model's
output, never that the input caused the event (D-003, D-010).
"""

from credit_risk_copilot.explain.adapters import (
    AttributionResult,
    Attributor,
    LinearContributions,
    TreeShapContributions,
    attributor_for,
)
from credit_risk_copilot.explain.groups import DIMENSIONS, dimension_of, family_of, group_of
from credit_risk_copilot.explain.local import explain_observation
from credit_risk_copilot.explain.schema import (
    Caveat,
    CaveatCode,
    DimensionAttribution,
    EvidenceLink,
    FeatureContribution,
    ModelExplanation,
)

__all__ = [
    "DIMENSIONS",
    "AttributionResult",
    "Attributor",
    "Caveat",
    "CaveatCode",
    "DimensionAttribution",
    "EvidenceLink",
    "FeatureContribution",
    "LinearContributions",
    "ModelExplanation",
    "TreeShapContributions",
    "attributor_for",
    "dimension_of",
    "explain_observation",
    "family_of",
    "group_of",
]
