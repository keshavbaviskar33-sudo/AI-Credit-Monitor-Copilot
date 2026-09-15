"""Tests for the text-based PDF extractor and the HTML->PDF renderer.

Fixture PDFs are generated in-process rather than committed as binaries, so the
tests stay offline, readable and diffable.
"""

from __future__ import annotations

import pymupdf
import pytest

from credit_risk_copilot.extraction import DocumentSource, PdfDocumentExtractor
from credit_risk_copilot.extraction.base import DocumentExtractionError
from credit_risk_copilot.extraction.models import ExtractedDocument
from credit_risk_copilot.extraction.render import TABLE_CSS, html_to_pdf

SOURCE = DocumentSource(uri="statements.pdf", media_type="application/pdf")

TABLE_HTML = (
    "<html><body><table>"
    "<tr><th>Item</th><th>2023</th><th>2022</th></tr>"
    "<tr><td>Total assets</td><td>1,234</td><td>1,100</td></tr>"
    "<tr><td>Total liabilities</td><td>900</td><td>850</td></tr>"
    "</table></body></html>"
)


def extract(pdf_bytes: bytes) -> ExtractedDocument:
    return PdfDocumentExtractor().extract(pdf_bytes, SOURCE)


def blank_pdf(pages: int = 1) -> bytes:
    """A PDF with pages but no text, standing in for a scanned document."""
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    return bytes(doc.tobytes())


def test_render_round_trip_preserves_text() -> None:
    doc = extract(html_to_pdf("<html><body><p>Revenue decreased.</p></body></html>"))

    assert "Revenue decreased." in doc.text


def test_rendered_tables_are_extracted_cell_for_cell() -> None:
    doc = extract(html_to_pdf(TABLE_HTML))

    assert len(doc.tables) == 1
    assert doc.tables[0].rows == (
        ("Item", "2023", "2022"),
        ("Total assets", "1,234", "1,100"),
        ("Total liabilities", "900", "850"),
    )


def test_borderless_render_is_why_the_table_css_exists() -> None:
    """Regression guard for the R-19 finding.

    `pymupdf.Story` draws no ruling lines, and without them pdfplumber's
    line-based detection finds no tables at all. `TABLE_CSS` restores the
    borders; drop it and the golden set would measure the renderer instead of
    the extractor.
    """
    without_borders = extract(html_to_pdf(TABLE_HTML, user_css=""))
    with_borders = extract(html_to_pdf(TABLE_HTML, user_css=TABLE_CSS))

    assert without_borders.tables == ()
    assert len(with_borders.tables) == 1
    # The text survives either way; only table *structure* is lost.
    assert "Total assets" in without_borders.text


def test_blocks_carry_page_numbers_and_sliceable_offsets() -> None:
    doc = extract(html_to_pdf("<html><body><p>Page one text.</p></body></html>"))

    assert doc.blocks
    for block in doc.blocks:
        assert block.location.page == 1
        assert doc.text[block.location.char_start : block.location.char_end] == block.text


def test_multi_page_documents_number_pages_in_order() -> None:
    html = "<html><body>" + "".join(f"<p>Paragraph {i}.</p>" for i in range(400)) + "</body></html>"

    doc = extract(html_to_pdf(html))

    pages = sorted({b.location.page for b in doc.blocks if b.location.page})
    assert len(pages) > 1, "fixture should span multiple pages"
    assert pages == list(range(1, len(pages) + 1))


def test_pages_without_text_are_reported_not_silently_dropped() -> None:
    doc = extract(blank_pdf(pages=2))

    codes = [e.code for e in doc.errors]
    assert codes.count("page_without_text") == 2


def test_table_location_points_at_its_page_span() -> None:
    doc = extract(html_to_pdf(TABLE_HTML))
    table = doc.tables[0]

    assert table.location.page == 1
    page_text = doc.text[table.location.char_start : table.location.char_end]
    assert "Total assets" in page_text


def test_non_pdf_bytes_are_rejected() -> None:
    with pytest.raises(DocumentExtractionError, match="Not a PDF"):
        extract(b"<html><body>I am not a PDF</body></html>")


def test_corrupt_pdf_raises_rather_than_returning_an_empty_document() -> None:
    with pytest.raises(DocumentExtractionError):
        extract(b"%PDF-1.7\nbut the rest of this is garbage")


def test_sections_are_detected_through_the_pdf_path_too() -> None:
    body = "This section has real content that runs on for a while. " * 12
    html = (
        "<html><body>"
        f"<p>Item 1A. Risk Factors</p><p>RISK_BODY {body}</p>"
        f"<p>Item 7. Management's Discussion and Analysis</p><p>MDNA_BODY {body}</p>"
        f"<p>Item 8. Financial Statements and Supplementary Data</p><p>STMT_BODY {body}</p>"
        "<p>Item 9. Changes in and Disagreements with Accountants</p>"
        "</body></html>"
    )

    doc = extract(html_to_pdf(html))

    assert {"item_1a", "item_7", "item_8"} <= {s.section_id for s in doc.sections}
    assert "RISK_BODY" in (doc.section_text("item_1a") or "")


def test_extractor_identity_is_recorded() -> None:
    doc = extract(html_to_pdf("<html><body><p>x</p></body></html>"))

    assert doc.extractor == "pdf"
    assert doc.extractor_version
