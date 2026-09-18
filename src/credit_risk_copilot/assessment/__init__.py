"""Combining the analytical layers into one citable assessment (Phase 11).

Phases 6-10 each answer a different question about a company and none of them
answer it in the same type. This package puts the four outputs side by side,
gives every fact in them an address, and reports where they agree and where
they do not -- without producing a combined score, which the project has
refused on the same grounds since D-010.

    assessment = assemble_assessment(
        cik=320193, company="APPLE INC", as_of=date(2026, 1, 30),
        health=health_report, health_filing=FilingStamp(...),
        explanation=model_explanation, narrative=narrative_report,
    )
    assessment.contradictions      # FR-15, every side cited
    assessment.corroborations      # where independent methods agree
    assessment.validate_citations(drafted_ids)   # the mechanism behind FR-17
    compare(previous, assessment)  # FR-11

The as-of date is enforced, not documented: `AsOfGate` rejects any evidence
filed after it, which is what makes FR-05's historical replay a guarantee
rather than a convention.
"""

from credit_risk_copilot.assessment.asof import AsOfGate, AsOfViolation
from credit_risk_copilot.assessment.change import (
    AssessmentChange,
    ChangeKind,
    EvidenceChange,
    FindingChange,
    compare,
)
from credit_risk_copilot.assessment.contradictions import detect_contradictions
from credit_risk_copilot.assessment.corroboration import detect_corroboration
from credit_risk_copilot.assessment.engine import (
    EvidenceCollision,
    FilingStamp,
    assemble_assessment,
)
from credit_risk_copilot.assessment.evidence import (
    health_evidence,
    model_evidence,
    narrative_evidence,
)
from credit_risk_copilot.assessment.models import (
    Assessment,
    Concern,
    ContradictionCode,
    ContradictionFinding,
    CorroborationCode,
    CorroborationFinding,
    EvidenceItem,
    EvidenceKind,
    LayerAbsence,
    LayerId,
)
from credit_risk_copilot.assessment.reads import read

__all__ = [
    "AsOfGate",
    "AsOfViolation",
    "Assessment",
    "AssessmentChange",
    "ChangeKind",
    "Concern",
    "ContradictionCode",
    "ContradictionFinding",
    "CorroborationCode",
    "CorroborationFinding",
    "EvidenceChange",
    "EvidenceCollision",
    "EvidenceItem",
    "EvidenceKind",
    "FilingStamp",
    "FindingChange",
    "LayerAbsence",
    "LayerId",
    "assemble_assessment",
    "compare",
    "detect_contradictions",
    "detect_corroboration",
    "health_evidence",
    "model_evidence",
    "narrative_evidence",
    "read",
]
