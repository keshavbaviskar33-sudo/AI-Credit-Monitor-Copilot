"""Independent agreement between layers.

The mirror of `contradictions.py`, and the only place this project can
honestly raise confidence rather than qualify it. The three analytical layers
share the filing and nothing else: Phase 7 reads XBRL facts through a ratio
catalog, Phase 8/9 reads a fitted hazard model's features, Phase 10 reads
English sentences with a regex and a mood classifier. Their failure modes are
unrelated -- a mis-mapped XBRL tag does not make a filer write "substantial
doubt", and a false-positive pattern does not move a current ratio -- so
agreement between them is not one piece of evidence counted three times.

**What agreement is still not.** It is not a probability, not a confidence
percentage, and not a score. `CorroborationFinding.layers` is a tuple of layer
names, so a reader sees *which* methods agree and can weigh them; the only
quantity is the length of that tuple, and two-layer agreement is reported as a
different finding from three-layer agreement rather than as 0.67 of it.
"""

from __future__ import annotations

from collections.abc import Sequence

from credit_risk_copilot.assessment import reads
from credit_risk_copilot.assessment.evidence import high_specificity_codes
from credit_risk_copilot.assessment.models import (
    Concern,
    CorroborationCode,
    CorroborationFinding,
    EvidenceItem,
    EvidenceKind,
    LayerId,
)
from credit_risk_copilot.health.dimensions import DIMENSIONS


def _all_layers(items: Sequence[EvidenceItem]) -> list[CorroborationFinding]:
    layers = (LayerId.FINANCIAL_HEALTH, LayerId.PREDICTIVE_MODEL, LayerId.NARRATIVE)
    if any(reads.read(items, layer) is not Concern.ELEVATED for layer in layers):
        return []
    supporting = tuple(
        evidence_id
        for layer in layers
        for evidence_id in reads.cited(items, layer, Concern.ELEVATED)
    )
    return [
        CorroborationFinding(
            code=CorroborationCode.ALL_LAYERS_ELEVATED,
            dimension=None,
            layers=layers,
            supporting=supporting,
            explanation=(
                "All three independent layers point the same way: the ratio trends are"
                " deteriorating, the model ranks the company high, and the filer states a"
                " risk condition about itself."
            ),
        )
    ]


def _health_and_narrative(items: Sequence[EvidenceItem]) -> list[CorroborationFinding]:
    findings = []
    for dimension in sorted(DIMENSIONS):
        health = reads.read(items, LayerId.FINANCIAL_HEALTH, dimension=dimension)
        narrative = reads.read(items, LayerId.NARRATIVE, dimension=dimension)
        if health is not Concern.ELEVATED or narrative is not Concern.ELEVATED:
            continue
        findings.append(
            CorroborationFinding(
                code=CorroborationCode.HEALTH_AND_NARRATIVE,
                dimension=dimension,
                layers=(LayerId.FINANCIAL_HEALTH, LayerId.NARRATIVE),
                supporting=(
                    reads.cited(
                        items, LayerId.FINANCIAL_HEALTH, Concern.ELEVATED, dimension=dimension
                    )
                    + reads.cited(items, LayerId.NARRATIVE, Concern.ELEVATED, dimension=dimension)
                ),
                explanation=(
                    f"On {dimension}, the computed ratio trends and the filer's own"
                    " statements agree, from independent sources in the same filing."
                ),
            )
        )
    return findings


def _model_and_health(items: Sequence[EvidenceItem]) -> list[CorroborationFinding]:
    """The model's largest risk-raising dimension is one the ratios also flag.

    Restricted to the *largest* such driver rather than every agreeing one.
    With five dimensions and a model that always attributes something to each,
    reporting every match would make agreement look inevitable; the leading
    driver is the one claim about the model that is worth corroborating.
    """
    drivers = [
        item
        for item in items
        if item.kind is EvidenceKind.MODEL_DRIVER
        and item.dimension is not None
        and item.concern is Concern.ELEVATED
    ]
    if not drivers:
        return []
    top = max(
        drivers,
        # Ties broken on the dimension name so the result does not depend on
        # the order `by_dimension` happened to arrive in.
        key=lambda item: (float(item.detail.get("share_of_absolute") or 0.0), item.dimension or ""),
    )
    dimension = top.dimension
    assert dimension is not None
    if reads.read(items, LayerId.FINANCIAL_HEALTH, dimension=dimension) is not Concern.ELEVATED:
        return []
    return [
        CorroborationFinding(
            code=CorroborationCode.MODEL_AND_HEALTH,
            dimension=dimension,
            layers=(LayerId.PREDICTIVE_MODEL, LayerId.FINANCIAL_HEALTH),
            supporting=(top.evidence_id,)
            + reads.cited(items, LayerId.FINANCIAL_HEALTH, Concern.ELEVATED, dimension=dimension),
            explanation=(
                f"{dimension} is the model's largest risk-raising attribution and is"
                " independently deteriorating in the ratio trends."
            ),
        )
    ]


def _model_and_narrative(items: Sequence[EvidenceItem]) -> list[CorroborationFinding]:
    severe = high_specificity_codes(items)
    if not severe:
        return []
    if reads.read(items, LayerId.PREDICTIVE_MODEL) is not Concern.ELEVATED:
        return []
    codes = ", ".join(sorted({str(item.detail.get("code")) for item in severe}))
    return [
        CorroborationFinding(
            code=CorroborationCode.MODEL_AND_NARRATIVE,
            dimension=None,
            layers=(LayerId.PREDICTIVE_MODEL, LayerId.NARRATIVE),
            supporting=reads.cited(items, LayerId.PREDICTIVE_MODEL, Concern.ELEVATED)
            + tuple(item.evidence_id for item in severe),
            explanation=(
                f"The model ranks this company high and the filer states {codes} about"
                " itself -- a fitted model and the filer's own words, agreeing."
            ),
        )
    ]


def detect_corroboration(items: Sequence[EvidenceItem]) -> tuple[CorroborationFinding, ...]:
    """Every agreement rule, in a deterministic order.

    The three-layer finding is emitted alongside the two-layer ones rather than
    suppressing them: they cite different evidence, and a reader who discounts
    one layer still needs to see what the other two agreed on.
    """
    findings: list[CorroborationFinding] = []
    findings += _all_layers(items)
    findings += _model_and_narrative(items)
    findings += _model_and_health(items)
    findings += _health_and_narrative(items)
    return tuple(findings)
