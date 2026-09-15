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
"""

from __future__ import annotations

import io

import pymupdf

#: Ruled, tightly-padded tables so table detection has edges to find.
#: `border-collapse` keeps adjacent cells from drawing doubled lines, which
#: confuses edge-based detection as badly as having none.
TABLE_CSS = """
table { border-collapse: collapse; }
table, th, td { border: 0.5px solid #000; padding: 2px; }
body { font-family: sans-serif; font-size: 9px; }
"""

#: Guards against a pathological document paginating forever. A 10-K runs to
#: a few hundred pages; well beyond that means the renderer is not converging.
MAX_PAGES = 2000


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
    return buffer.getvalue()
