"""Tests for the 10-K HTML / inline-XBRL extractor."""

from __future__ import annotations

import pytest

from credit_risk_copilot.extraction import DocumentSource, HtmlDocumentExtractor
from credit_risk_copilot.extraction.base import DocumentExtractionError
from credit_risk_copilot.extraction.models import ExtractedDocument

SOURCE = DocumentSource(
    uri="aapl-20230930.htm",
    media_type="text/html",
    cik=320193,
    accession="0000320193-23-000106",
    form="10-K",
    filed="2023-11-03",
)


def extract(html: str) -> ExtractedDocument:
    return HtmlDocumentExtractor().extract(html.encode("utf-8"), SOURCE)


def test_blocks_are_separated_and_whitespace_collapsed() -> None:
    doc = extract("<body><p>First   paragraph.</p><p>Second\n\tparagraph.</p></body>")

    assert [b.text for b in doc.blocks] == ["First paragraph.", "Second paragraph."]


def test_every_block_location_slices_back_to_its_own_text() -> None:
    """Offsets are the whole provenance guarantee -- if they drift, quotes lie."""
    doc = extract("<body><div>Alpha</div><p>Beta</p><ul><li>Gamma</li><li>Delta</li></ul></body>")

    for block in doc.blocks:
        assert doc.text[block.location.char_start : block.location.char_end] == block.text


def test_table_cells_are_extracted_as_raw_strings() -> None:
    doc = extract(
        "<body><table>"
        "<tr><th>Item</th><th>2023</th></tr>"
        "<tr><td>Total assets</td><td>1,234</td></tr>"
        "</table></body>"
    )

    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.rows == (("Item", "2023"), ("Total assets", "1,234"))
    assert table.n_rows == 2
    assert table.n_cols == 2


def test_table_text_is_mirrored_into_the_document_text() -> None:
    """Item 8 is nearly all tables; leaving them out would make it look empty."""
    doc = extract("<body><table><tr><td>Total assets</td><td>1,234</td></tr></table></body>")

    assert "Total assets" in doc.text
    table = doc.tables[0]
    assert "1,234" in doc.text[table.location.char_start : table.location.char_end]


def test_inline_xbrl_tags_contribute_their_displayed_value() -> None:
    """`<ix:nonFraction>` wraps the number a human sees; read the document, not the facts."""
    doc = extract(
        "<body><table><tr><td>Total assets</td>"
        "<td><ix:nonFraction contextRef='c1' unitRef='usd'>352,583</ix:nonFraction></td>"
        "</tr></table></body>"
    )

    assert doc.tables[0].rows == (("Total assets", "352,583"),)


def test_script_and_style_content_is_not_document_text() -> None:
    doc = extract(
        "<body><style>.c { color: red; }</style>"
        "<script>var hidden = 'SCRIPT_NOISE';</script>"
        "<p>Real text.</p></body>"
    )

    assert "SCRIPT_NOISE" not in doc.text
    assert "color: red" not in doc.text
    assert [b.text for b in doc.blocks] == ["Real text."]


def test_empty_layout_tables_are_skipped_without_an_error() -> None:
    """Filings use borderless empty tables for spacing; they lose no content."""
    doc = extract("<body><table><tr><td></td><td></td></tr></table><p>Real text.</p></body>")

    assert doc.tables == ()
    assert [e for e in doc.errors if "table" in e.code] == []


def test_tail_text_after_a_table_is_kept_exactly_once() -> None:
    """`skip_subtree` still fires the end event, so tails are easy to double-count."""
    doc = extract("<body><div><table><tr><td>X</td></tr></table>TAIL_TEXT</div></body>")

    assert doc.text.count("TAIL_TEXT") == 1


def test_blocks_carry_an_element_path_for_traceability() -> None:
    doc = extract("<body><p>Traceable.</p></body>")

    assert doc.blocks[0].location.element_path
    assert doc.blocks[0].location.page is None


def test_source_and_extractor_version_are_recorded() -> None:
    doc = extract("<body><p>Anything.</p></body>")

    assert doc.source.accession == "0000320193-23-000106"
    assert doc.extractor == "html"
    assert doc.extractor_version


def test_empty_document_is_rejected() -> None:
    with pytest.raises(DocumentExtractionError, match="empty"):
        extract("   ")


def test_section_text_returns_none_for_a_section_that_was_not_found() -> None:
    doc = extract("<body><p>No items here at all.</p></body>")

    assert doc.section("item_1a") is None
    assert doc.section_text("item_1a") is None
