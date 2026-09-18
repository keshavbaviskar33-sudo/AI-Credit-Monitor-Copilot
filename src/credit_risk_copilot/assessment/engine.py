"""Assembling one company's assessment from whichever layers ran.

The assembly is deliberately boring: register what each layer produced, refuse
anything dated after the as-of date, run the rules, record what is missing.
All the judgement lives in `evidence.py` (what counts as a fact),
`reads.py` (what counts as a concern) and the two rule modules; this file only
has to make sure nothing is dropped and nothing is invented.

## Every layer is optional and every absence is recorded

A caller can legitimately have no model explanation -- the company may be
outside the model's training range, or scoring may have failed -- and the
assessment is still worth producing. What it must never do is look the same as
an assessment where the model ran and found nothing. `layers_absent` carries
the reason, and it is required rather than defaulted, because a default reason
is the same as no reason.

## A hash collision is an error, not a tie-break

Two evidence items with identical content are one item and are deduplicated
silently. Two *different* items sharing an ID are a 32-bit collision, and
letting the second overwrite the first would corrupt every citation that
resolves to it. The assembly raises instead. This is expected roughly never;
it is checked because the failure mode is silent and permanent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from credit_risk_copilot.assessment.asof import AsOfGate
from credit_risk_copilot.assessment.contradictions import detect_contradictions
from credit_risk_copilot.assessment.corroboration import detect_corroboration
from credit_risk_copilot.assessment.evidence import (
    health_evidence,
    model_evidence,
    narrative_evidence,
)
from credit_risk_copilot.assessment.models import (
    Assessment,
    EvidenceItem,
    LayerAbsence,
    LayerId,
)
from credit_risk_copilot.explain.schema import ModelExplanation
from credit_risk_copilot.health.models import FinancialHealthReport
from credit_risk_copilot.nlp.models import NarrativeRiskReport


class EvidenceCollision(RuntimeError):
    """Two different evidence items produced the same ID."""


@dataclass(frozen=True)
class FilingStamp:
    """The filing a Phase 7 report's window closed on.

    A `FinancialHealthReport` spans several filings and belongs to none of
    them, so it cannot say when it became knowable. The caller that built the
    window can, and has to: without this the as-of gate would have to wave
    every health item through, and the gate would then only be checking the
    layers that happened to carry their own dates.
    """

    accession: str | None
    form: str | None
    filed: date | None


def _merge(items: Sequence[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    merged: dict[str, EvidenceItem] = {}
    for item in items:
        existing = merged.get(item.evidence_id)
        if existing is None:
            merged[item.evidence_id] = item
            continue
        if existing == item:
            continue
        raise EvidenceCollision(
            f"{item.evidence_id} is claimed by two different items:"
            f" {existing.identity_key!r} and {item.identity_key!r}"
        )
    return tuple(merged.values())


def assemble_assessment(
    *,
    cik: int,
    company: str,
    as_of: date,
    health: FinancialHealthReport | None = None,
    health_filing: FilingStamp | None = None,
    health_absent_reason: str | None = None,
    explanation: ModelExplanation | None = None,
    model_absent_reason: str | None = None,
    narrative: NarrativeRiskReport | None = None,
    narrative_absent_reason: str | None = None,
    pipeline_versions: Mapping[str, str] | None = None,
    gate: AsOfGate | None = None,
) -> Assessment:
    """Combine whichever layers ran into one citable, gated assessment.

    `health_filing` is required whenever `health` is supplied: see
    `FilingStamp`. Each `*_absent_reason` is required whenever its layer is
    `None`, so that an assessment can always answer "why is this missing?".
    """
    items: list[EvidenceItem] = []
    present: list[LayerId] = []
    absent: list[LayerAbsence] = []

    if health is not None:
        if health_filing is None:
            raise ValueError(
                "health_filing is required with health: the as-of gate cannot verify a"
                " financial-health report that does not say which filing closed its window"
            )
        items += health_evidence(
            health,
            accession=health_filing.accession,
            form=health_filing.form,
            filed=health_filing.filed,
        )
        present.append(LayerId.FINANCIAL_HEALTH)
    else:
        if not health_absent_reason:
            raise ValueError("health_absent_reason is required when no health report is supplied")
        absent.append(LayerAbsence(layer=LayerId.FINANCIAL_HEALTH, reason=health_absent_reason))

    if explanation is not None:
        items += model_evidence(explanation)
        present.append(LayerId.PREDICTIVE_MODEL)
    else:
        if not model_absent_reason:
            raise ValueError("model_absent_reason is required when no explanation is supplied")
        absent.append(LayerAbsence(layer=LayerId.PREDICTIVE_MODEL, reason=model_absent_reason))

    if narrative is not None:
        items += narrative_evidence(narrative)
        present.append(LayerId.NARRATIVE)
    else:
        if not narrative_absent_reason:
            raise ValueError(
                "narrative_absent_reason is required when no narrative report is supplied"
            )
        absent.append(LayerAbsence(layer=LayerId.NARRATIVE, reason=narrative_absent_reason))

    evidence = _merge(items)
    (gate or AsOfGate(as_of=as_of)).verify(evidence)

    versions = dict(pipeline_versions or {})
    if narrative is not None:
        versions.setdefault("nlp_catalog", narrative.catalog_version)
    if explanation is not None:
        versions.setdefault("model", explanation.model_name)
        versions.setdefault("attribution", explanation.attribution_method)

    # The period this assessment describes. Taken from the health layer first
    # because its window is the widest; the model's fiscal period is the same
    # filing's, and the narrative layer does not carry a fiscal period at all.
    period_label = None
    if health is not None:
        period_label = health.period_label
    elif explanation is not None:
        period_label = explanation.fiscal_period_label

    return Assessment(
        cik=cik,
        company=company,
        as_of=as_of,
        period_label=period_label,
        evidence=evidence,
        contradictions=detect_contradictions(evidence),
        corroborations=detect_corroboration(evidence),
        layers_present=tuple(present),
        layers_absent=tuple(absent),
        pipeline_versions=versions,
    )
