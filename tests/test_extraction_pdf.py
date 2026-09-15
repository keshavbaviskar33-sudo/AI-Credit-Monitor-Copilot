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
from credit_risk_copilot.extraction.render import TABLE_CSS, html_to_pdf, prepare_for_render

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


# --- Preparing filing HTML for rendering ----------------------------------

BODY_TEXT = "Discussion text that runs on for a while to give the section a body. " * 8
# Comfortably over MIN_SLICE_BYTES: the fallback guard is sized for real
# filings, so a toy fixture would trip it and look like a slicing failure.
STATEMENTS = "Consolidated balance sheet line items and figures follow here. " * 1200


def filing_html(*, wrapped: bool, statements: str = STATEMENTS) -> bytes:
    """A miniature filing. `wrapped` puts everything under one container div,
    the way iHeartMedia's and Chesapeake's filings do."""
    blocks = "".join(
        f"<div>{part}</div>"
        for part in [
            "Item 1A. Risk Factors",
            BODY_TEXT,
            "Item 7. Management's Discussion and Analysis",
            BODY_TEXT,
            "Item 8. Financial Statements and Supplementary Data",
            statements,
            "Item 9. Changes in and Disagreements with Accountants",
            BODY_TEXT,
        ]
    )
    inner = f"<div>{blocks}</div>" if wrapped else blocks
    return f"<html><body>{inner}</body></html>".encode()


def test_prepare_narrows_to_the_financial_statements() -> None:
    prepared = prepare_for_render(filing_html(wrapped=False))

    assert "Consolidated balance sheet" in prepared
    assert "Risk Factors" not in prepared


def test_prepare_descends_past_a_single_wrapper_div() -> None:
    """Some filings wrap the whole document in one div; slicing the body
    would then be a no-op and render the entire filing."""
    prepared = prepare_for_render(filing_html(wrapped=True))

    assert "Consolidated balance sheet" in prepared
    assert "Risk Factors" not in prepared


def test_prepare_falls_back_when_item_8_is_only_a_cross_reference() -> None:
    """Filings often satisfy Item 8 with "see the index on page F-1" and put
    the statements in an appendix. Narrowing to that would yield an empty PDF,
    so the whole filing is rendered instead."""
    tiny = "See the Index to Consolidated Financial Statements on page F-1."

    prepared = prepare_for_render(filing_html(wrapped=False, statements=tiny))

    assert "Risk Factors" in prepared, "should have fallen back to the whole filing"


def test_prepare_keeps_the_whole_filing_when_asked() -> None:
    prepared = prepare_for_render(filing_html(wrapped=False), financial_statements_only=False)

    assert "Risk Factors" in prepared
    assert "Consolidated balance sheet" in prepared


def test_prepare_keeps_inline_styles() -> None:
    """Stripping `style` was tried and measured: modern filings carry their
    table column widths there, and without them a many-column statement wraps
    a character per line and never converges (41 pages -> 2,500+)."""
    html = (
        "<html><body>"
        "<div>Item 8. Financial Statements and Supplementary Data</div>"
        '<table style="width:600px"><tr><td style="width:300px">Total assets</td>'
        "<td>1,234</td></tr></table>"
        f"<div>{STATEMENTS}</div>"
        "<div>Item 9. Changes in and Disagreements with Accountants</div>"
        "</body></html>"
    ).encode()

    prepared = prepare_for_render(html)

    assert "width:600px" in prepared
    assert "width:300px" in prepared


def test_pdf_tables_carry_a_bounding_box() -> None:
    """bbox is the PDF equivalent of the HTML element path: it locates the
    table precisely enough to highlight it back to an analyst later."""
    doc = extract(html_to_pdf(TABLE_HTML))
    bbox = doc.tables[0].location.bbox

    assert bbox is not None
    x0, top, x1, bottom = bbox
    assert x1 > x0 and bottom > top


def test_pdf_table_context_captures_the_text_above_it() -> None:
    html = (
        "<html><body>"
        "<p>CONSOLIDATED BALANCE SHEETS</p>"
        "<p>(In millions)</p>"
        "<table>"
        "<tr><th>Item</th><th>2025</th></tr>"
        "<tr><td>Total assets</td><td>1,234</td></tr>"
        "<tr><td>Total liabilities</td><td>900</td></tr>"
        "<tr><td>Total equity</td><td>334</td></tr>"
        "</table></body></html>"
    )

    doc = extract(html_to_pdf(html))
    context = doc.tables[0].context or ""

    assert "BALANCE SHEETS" in context
