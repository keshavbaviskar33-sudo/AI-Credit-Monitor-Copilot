"""Tests for the structure Phase 5 depends on: grids, context and sections.

These cover the Phase 4 audit's findings. Each is a property Phase 5 cannot
reconstruct on its own, so a regression here would surface as an inexplicable
parsing failure two phases later.
"""

from __future__ import annotations

from credit_risk_copilot.extraction import DocumentSource, HtmlDocumentExtractor
from credit_risk_copilot.extraction.models import DocumentLocation, Table

SOURCE = DocumentSource(uri="filing.htm", media_type="text/html")


def extract(html: str):
    return HtmlDocumentExtractor().extract(html.encode(), SOURCE)


def table(*rows: tuple[str, ...]) -> Table:
    return Table(rows=rows, location=DocumentLocation(char_start=0, char_end=1))


# --- Grid expansion -------------------------------------------------------


def test_colspan_is_expanded_so_every_row_has_the_same_width() -> None:
    doc = extract(
        "<body><table>"
        "<tr><td colspan='3'></td><td colspan='3'>2025</td></tr>"
        "<tr><td colspan='3'>Total assets</td><td>$</td><td>1,234</td><td></td></tr>"
        "</table></body>"
    )

    assert doc.tables[0].is_rectangular
    assert doc.tables[0].n_cols == 6


def test_header_lands_in_the_same_column_as_its_values() -> None:
    """The point of expansion: an unexpanded grid puts the header at index 1
    and the value at index 2, so pairing a figure with its year is guesswork."""
    doc = extract(
        "<body><table>"
        "<tr><td colspan='2'></td><td colspan='2'>FY2025</td><td colspan='2'>FY2024</td></tr>"
        "<tr><td colspan='2'>Revenue</td><td colspan='2'>500</td><td colspan='2'>400</td></tr>"
        "</table></body>"
    )
    header, data = doc.tables[0].rows

    assert header.index("FY2025") == data.index("500")
    assert header.index("FY2024") == data.index("400")


def test_spanned_cells_repeat_as_empty_not_as_duplicate_values() -> None:
    """A value duplicated across its span would be counted twice downstream."""
    doc = extract("<body><table><tr><td colspan='3'>1,234</td></tr></table></body>")

    assert doc.tables[0].rows[0] == ("1,234", "", "")


def test_rowspan_shifts_following_rows_into_the_right_columns() -> None:
    doc = extract(
        "<body><table>"
        "<tr><td rowspan='2'>Segment</td><td>2025</td><td>2024</td></tr>"
        "<tr><td>100</td><td>90</td></tr>"
        "</table></body>"
    )
    rows = doc.tables[0].rows

    assert rows[0] == ("Segment", "2025", "2024")
    assert rows[1] == ("", "100", "90"), "rowspan must hold the first column open"


def test_absurd_colspan_cannot_blow_up_a_row() -> None:
    doc = extract("<body><table><tr><td colspan='99999'>x</td></tr></table></body>")

    assert doc.tables[0].n_cols <= 50


def test_malformed_colspan_is_treated_as_one() -> None:
    doc = extract("<body><table><tr><td colspan='abc'>x</td><td>y</td></tr></table></body>")

    assert doc.tables[0].rows[0] == ("x", "y")


# --- Table context --------------------------------------------------------


def test_table_context_captures_the_statement_title_and_units() -> None:
    """Both live above the table, never inside it, and Phase 5 needs both --
    the units line is the defence against the wrong-scale error in R-09."""
    doc = extract(
        "<body>"
        "<p>Apple Inc.</p>"
        "<p>CONSOLIDATED BALANCE SHEETS</p>"
        "<p>(In millions, except par value)</p>"
        "<table><tr><td>Total assets</td><td>1,234</td></tr></table>"
        "</body>"
    )
    context = doc.tables[0].context or ""

    assert "CONSOLIDATED BALANCE SHEETS" in context
    assert "In millions" in context


def test_table_with_nothing_before_it_has_no_context() -> None:
    doc = extract("<body><table><tr><td>Total assets</td><td>1</td></tr></table></body>")

    assert doc.tables[0].context is None


# --- Section assignment ---------------------------------------------------


def test_tables_and_blocks_are_stamped_with_their_section() -> None:
    body = "This section has real content that runs on for a while. " * 12
    doc = extract(
        "<body>"
        f"<p>Item 1A. Risk Factors</p><p>{body}</p>"
        f"<p>Item 7. Management's Discussion and Analysis</p><p>{body}</p>"
        "<p>Item 8. Financial Statements and Supplementary Data</p>"
        "<table><tr><td>Total assets</td><td>1,234</td></tr></table>"
        f"<p>{body}</p>"
        "<p>Item 9. Changes in and Disagreements with Accountants</p>"
        "</body>"
    )

    assert doc.tables[0].location.section_id == "item_8"
    assert any(b.location.section_id == "item_1a" for b in doc.blocks)


def test_content_outside_every_section_is_left_unstamped() -> None:
    """Nearest-guess would be worse than None: a cover-page table is not in
    Item 8 just because Item 8 is the closest section."""
    doc = extract("<body><p>Cover page</p><table><tr><td>x</td><td>1</td></tr></table></body>")

    assert doc.tables[0].location.section_id is None


# --- Quality signals ------------------------------------------------------


def test_numeric_density_separates_data_tables_from_layout_tables() -> None:
    data = table(("Revenue", "1,234"), ("Costs", "567"), ("Profit", "667"))
    layout = table(("Some heading text",), ("More prose here",), ("And more",))

    assert data.numeric_density > 0.4
    assert layout.numeric_density == 0.0


def test_looks_like_financial_data_screens_out_scaffolding() -> None:
    statement = table(
        ("", "2025", "2024"),
        ("Total assets", "1,234", "1,100"),
        ("Total liabilities", "900", "850"),
    )
    spacer = table(("",), ("",))

    assert statement.looks_like_financial_data
    assert not spacer.looks_like_financial_data


def test_has_row_labels_requires_a_wordy_first_column() -> None:
    labelled = table(("Revenue", "1"), ("Costs", "2"))
    unlabelled = table(("1,234", "1"), ("5,678", "2"))

    assert labelled.has_row_labels
    assert not unlabelled.has_row_labels


def test_quality_signals_are_facts_not_invented_confidence() -> None:
    """Deliberate design choice: report what is measurable about the grid and
    let Phase 5 judge. A fabricated confidence score would look like evidence
    without being any."""
    assert not hasattr(table(("a", "1")), "confidence")
