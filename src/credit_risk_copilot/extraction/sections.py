"""Locate 10-K item sections (Risk Factors, MD&A, Financial Statements).

Phase 10's NLP reads narrative sections and must quote them verbatim (SC-03),
so sections are returned as character spans into the document text rather than
as copied strings.

Two things make this harder than matching a heading:

1. **The table of contents.** Every 10-K lists the same item headings near the
   front. A naive "first match" lands in the TOC and yields a section a few
   words long. Real body sections are separated by substantial text, so
   candidates are scored by how much text follows them and the largest span
   wins.
2. **Cross references.** "...described in Item 1A. Risk Factors..." appears
   mid-sentence. Requiring a heading to begin a line removes most of these,
   and the span-length score removes the rest.

A section that cannot be located is reported as an `ExtractionError`, never
approximated -- "insufficient information" is a valid answer (principle 4).
Detection accuracy on a real sample is measured in Phase 10 (A-10).
"""

from __future__ import annotations

import re

from credit_risk_copilot.extraction.models import (
    DocumentLocation,
    DocumentSection,
    ExtractionError,
)

#: Shortest body a candidate must have to be accepted as the real section
#: rather than a table-of-contents line or a cross reference. Item 7A is
#: routinely a single short paragraph ("not applicable to smaller reporting
#: companies"), so this is deliberately low -- the span-length ranking, not
#: this floor, is what rejects TOC entries.
MIN_SECTION_CHARS = 200


class _ItemSpec:
    __slots__ = ("section_id", "number", "title", "emit", "required")

    def __init__(
        self,
        section_id: str,
        number: str,
        title: str,
        *,
        emit: bool = False,
        required: bool = False,
    ) -> None:
        self.section_id = section_id
        self.number = number
        self.title = title
        self.emit = emit
        self.required = required


#: Every 10-K item, in filing order. Most are here purely as **boundaries**: a
#: section ends where the next item in this list begins, so the list must be
#: complete even though only `emit` items are returned. Item 8 in particular
#: needs the items that follow it -- without them its span would run to the end
#: of the document, and a table-of-contents match would then beat the real
#: section on length. `required` marks what downstream phases consume and is
#: the only case that produces an error when missing.
ITEM_SPECS: tuple[_ItemSpec, ...] = (
    _ItemSpec("item_1", "1", "Business", emit=True),
    _ItemSpec("item_1a", "1A", "Risk Factors", emit=True, required=True),
    _ItemSpec("item_1b", "1B", "Unresolved Staff Comments"),
    _ItemSpec("item_1c", "1C", "Cybersecurity"),
    _ItemSpec("item_2", "2", "Properties"),
    _ItemSpec("item_3", "3", "Legal Proceedings", emit=True),
    _ItemSpec("item_4", "4", "Mine Safety Disclosures"),
    _ItemSpec("item_5", "5", "Market for Registrant's Common Equity"),
    _ItemSpec("item_6", "6", "Selected Financial Data"),
    _ItemSpec(
        "item_7",
        "7",
        "Management's Discussion and Analysis of Financial Condition and Results of Operations",
        emit=True,
        required=True,
    ),
    _ItemSpec(
        "item_7a",
        "7A",
        "Quantitative and Qualitative Disclosures About Market Risk",
        emit=True,
    ),
    _ItemSpec(
        "item_8", "8", "Financial Statements and Supplementary Data", emit=True, required=True
    ),
    _ItemSpec("item_9", "9", "Changes in and Disagreements with Accountants"),
    _ItemSpec("item_9a", "9A", "Controls and Procedures"),
    _ItemSpec("item_9b", "9B", "Other Information"),
    _ItemSpec("item_9c", "9C", "Disclosure Regarding Foreign Jurisdictions"),
    _ItemSpec("item_10", "10", "Directors, Executive Officers and Corporate Governance"),
    _ItemSpec("item_11", "11", "Executive Compensation"),
    _ItemSpec("item_12", "12", "Security Ownership"),
    _ItemSpec("item_13", "13", "Certain Relationships and Related Transactions"),
    _ItemSpec("item_14", "14", "Principal Accountant Fees and Services"),
    _ItemSpec("item_15", "15", "Exhibits and Financial Statement Schedules"),
    _ItemSpec("item_16", "16", "Form 10-K Summary"),
)

# "Item 1A." / "ITEM 1A -" / "Item 1A:" / "Item 1A\n", at the start of a line,
# optionally preceded by a "Part II" prefix on the same line. The trailing
# guard keeps "Item 1" off the "Item 1A" heading and "Item 9" off "Item 9C".
_HEADING_TEMPLATE = (
    r"^[ \t]*(?:PART\s+[IVX]+[ \t.:\-]*)?ITEM[ \t]+{number}(?![A-Za-z0-9])[ \t]*[.:)\-–—]*[ \t]*"
)


#: Compiled once at import: the item list is static, and a 10-K is large enough
#: that recompiling twenty-odd patterns per document is pure waste.
_HEADING_PATTERNS: dict[str, re.Pattern[str]] = {
    spec.section_id: re.compile(
        _HEADING_TEMPLATE.format(number=re.escape(spec.number)),
        re.IGNORECASE | re.MULTILINE,
    )
    for spec in ITEM_SPECS
}


def _candidate_starts(text: str) -> dict[str, list[int]]:
    """Every line-initial "Item N" heading match, keyed by section id."""
    return {
        section_id: [m.start() for m in pattern.finditer(text)]
        for section_id, pattern in _HEADING_PATTERNS.items()
    }


def detect_sections(
    text: str,
) -> tuple[tuple[DocumentSection, ...], tuple[ExtractionError, ...]]:
    """Locate 10-K item sections in `text`.

    Returns the sections found and an error for each *required* section that
    could not be located with a plausible body.
    """
    candidates = _candidate_starts(text)
    order = [spec.section_id for spec in ITEM_SPECS]
    sections: list[DocumentSection] = []
    errors: list[ExtractionError] = []

    for index, spec in enumerate(ITEM_SPECS):
        # A section ends at the next heading of any later item, so a TOC entry
        # -- immediately followed by the next TOC line -- scores near zero.
        later_starts = sorted(start for sid in order[index + 1 :] for start in candidates[sid])

        best: tuple[int, int] | None = None
        for start in candidates[spec.section_id]:
            end = next((s for s in later_starts if s > start), len(text))
            if best is None or (end - start) > (best[1] - best[0]):
                best = (start, end)

        if not spec.emit:
            continue

        if best is None or (best[1] - best[0]) < MIN_SECTION_CHARS:
            if spec.required:
                reason = (
                    "no heading matched"
                    if best is None
                    else f"only a {best[1] - best[0]}-character body found "
                    f"(likely a table-of-contents entry)"
                )
                errors.append(
                    ExtractionError(
                        code="section_not_found",
                        message=f"Item {spec.number} ({spec.title}) could not be located: {reason}.",
                    )
                )
            continue

        start, end = best
        line_end = text.find("\n", start, end)
        heading_line = text[start : line_end if line_end != -1 else end]
        sections.append(
            DocumentSection(
                section_id=spec.section_id,
                title=spec.title,
                heading_text=heading_line.strip()[:200],
                location=DocumentLocation(
                    char_start=start, char_end=end, section_id=spec.section_id
                ),
            )
        )

    return tuple(sections), tuple(errors)
