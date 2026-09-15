"""Extract text, tables and sections from text-based PDFs.

This path serves analyst-uploaded financial statements (FR-04) and the
generated PDF half of the golden set (D-014). Scanned/OCR PDFs are out of MVP
scope: a page with no extractable text is reported as an `ExtractionError`
rather than silently contributing nothing (R-09).

Unlike the HTML path, PDFs are page-oriented, so every location carries a page
number as well as a character span.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pdfplumber

from credit_risk_copilot.extraction.base import DocumentExtractionError
from credit_risk_copilot.extraction.models import (
    DocumentLocation,
    DocumentSource,
    ExtractedDocument,
    ExtractionError,
    Table,
    TextBlock,
)
from credit_risk_copilot.extraction.sections import detect_sections

logger = logging.getLogger(__name__)

EXTRACTOR_NAME = "pdf"
EXTRACTOR_VERSION = "1.0"

PDF_MAGIC = b"%PDF-"


class PdfDocumentExtractor:
    """Extracts a text-based PDF into located text, tables and sections."""

    name = EXTRACTOR_NAME
    version = EXTRACTOR_VERSION

    def extract(self, content: bytes, source: DocumentSource) -> ExtractedDocument:
        if not content.startswith(PDF_MAGIC):
            raise DocumentExtractionError("Not a PDF: file does not start with %PDF-.")

        parts: list[str] = []
        length = 0
        blocks: list[TextBlock] = []
        tables: list[Table] = []
        errors: list[ExtractionError] = []

        def append(text: str) -> tuple[int, int]:
            nonlocal length
            start = length
            parts.append(text + "\n")
            length += len(text) + 1
            return start, start + len(text)

        with open_pdf(content) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                page_start = length

                if not page_text.strip():
                    errors.append(
                        ExtractionError(
                            code="page_without_text",
                            message=(
                                f"Page {page_number} yielded no extractable text "
                                "(likely a scanned image; OCR is out of MVP scope)."
                            ),
                        )
                    )

                for line in page_text.splitlines():
                    if not line.strip():
                        continue
                    start, end = append(line.strip())
                    blocks.append(
                        TextBlock(
                            text=line.strip(),
                            location=DocumentLocation(
                                char_start=start, char_end=end, page=page_number
                            ),
                        )
                    )

                tables.extend(_page_tables(page, page_number, page_start, length, errors))

        sections, section_errors = detect_sections("".join(parts))
        return ExtractedDocument(
            source=source,
            extractor=self.name,
            extractor_version=self.version,
            text="".join(parts),
            blocks=tuple(blocks),
            tables=tuple(tables),
            sections=sections,
            errors=tuple(errors) + section_errors,
        )


def _page_tables(
    page: pdfplumber.page.Page,
    page_number: int,
    page_start: int,
    page_end: int,
    errors: list[ExtractionError],
) -> list[Table]:
    """Tables on one page.

    A table's location is its page's text span, not a span of its own:
    pdfplumber finds tables geometrically, so the cells are already part of the
    page text appended by the caller. Appending them again would duplicate
    content in `text` and break the character offsets that quotes rely on.
    """
    found: list[Table] = []
    try:
        raw_tables = page.extract_tables()
    except Exception as exc:  # pdfplumber raises assorted errors on odd layouts
        errors.append(
            ExtractionError(
                code="table_extraction_failed",
                message=f"Table extraction failed on page {page_number}: {exc}",
            )
        )
        return found

    for raw in raw_tables:
        rows = tuple(
            tuple((cell or "").strip().replace("\n", " ") for cell in row)
            for row in raw
            if any(cell and cell.strip() for cell in row)
        )
        if not rows:
            continue
        found.append(
            Table(
                rows=rows,
                location=DocumentLocation(
                    char_start=page_start, char_end=page_end, page=page_number
                ),
            )
        )
    return found


def open_pdf(content: bytes) -> Any:
    """Open PDF bytes, raising `DocumentExtractionError` on anything unreadable."""
    try:
        return pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise DocumentExtractionError(f"PDF could not be opened: {exc}") from exc
