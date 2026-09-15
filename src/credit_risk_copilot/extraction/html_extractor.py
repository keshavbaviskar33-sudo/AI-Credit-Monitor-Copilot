"""Extract text, tables and sections from SEC 10-K HTML / inline XBRL.

This is the primary document path for SEC filers: EDGAR publishes 10-Ks as
HTML (increasingly inline XBRL), never as PDF. Inline-XBRL tags such as
`<ix:nonFraction>` wrap the displayed value, so reading element text gets the
same string a human sees -- this extractor deliberately reads the *document*,
not the embedded XBRL facts. Those come from the `companyfacts` API and remain
the source of record for numbers (D-005).

Tables are emitted as raw cell strings. Interpreting them -- units, negative
parentheses, which column is which fiscal year -- is Phase 5.
"""

from __future__ import annotations

import re

import lxml.html
from lxml import etree

from credit_risk_copilot.extraction.base import DocumentExtractionError
from credit_risk_copilot.extraction.models import (
    DocumentLocation,
    DocumentSource,
    ExtractedDocument,
    ExtractionError,
    Table,
    TextBlock,
)
from credit_risk_copilot.extraction.sections import (
    assign_sections,
    check_expected_content,
    detect_sections,
)

EXTRACTOR_NAME = "html"
EXTRACTOR_VERSION = "1.0"

# Non-content elements: their text is markup machinery, not document text.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "meta", "link", "title"})

# Elements that end a run of text. Without these, an entire filing collapses
# into one block and character offsets stop meaning anything useful.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "tr",
        "li",
        "ul",
        "ol",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "blockquote",
    }
)

#: How much preceding text to keep as a table's context, and how many blocks to
#: draw it from. Three blocks covers the usual "company name / statement title /
#: units declaration" run without dragging in the previous table's footnotes.
_CONTEXT_BLOCKS = 3
_CONTEXT_CHARS = 300

#: Guard against a malformed `colspan="9999"` blowing up a row.
_MAX_SPAN = 50

_WHITESPACE = re.compile(r"\s+")


def _span(cell: etree._Element, attribute: str) -> int:
    try:
        value = int(cell.get(attribute) or 1)
    except ValueError:
        return 1
    return max(1, min(value, _MAX_SPAN))


def _expand_grid(element: etree._Element) -> list[tuple[str, ...]]:
    """Read a table into a rectangular grid, expanding `colspan`/`rowspan`.

    This is the difference between a table Phase 5 can use and one it cannot.
    Filings lay statements out with heavy colspan — in Apple's FY2025 balance
    sheet the header row holds 4 cells and the data rows 6 or 8, so column
    index 2 means different things on different rows and pairing a figure with
    its fiscal year is guesswork. Expanded, every row is 12 wide and the header
    date sits in the same column as its values.

    Spanned cells repeat as empty strings rather than duplicating their text,
    so a value is never counted twice.
    """
    grid: list[list[str]] = []
    carried: dict[int, int] = {}  # column -> remaining rowspan rows to skip

    for row_element in element.iter("tr"):
        row: list[str] = []
        for cell in row_element.iter("td", "th"):
            while carried.get(len(row), 0):
                carried[len(row)] -= 1
                row.append("")
            text = _clean("".join(cell.itertext()))
            colspan = _span(cell, "colspan")
            rowspan = _span(cell, "rowspan")
            if rowspan > 1:
                for offset in range(colspan):
                    carried[len(row) + offset] = rowspan - 1
            row.extend([text] + [""] * (colspan - 1))
        if any(cell.strip() for cell in row):
            grid.append(row)

    width = max((len(row) for row in grid), default=0)
    return [tuple(row + [""] * (width - len(row))) for row in grid]


def _clean(value: str) -> str:
    """Collapse every run of whitespace, newlines included, to a single space.

    Filing HTML is full of `&nbsp;` and newline-indented markup. Newlines have
    to go too: the document's own line breaks are inserted between blocks by
    `_Accumulator._append`, and a stray newline *inside* a block would let the
    line-anchored heading patterns in `sections` match mid-paragraph.
    """
    return _WHITESPACE.sub(" ", value.replace("\xa0", " ")).strip()


