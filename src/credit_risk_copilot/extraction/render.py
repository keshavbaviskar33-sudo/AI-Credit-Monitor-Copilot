"""Render filing HTML to PDF, to produce the PDF half of the golden set.

SEC publishes 10-Ks as HTML and never as PDF, but QM-01 measures extraction
accuracy "PDF vs. XBRL reference" and analysts upload PDFs (FR-04). A-07
permits golden-set PDFs to be *generated*, which keeps the corpus
licence-clear and reproducible by anyone who clones the repo (D-014).

**Why the table CSS below is not cosmetic.** `pymupdf.Story` renders HTML
tables with no ruling lines. Measured during the Phase 4 spike (R-19), a
borderless render defeats table detection in both candidate libraries --
pdfplumber's line strategy finds nothing, its text strategy returns shredded
cells ("I", "tem"), and pymupdf's `find_tables` finds nothing either. Adding
borders restores exact extraction in both. Without this, the golden set would
measure the renderer rather than the extractor.

This makes generated PDFs cleaner than a typical real-world PDF, so QM-01's
PDF figure is an upper bound. That limitation is recorded in docs/golden_set.md
rather than left implicit.

**Do not strip the filing's presentation attributes.** That was tried and
measured, and it is actively harmful. Modern filings carry their table column
widths in inline `style`; without them a many-column financial statement gets
near-zero column widths, wraps a character per line and never converges.
Measured on Apple's FY2025 10-K: 41 pages as filed, **2,500+ pages** with
`style` removed. Older filings (iHeartMedia 2016) do benefit, but not enough
to justify breaking the modern ones.

**Narrow to the financial statements instead** -- see `prepare_for_render`.
That is what actually bounds the cost, and it is also the more faithful
artefact: QM-01 measures "a golden set of 10-K *financial statements*", and
FR-04's real input is an analyst uploading a *financial statement* PDF, not a
300-page annual report.
"""

from __future__ import annotations

import io
import logging

import lxml.html
import pymupdf

from credit_risk_copilot.extraction.sections import detect_sections

logger = logging.getLogger(__name__)

#: Ruled, tightly-padded tables so table detection has edges to find.
#: `border-collapse` keeps adjacent cells from drawing doubled lines, which
#: confuses edge-based detection as badly as having none.
TABLE_CSS = """
table { border-collapse: collapse; }
table, th, td { border: 0.5px solid #000; padding: 2px; }
body { font-family: sans-serif; font-size: 9px; }
"""

#: Guards against a pathological document paginating forever. A 10-K runs to a
#: few hundred pages; well beyond that means the layout is not converging, and
#: the result would be unusable anyway.
MAX_PAGES = 600

#: An Item 8 slice smaller than this is not the statements. Many filings satisfy
#: Item 8 with a one-line cross reference ("see the Index to Financial
#: Statements on page F-1") and put the statements in an appendix after Item 15.
#: Measured: Frontier's 2019 10-K yields a 2 KB Item 8 against a 4 MB filing.
#: Below this floor the whole document is rendered instead, which is slower but
#: never silently produces an empty PDF.
MIN_SLICE_BYTES = 50_000


def _branching_level(body: lxml.html.HtmlElement) -> lxml.html.HtmlElement:
    """Descend past single-child wrappers to the level that holds the content.

    Filings differ here and the difference is not cosmetic: Apple's 10-K puts
    ~800 siblings directly under `<body>`, while iHeartMedia's and Chesapeake's
    wrap the entire document in one `<div>`. Slicing at `<body>` would be a
    no-op for the latter, so descend until there is something to slice.
    """
    node = body
    while True:
        elements = [child for child in node if isinstance(child.tag, str)]
        if len(elements) != 1:
            return node
        node = elements[0]


def _financial_statement_slice(children: list[lxml.html.HtmlElement]) -> bytes | None:
    """Serialised Item 8 region, or None if it is missing or implausibly small.

    Each sibling is mapped to a character span of its own text so
    `detect_sections` can pick the Item 8 span -- reusing the
    table-of-contents handling that is already tested rather than inventing a
    second heading matcher here.
    """
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    length = 0
    for index, child in enumerate(children):
        text = " ".join(child.text_content().replace("\xa0", " ").split())
        parts.append(text + "\n")
        spans.append((index, length, length + len(text) + 1))
        length += len(text) + 1

    sections, _ = detect_sections("".join(parts))
    section = next((s for s in sections if s.section_id == "item_8"), None)
    if section is None:
        return None

    start, end = section.location.char_start, section.location.char_end
    covering = [index for index, low, high in spans if low < end and high > start]
    if not covering:
        return None

    sliced = b"".join(
        lxml.html.tostring(children[index]) for index in range(min(covering), max(covering) + 1)
    )
    return sliced if len(sliced) >= MIN_SLICE_BYTES else None


def prepare_for_render(content: bytes, *, financial_statements_only: bool = True) -> str:
    """Narrow a filing's HTML to what is worth rendering to PDF.

    Falls back to the whole document whenever the financial statements cannot
    be isolated confidently, so an unusual filing still yields a usable PDF
    rather than an empty one.
    """
    root = lxml.html.fromstring(content)
    body = root.find("body")
    body = body if body is not None else root

    if financial_statements_only:
        children = [c for c in _branching_level(body) if isinstance(c.tag, str)]
        if children:
            sliced = _financial_statement_slice(children)
            if sliced is not None:
                return _wrap(sliced)
        logger.info("Financial statements could not be isolated; rendering the whole filing")

    return _wrap(lxml.html.tostring(body))


def _wrap(body_html: bytes) -> str:
    return "<html><body>" + body_html.decode("utf-8", errors="replace") + "</body></html>"


def html_to_pdf(html: str, *, user_css: str = TABLE_CSS) -> bytes:
    """Render `html` to PDF bytes."""
    buffer = io.BytesIO()
    story = pymupdf.Story(html=html, user_css=user_css)
    writer = pymupdf.DocumentWriter(buffer)
    page_box = pymupdf.paper_rect("letter")
    content_box = page_box + (36, 36, -36, -36)

    more = True
    pages = 0
    while more and pages < MAX_PAGES:
        device = writer.begin_page(page_box)
        more, _ = story.place(content_box)
        story.draw(device)
        writer.end_page()
        pages += 1

    writer.close()
    if more:
        logger.warning("Render stopped at the %d-page cap; output is truncated", MAX_PAGES)
    return buffer.getvalue()
