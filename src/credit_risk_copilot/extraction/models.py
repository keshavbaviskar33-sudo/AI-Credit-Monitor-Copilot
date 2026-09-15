"""Typed document-extraction results, with provenance on every unit of output.

The product principle is "evidence or nothing" (product_requirements.md §4):
anything the pipeline later displays must be traceable back to a place in a
source document. So every block, table and section carries a
`DocumentLocation`, and anything that could not be extracted becomes an
explicit `ExtractionError` rather than a silent omission (R-09).

These are *document* models. The canonical financial line-item schema is Phase
5 work and deliberately lives elsewhere.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DocumentLocation(BaseModel):
    """Where a piece of extracted content came from.

    `char_start`/`char_end` index into `ExtractedDocument.text` for every
    extractor, so quotes stay verifiable regardless of source format (SC-03).
    `page` is populated by page-oriented sources (PDF) and left unset for
    flow-oriented ones (HTML); `element_path` is the reverse.
    """

    model_config = ConfigDict(frozen=True)

    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    element_path: str | None = None
    section_id: str | None = None
    #: PDF only: (x0, top, x1, bottom) in PDF points, for highlighting a region
    #: back to the analyst and for locating text around a table.
    bbox: tuple[float, float, float, float] | None = None


class TextBlock(BaseModel):
    """A paragraph-level run of text."""

    model_config = ConfigDict(frozen=True)

    text: str
    location: DocumentLocation


class Table(BaseModel):
    """A tabular region, kept as raw cell strings on a rectangular grid.

    No *interpretation* happens here: units, signs, parentheses-as-negative and
    which column is which fiscal year are Phase 5's problem. What does happen is
    *structural* normalisation, which Phase 5 cannot recover on its own —
    `colspan`/`rowspan` are expanded so every row has the same width and a
    column index means the same thing in the header as in the data rows.

    The properties below report measurable facts about the grid. They are
    deliberately not a "confidence score": an invented number would look like
    evidence without being any. Phase 5 decides what the facts imply.
    """

    model_config = ConfigDict(frozen=True)

    rows: tuple[tuple[str, ...], ...]
    location: DocumentLocation
    caption: str | None = None
    #: Text immediately preceding the table — in filings this is where the
    #: statement title and the units declaration live ("CONSOLIDATED BALANCE
    #: SHEETS", "(In millions, except share data)"). Phase 5 needs both, and
    #: neither is inside the table.
    context: str | None = None

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    @property
    def is_rectangular(self) -> bool:
        """Whether every row has the same width, so column indices line up."""
        return len({len(row) for row in self.rows}) <= 1

    @property
    def numeric_density(self) -> float:
        """Fraction of non-empty cells containing a digit.

        Filings use tables for page layout as much as for data; density
        separates the two far more reliably than size does.
        """
        cells = [cell for row in self.rows for cell in row if cell.strip()]
        if not cells:
            return 0.0
        return sum(1 for cell in cells if any(c.isdigit() for c in cell)) / len(cells)

    @property
    def has_row_labels(self) -> bool:
        """Whether the first column reads as labels rather than figures."""
        first = [row[0].strip() for row in self.rows if row and row[0].strip()]
        if not first:
            return False
        wordy = sum(1 for cell in first if any(c.isalpha() for c in cell))
        return wordy / len(first) > 0.5

    @property
    def looks_like_financial_data(self) -> bool:
        """A cheap screen so Phase 5 can skip page-layout scaffolding.

        Intentionally permissive: it is a filter to narrow work, not a
        classifier to trust. A table failing this is still returned.
        """
        return self.n_rows >= 3 and self.numeric_density >= 0.25 and self.has_row_labels


class DocumentSection(BaseModel):
    """A located 10-K item section (e.g. Item 1A Risk Factors)."""

    model_config = ConfigDict(frozen=True)

    section_id: str
    title: str
    heading_text: str
    location: DocumentLocation


class ExtractionError(BaseModel):
    """Something that could not be extracted, stated rather than hidden.

    Carried alongside the results instead of raised, so one bad table or one
    missing section degrades that part to `insufficient_data` without losing
    the rest of the document (the "fail-safe behaviour" NFR).
    """

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    location: DocumentLocation | None = None


class DocumentSource(BaseModel):
    """Identity of the document that was extracted.

    SEC fields are optional because analyst-uploaded PDFs (FR-04) have no
    accession number; `uri` is always present so provenance never dead-ends.
    """

    model_config = ConfigDict(frozen=True)

    uri: str
    media_type: str
    cik: int | None = None
    accession: str | None = None
    form: str | None = None
    filed: str | None = None


class ExtractedDocument(BaseModel):
    """Everything one extractor produced from one document."""

    model_config = ConfigDict(frozen=True)

    source: DocumentSource
    extractor: str
    extractor_version: str
    text: str
    blocks: tuple[TextBlock, ...] = ()
    tables: tuple[Table, ...] = ()
    sections: tuple[DocumentSection, ...] = ()
    errors: tuple[ExtractionError, ...] = ()

    def section(self, section_id: str) -> DocumentSection | None:
        """The section with this id, or None if it was not located."""
        return next((s for s in self.sections if s.section_id == section_id), None)

    def section_text(self, section_id: str) -> str | None:
        """The verbatim text of a located section, sliced from `text`."""
        section = self.section(section_id)
        if section is None:
            return None
        return self.text[section.location.char_start : section.location.char_end]