class _Accumulator:
    """Builds the document text while recording where each part landed."""

    def __init__(self, tree: etree._ElementTree) -> None:
        self._tree = tree
        self._parts: list[str] = []
        self._length = 0
        self._buffer: list[str] = []
        self._buffer_path: str | None = None
        self.blocks: list[TextBlock] = []
        self.tables: list[Table] = []
        self.errors: list[ExtractionError] = []

    def _path(self, element: etree._Element) -> str:
        try:
            return str(self._tree.getpath(element))
        except (ValueError, TypeError):  # detached or comment nodes
            return ""

    def add_text(self, value: str | None, element: etree._Element) -> None:
        if not value or not value.strip():
            return
        if self._buffer_path is None:
            self._buffer_path = self._path(element)
        self._buffer.append(value)

    def _append(self, text: str) -> tuple[int, int]:
        """Append `text` plus a newline to the document, returning its span."""
        start = self._length
        self._parts.append(text + "\n")
        self._length += len(text) + 1
        return start, start + len(text)

    def flush(self) -> None:
        """Close the current run of text as a block."""
        if not self._buffer:
            return
        text = _clean(" ".join(self._buffer))
        path, self._buffer, self._buffer_path = self._buffer_path, [], None
        if not text:
            return
        start, end = self._append(text)
        self.blocks.append(
            TextBlock(
                text=text,
                location=DocumentLocation(char_start=start, char_end=end, element_path=path),
            )
        )

    def add_table(self, element: etree._Element) -> None:
        """Emit a table, and mirror its cells into the document text.

        The text mirror matters: section detection and any later verbatim quote
        run over `text`, and a 10-K's Item 8 is almost entirely tables. Leaving
        them out of `text` would make that section look empty.
        """
        rows = _expand_grid(element)

        # Filings use borderless tables for page layout as well as for data;
        # a table whose every cell is empty is spacing, not lost content. It is
        # skipped silently so genuine errors stay visible (a real 10-K carries
        # a handful of these, and reporting them drowns the signal).
        if not rows:
            return

        caption_el = element.find("caption")
        caption = _clean("".join(caption_el.itertext())) if caption_el is not None else None

        start, end = self._append("\n".join("\t".join(row) for row in rows))
        self.tables.append(
            Table(
                rows=tuple(rows),
                caption=caption or None,
                context=self._recent_context(),
                location=DocumentLocation(
                    char_start=start, char_end=end, element_path=self._path(element)
                ),
            )
        )

    def _recent_context(self) -> str | None:
        """The last few text blocks before this table.

        Filings put the statement title and the units declaration in the
        paragraphs immediately above the table -- "CONSOLIDATED BALANCE
        SHEETS", then "(In millions, except number of shares...)". Phase 5
        needs both to identify the statement and to avoid the wrong-scale error
        R-09 warns about, and neither appears inside the table itself.
        """
        recent = [block.text for block in self.blocks[-_CONTEXT_BLOCKS:] if block.text]
        if not recent:
            return None
        return " | ".join(recent)[-_CONTEXT_CHARS:]

    @property
    def text(self) -> str:
        return "".join(self._parts)


class HtmlDocumentExtractor:
    """Extracts a 10-K HTML document into located text, tables and sections."""

    name = EXTRACTOR_NAME
    version = EXTRACTOR_VERSION

    def extract(self, content: bytes, source: DocumentSource) -> ExtractedDocument:
        root = _parse(content)
        tree = root.getroottree()
        acc = _Accumulator(tree)

        walker = etree.iterwalk(root, events=("start", "end"))
        for action, element in walker:
            tag = element.tag if isinstance(element.tag, str) else ""
            # Inline XBRL and namespaced tags arrive as "{uri}local" or
            # "ix:local"; compare on the local name so `<ix:table>` and a
            # plain `<table>` behave the same.
            local = tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()

            if action == "start":
                if local in _SKIP_TAGS:
                    walker.skip_subtree()
                    continue
                if local == "table":
                    walker.skip_subtree()
                    acc.flush()
                    acc.add_table(element)
                    continue
                if local in _BLOCK_TAGS:
                    acc.flush()
                acc.add_text(element.text, element)
            else:
                # `skip_subtree` still fires this element's end event, so tails
                # are handled here exactly once for every element.
                if local in _BLOCK_TAGS or local == "table":
                    acc.flush()
                acc.add_text(element.tail, element)

        acc.flush()

        sections, section_errors = detect_sections(acc.text)
        tables = assign_sections(tuple(acc.tables), sections)
        return ExtractedDocument(
            source=source,
            extractor=self.name,
            extractor_version=self.version,
            text=acc.text,
            blocks=assign_sections(tuple(acc.blocks), sections),
            tables=tables,
            sections=sections,
            errors=tuple(acc.errors)
            + section_errors
            + check_expected_content(tables, sections),
        )


def _parse(content: bytes) -> etree._Element:
    """Parse filing HTML, tolerating the malformed markup EDGAR is full of."""
    if not content.strip():
        raise DocumentExtractionError("HTML document is empty.")
    try:
        root = lxml.html.fromstring(content)
    except etree.ParserError as exc:  # pragma: no cover - lxml recovers from almost anything
        raise DocumentExtractionError(f"HTML could not be parsed: {exc}") from exc
    body = root.find("body")
    return body if body is not None else root
