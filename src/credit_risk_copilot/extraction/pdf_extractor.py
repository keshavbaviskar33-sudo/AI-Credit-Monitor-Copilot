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
from credit_risk_copilot.extraction.sections import assign_sections, detect_sections

EXTRACTOR_NAME = "pdf"
EXTRACTOR_VERSION = "1.0"

PDF_MAGIC = b"%PDF-"

#: How much text above a table to keep as its context — enough for the
#: statement title and the units declaration, not the previous table.
CONTEXT_LINES = 3
CONTEXT_CHARS = 300


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

                # pdfplumber caches every page's parsed objects on the page and
                # never releases them, so a few hundred table-dense pages will
                # exhaust memory. We never revisit a page, so drop it now.
                page.flush_cache()
                page.get_textmap.cache_clear()

        sections, section_errors = detect_sections("".join(parts))
        return ExtractedDocument(
            source=source,
            extractor=self.name,
            extractor_version=self.version,
            text="".join(parts),
            blocks=assign_sections(tuple(blocks), sections),
            tables=assign_sections(tuple(tables), sections),
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
    """Tables on one page, with their bounding box and the text above them.

    A table's character span is its *page's* span, not one of its own:
    pdfplumber finds tables geometrically, so the cells are already part of the
    page text appended by the caller. Appending them again would duplicate
    content in `text` and break the offsets that quotes rely on. The `bbox`
    carries the precise position instead.

    `find_tables()` is used rather than `extract_tables()` purely to reach that
    bbox — the latter is implemented as the former plus `.extract()`, so the
    cells are identical.
    """
    found: list[Table] = []
    try:
        finder = page.find_tables()
    except Exception as exc:  # pdfplumber raises assorted errors on odd layouts
        errors.append(
            ExtractionError(
                code="table_extraction_failed",
                message=f"Table extraction failed on page {page_number}: {exc}",
            )
        )
        return found

    lines: list[Any] | None = None
    for table in finder:
        try:
            raw = table.extract()
        except Exception as exc:
            errors.append(
                ExtractionError(
                    code="table_extraction_failed",
                    message=f"A table on page {page_number} could not be read: {exc}",
                )
            )
            continue

        rows = tuple(
            tuple((cell or "").strip().replace("\n", " ") for cell in row)
            for row in raw
            if any(cell and cell.strip() for cell in row)
        )
        if not rows:
            continue

        candidate = Table(
            rows=rows,
            location=DocumentLocation(
                char_start=page_start,
                char_end=page_end,
                page=page_number,
                bbox=tuple(float(v) for v in table.bbox),  # type: ignore[arg-type]
            ),
        )
        # The statement title and units declaration sit above the table, not in
        # it. Only worth the text pass for tables that could be a statement --
        # a dense filing carries thousands of layout tables and paying for each
        # would multiply the cost of the slowest path in the pipeline.
        if candidate.looks_like_financial_data:
            if lines is None:
                lines = _text_lines(page)
            candidate = candidate.model_copy(
                update={"context": _context_above(lines, table.bbox[1])}
            )
        found.append(candidate)
    return found


def _text_lines(page: pdfplumber.page.Page) -> list[Any]:
    try:
        return list(page.extract_text_lines())
    except Exception:
        return []


def _context_above(lines: list[Any], top: float) -> str | None:
    """The last few text lines ending above `top`."""
    above = [ln for ln in lines if ln.get("bottom", 0) <= top]
    if not above:
        return None
    recent = [str(ln.get("text", "")).strip() for ln in above[-CONTEXT_LINES:]]
    joined = " | ".join(line for line in recent if line)
    return joined[-CONTEXT_CHARS:] or None


def open_pdf(content: bytes) -> Any:
    """Open PDF bytes, raising `DocumentExtractionError` on anything unreadable."""
    try:
        return pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise DocumentExtractionError(f"PDF could not be opened: {exc}") from exc
