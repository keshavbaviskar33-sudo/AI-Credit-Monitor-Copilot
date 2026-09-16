"""Canonical financial-fact schema and XBRL-driven resolution.

Turns Phase 4's located-but-uninterpreted evidence into typed, provenance-
carrying financial facts (`docs/canonical_schema.md`). For US SEC filers,
XBRL is the source of record (D-005); `resolver.resolve_filing` is the main
entry point, and `reconciliation.corroborate_filing` optionally cross-checks
its output against a filing's own HTML tables.
"""

from credit_risk_copilot.financials.company import CompanyFinancials, Restatement
from credit_risk_copilot.financials.concept_map import CONCEPT_DEFINITIONS, CONCEPTS_BY_ID
from credit_risk_copilot.financials.models import (
    CandidateValue,
    CanonicalFact,
    CanonicalFilingFacts,
    Confidence,
    FactStatus,
    ManualCorrection,
    Origin,
    Period,
    PeriodType,
    Provenance,
    SourceType,
    StatementType,
    ValidationResult,
)
from credit_risk_copilot.financials.reconciliation import corroborate_fact, corroborate_filing
from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.financials.statements import classify_table

__all__ = [
    "CONCEPTS_BY_ID",
    "CONCEPT_DEFINITIONS",
    "CandidateValue",
    "CanonicalFact",
    "CanonicalFilingFacts",
    "CompanyFinancials",
    "Confidence",
    "FactStatus",
    "ManualCorrection",
    "Origin",
    "Period",
    "PeriodType",
    "Provenance",
    "Restatement",
    "SourceType",
    "StatementType",
    "ValidationResult",
    "classify_table",
    "corroborate_fact",
    "corroborate_filing",
    "resolve_filing",
]
