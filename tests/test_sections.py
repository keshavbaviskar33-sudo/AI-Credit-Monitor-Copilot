"""Tests for 10-K item section detection.

The cases that matter are the ones that make naive heading matching wrong: the
table of contents, cross references, and `Item 1` vs `Item 1A`.
"""

from __future__ import annotations

from credit_risk_copilot.extraction.sections import MIN_SECTION_CHARS, detect_sections

BODY = "This section has real content that runs on for a while. " * 12


def _filing(*, toc: bool = True) -> str:
    """A miniature 10-K: optional table of contents, then real item bodies."""
    parts = []
    if toc:
        parts += [
            "TABLE OF CONTENTS",
            "Item 1. Business 3",
            "Item 1A. Risk Factors 12",
            "Item 7. Management's Discussion and Analysis 40",
            "Item 8. Financial Statements and Supplementary Data 55",
            "Item 9A. Controls and Procedures 90",
        ]
    parts += [
        "Item 1. Business",
        f"BUSINESS_BODY {BODY}",
        "Item 1A. Risk Factors",
        f"RISK_BODY {BODY}",
        "Item 2. Properties",
        f"PROPERTIES_BODY {BODY}",
        "Item 7. Management's Discussion and Analysis of Financial Condition",
        f"MDNA_BODY {BODY}",
        "Item 8. Financial Statements and Supplementary Data",
        f"STATEMENTS_BODY {BODY}",
        "Item 9A. Controls and Procedures",
        f"CONTROLS_BODY {BODY}",
    ]
    return "\n".join(parts) + "\n"


def test_finds_the_required_sections() -> None:
    sections, errors = detect_sections(_filing())

    assert errors == ()
    found = {s.section_id for s in sections}
    assert {"item_1a", "item_7", "item_8"} <= found


def test_skips_the_table_of_contents() -> None:
    """The first "Item 1A" in a filing is a contents line, not the section."""
    text = _filing()
    sections, _ = detect_sections(text)
    risk = next(s for s in sections if s.section_id == "item_1a")

    body = text[risk.location.char_start : risk.location.char_end]

    assert "RISK_BODY" in body
    assert "Risk Factors 12" not in body, "matched the table-of-contents entry"


def test_section_ends_where_the_next_item_begins() -> None:
    text = _filing()
    sections, _ = detect_sections(text)
    risk = next(s for s in sections if s.section_id == "item_1a")

    body = text[risk.location.char_start : risk.location.char_end]

    # Item 2 is not reported, but it must still bound Item 1A.
    assert "PROPERTIES_BODY" not in body
    assert "Item 2. Properties" not in body


def test_item_8_is_bounded_by_the_items_after_it() -> None:
    """Item 8 is the last *reported* item, so it needs later items as boundaries.

    Without them its span runs to the end of the document, which lets the
    table-of-contents match win on length.
    """
    text = _filing()
    sections, _ = detect_sections(text)
    statements = next(s for s in sections if s.section_id == "item_8")

    body = text[statements.location.char_start : statements.location.char_end]

    assert "STATEMENTS_BODY" in body
    assert "CONTROLS_BODY" not in body


def test_item_1_does_not_match_the_item_1a_heading() -> None:
    text = _filing()
    sections, _ = detect_sections(text)
    business = next(s for s in sections if s.section_id == "item_1")

    body = text[business.location.char_start : business.location.char_end]

    assert "BUSINESS_BODY" in body
    assert "RISK_BODY" not in body


def test_cross_reference_mid_sentence_is_not_a_heading() -> None:
    text = (
        "Item 1A. Risk Factors\n"
        f"RISK_BODY {BODY}\n"
        "These matters are further described in Item 8. Financial Statements below.\n"
        f"{BODY}\n"
        "Item 8. Financial Statements and Supplementary Data\n"
        f"STATEMENTS_BODY {BODY}\n"
        "Item 9. Changes in and Disagreements with Accountants\n"
    )
    sections, _ = detect_sections(text)
    statements = next(s for s in sections if s.section_id == "item_8")

    assert "STATEMENTS_BODY" in text[statements.location.char_start : statements.location.char_end]


def test_missing_required_section_is_reported_not_guessed() -> None:
    text = f"Item 1. Business\nBUSINESS_BODY {BODY}\nItem 2. Properties\n{BODY}\n"

    sections, errors = detect_sections(text)

    assert {s.section_id for s in sections} == {"item_1"}
    codes = {e.code for e in errors}
    assert codes == {"section_not_found"}
    missing = {e.message.split("(")[0].strip() for e in errors}
    assert missing == {"Item 1A", "Item 7", "Item 8"}


def test_contents_only_filing_reports_every_required_section_missing() -> None:
    """A filing that is nothing but a contents page yields errors, not stubs."""
    text = "\n".join(
        [
            "Item 1A. Risk Factors 12",
            "Item 7. Management's Discussion 40",
            "Item 8. Financial Statements 55",
            "Item 9. Changes in Accountants 90",
        ]
    )

    sections, errors = detect_sections(text)

    assert sections == ()
    assert len(errors) == 3
    assert all("table-of-contents" in e.message for e in errors)


def test_body_shorter_than_the_floor_is_rejected() -> None:
    text = (
        "Item 1A. Risk Factors\n"
        + "x" * (MIN_SECTION_CHARS // 4)
        + "\nItem 7. Management's Discussion\n"
        + f"MDNA {BODY}\n"
        + "Item 8. Financial Statements\n"
        + f"STMT {BODY}\n"
        + "Item 9. Changes\n"
    )

    sections, errors = detect_sections(text)

    assert "item_1a" not in {s.section_id for s in sections}
    assert any("Item 1A" in e.message for e in errors)


def test_uppercase_and_part_prefixed_headings_match() -> None:
    text = (
        "PART I\n"
        "ITEM 1A — RISK FACTORS\n"
        f"RISK_BODY {BODY}\n"
        "PART II ITEM 7: MANAGEMENT'S DISCUSSION AND ANALYSIS\n"
        f"MDNA_BODY {BODY}\n"
        "ITEM 8. FINANCIAL STATEMENTS\n"
        f"STMT_BODY {BODY}\n"
        "ITEM 9. CHANGES\n"
    )

    sections, errors = detect_sections(text)

    assert errors == ()
    assert {"item_1a", "item_7", "item_8"} <= {s.section_id for s in sections}
