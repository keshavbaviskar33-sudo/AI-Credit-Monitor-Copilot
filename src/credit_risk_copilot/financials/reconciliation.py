"""Bounded cross-source reconciliation (§13): does the document agree?

For SEC filers, XBRL is the source of record (D-005) -- this module does not
re-derive values from document tables, it only checks whether a value
already resolved from XBRL is *also* independently visible in the filing's
own HTML tables (the same document Phase 4 already extracted). Two outcomes:

- **Found:** a second, independent provenance entry is appended and
  confidence may rise -- two sources agreeing is real evidence (§20).
- **Not found:** nothing is downgraded. HTML recall against this same golden
  set measured 85.1%, not 100% (`golden_set.md` §3), so "not found in the
  tables" is exactly as likely to mean "the extractor missed it" as "the
  number is wrong" -- treating it as a conflict would manufacture distrust
  the data does not support.

This is deliberately not the enormous reconciliation framework §13 warns
against: one function, one direction (XBRL confirmed by document), no
attempt to parse the document's own tables into facts.
"""

from __future__ import annotations

from credit_risk_copilot.extraction.models import ExtractedDocument
from credit_risk_copilot.financials.models import (
    CanonicalFact,
    CanonicalFilingFacts,
    Confidence,
    FactStatus,
    Provenance,
    SourceType,
)
from credit_risk_copilot.financials.numeric import render_candidates


def _find_in_tables(value: float, document: ExtractedDocument) -> Provenance | None:
    candidates = render_candidates(value)
    if not candidates:
        return None
    for table in document.tables:
        for row in table.rows:
            for cell in row:
                if cell and cell.strip() in candidates:
                    return Provenance(
                        source_type=SourceType.HTML,
                        extraction_method="html-table-corroboration",
                        document_uri=document.source.uri,
                        section_id=table.location.section_id,
                        original_text=cell.strip(),
                        original_value=value,
                        notes="Independently found in the filing's own HTML table.",
                    )
    return None


def corroborate_fact(fact: CanonicalFact, document: ExtractedDocument) -> CanonicalFact:
    """Return `fact`, or a copy with an added HTML provenance entry and
    raised confidence, if its value is independently visible in `document`."""
    if fact.status not in (FactStatus.FOUND, FactStatus.DERIVED) or fact.value is None:
        return fact
    corroboration = _find_in_tables(fact.value, document)
    if corroboration is None:
        return fact
    return fact.model_copy(
        update={
            "provenance": (*fact.provenance, corroboration),
            "confidence": Confidence.HIGH,
        }
    )


def corroborate_filing(
    filing: CanonicalFilingFacts, document: ExtractedDocument
) -> CanonicalFilingFacts:
    """Apply `corroborate_fact` to every fact in a filing against one
    document (typically that filing's own HTML, per D-005/D-014)."""
    return filing.model_copy(
        update={"facts": tuple(corroborate_fact(f, document) for f in filing.facts)}
    )
