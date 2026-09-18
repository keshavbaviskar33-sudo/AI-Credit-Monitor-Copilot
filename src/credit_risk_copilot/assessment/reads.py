"""Projecting four incomparable outputs onto one three-valued axis.

A `DimensionStatus`, a signed TreeSHAP contribution and a regex hit on a
sentence have nothing in common until something says what each of them counts
as. This module is that something, and it is deliberately the smallest
translation that lets a rule compare two layers: `ELEVATED`, `QUIET`,
`UNKNOWN`, no ordering, no arithmetic.

Two aggregation choices do real work.

**Any elevated wins.** A layer reads `ELEVATED` on a dimension if *any* of its
items there is elevated, even when four others are quiet. Counting instead --
"three quiet beats one elevated" -- would be netting a deterioration against
unrelated stability, which is the exact operation Phase 7 refuses when it keeps
`MIXED` rather than averaging (D-022). It also fails unsafely: the cost of
surfacing a disagreement that turns out to be nothing is an analyst's minute,
and the cost of cancelling a real one is the product's purpose.

**`UNKNOWN` never decays to `QUIET`.** A layer that could not form a read is
not a layer reporting calm. Every rule below therefore requires both sides to
be non-`UNKNOWN` before it can fire -- a contradiction between a real finding
and an absence of data is not a contradiction, it is missing data, and it is
reported as coverage evidence instead.
"""

from __future__ import annotations

from collections.abc import Sequence

from credit_risk_copilot.assessment.models import Concern, EvidenceItem, EvidenceKind, LayerId
from credit_risk_copilot.nlp.models import Assertion, Specificity

#: The evidence kinds that carry a layer's *read*, as opposed to its supporting
#: detail. Ratio trends are excluded because the dimension status already
#: aggregates them, and a ratio change is excluded because a number moving is
#: not by itself a concern in either direction.
HEADLINE_KINDS: dict[LayerId, frozenset[EvidenceKind]] = {
    LayerId.FINANCIAL_HEALTH: frozenset(
        {EvidenceKind.DIMENSION_STATUS, EvidenceKind.HEALTH_SIGNAL}
    ),
    # Not `MODEL_DRIVER`: an attribution's sign says which way a feature pushed
    # this score, not whether the company is a concern. Only the ranking
    # position is a read (D-033).
    LayerId.PREDICTIVE_MODEL: frozenset({EvidenceKind.MODEL_SCORE}),
    LayerId.NARRATIVE: frozenset({EvidenceKind.NARRATIVE_SIGNAL}),
}


def _counts_as_narrative_read(item: EvidenceItem) -> bool:
    """Whether one narrative item may set the layer's read.

    A `LOW`-specificity assertion may not. Phase 10 measured
    `ASSET_IMPAIRMENT` as ordinary in healthy filers and `MATERIAL_WEAKNESS` at
    a lift of 1.16 -- close to no information -- and a layer read driven by
    those would make "the filing mentions an impairment" enough to contradict
    the model. The signal is still registered, still citable and still shown;
    it just does not get a vote on the layer's headline.

    An explicit denial (`NEGATED`) does get a vote, as `QUIET`: "we were in
    compliance with all covenants" is the filer stating the absence, which is a
    read, unlike the silence of a filing that never raises the subject.
    """
    specificity = item.detail.get("specificity")
    assertion = item.detail.get("assertion")
    if assertion == Assertion.NEGATED.value:
        return True
    if assertion != Assertion.ASSERTED.value:
        return False
    return specificity in (Specificity.HIGH.value, Specificity.MODERATE.value)


def _resolve(concerns: Sequence[Concern]) -> Concern:
    if Concern.ELEVATED in concerns:
        return Concern.ELEVATED
    if Concern.QUIET in concerns:
        return Concern.QUIET
    return Concern.UNKNOWN


def contributing(
    items: Sequence[EvidenceItem], layer: LayerId, *, dimension: str | None = None
) -> tuple[EvidenceItem, ...]:
    """The items that may set `layer`'s read, optionally on one dimension.

    Passing `dimension=None` means "every item from this layer", not "items
    with no dimension" -- the cross-cutting items (going-concern doubt, the
    model score) are exactly the ones a layer-level read must include.
    """
    selected = []
    for item in items:
        if item.layer is not layer:
            continue
        if item.kind not in HEADLINE_KINDS.get(layer, frozenset()):
            continue
        if dimension is not None and item.dimension != dimension:
            continue
        if layer is LayerId.NARRATIVE and not _counts_as_narrative_read(item):
            continue
        selected.append(item)
    return tuple(selected)


def read(items: Sequence[EvidenceItem], layer: LayerId, *, dimension: str | None = None) -> Concern:
    """One layer's read, resolved by "any elevated wins"."""
    return _resolve([item.concern for item in contributing(items, layer, dimension=dimension)])


def cited(
    items: Sequence[EvidenceItem],
    layer: LayerId,
    concern: Concern,
    *,
    dimension: str | None = None,
) -> tuple[str, ...]:
    """The evidence IDs behind a read -- what a finding points at.

    A finding cites the items that *produced* its side of the disagreement,
    never every item the layer emitted, so a reader opening a contradiction
    lands on the two or three facts in tension rather than on the register.
    """
    return tuple(
        item.evidence_id
        for item in contributing(items, layer, dimension=dimension)
        if item.concern is concern
    )
