"""Narrative risk signals from 10-K text, with verbatim evidence (Phase 10).

Reads the sections Phase 4 located, and reports what the filer *states* about
its own condition -- going-concern doubt, covenant breach, default,
restructuring -- each with the exact sentence it was found in and the filing it
came from (FR-14, SC-03).

The layer is rules-based by decision, not by default (A-15, D-035): every
signal traces to one editable pattern, which is what makes a false positive a
one-line fix rather than a retraining job.
"""

from credit_risk_copilot.nlp.catalog import CATALOG, CATALOG_VERSION, definition_for
from credit_risk_copilot.nlp.extract import (
    NARRATIVE_SECTIONS,
    analyze_document,
    extract_from_text,
    verify_quotes,
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

__all__ = [
    "CATALOG",
    "CATALOG_VERSION",
    "NARRATIVE_SECTIONS",
    "Assertion",
    "EvidenceQuote",
    "NarrativeRiskReport",
    "NarrativeRiskSignal",
    "RiskSignalCode",
    "SectionCoverage",
    "Specificity",
    "analyze_document",
    "definition_for",
    "extract_from_text",
    "verify_quotes",
]
