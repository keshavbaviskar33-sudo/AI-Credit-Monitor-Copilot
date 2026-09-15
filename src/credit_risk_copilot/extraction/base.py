"""The extractor interface the rest of the pipeline depends on.

Phase 5 parsing consumes `ExtractedDocument`, never a library-specific object,
so the HTML and PDF paths stay interchangeable and either library can be
swapped out behind this protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from credit_risk_copilot.extraction.models import DocumentSource, ExtractedDocument


@runtime_checkable
class DocumentExtractor(Protocol):
    """Turns one document's bytes into located text, tables and sections."""

    name: str
    version: str

    def extract(self, content: bytes, source: DocumentSource) -> ExtractedDocument:
        """Extract `content`. Failures inside the document become
        `ExtractedDocument.errors`; only an unusable document raises."""
        ...


class DocumentExtractionError(Exception):
    """The document as a whole could not be opened or parsed.

    Per-part failures are `ExtractionError` entries instead -- this is for the
    case where there is nothing to return at all.
    """
