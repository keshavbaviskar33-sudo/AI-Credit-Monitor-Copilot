# Document Extraction — Design

| | |
|---|---|
| **Status** | Draft v0.1 — Phase 4 |
| **Date** | 2026-09-15 |
| **Related** | [D-005](decision_log.md) · [D-014](decision_log.md) · [D-015](decision_log.md) · [golden_set.md](golden_set.md) · [product_requirements.md](product_requirements.md) (FR-04, FR-07, SC-01, SC-03) |

Phase 4 turns filing documents into **located** text, tables and sections. It
deliberately does not interpret anything it extracts: units, signs, aliases and
the canonical line-item schema are Phase 5.

## 1. What this layer is for

Two consumers, and it is worth being clear that they want different things:

1. **Narrative sections → Phase 10 NLP.** Risk Factors and MD&A, as character
   spans, so extracted evidence quotes can be checked verbatim against the
   source (SC-03).
2. **Financial statement tables → Phase 5 parsing.** Raw cells, measured for
   accuracy against XBRL (QM-01).

For SEC filers the *numbers* still come from XBRL, not from this layer
([D-005](decision_log.md)). Document extraction exists to be measured against
XBRL, to serve analyst uploads that have no XBRL at all (FR-04), and to reach
the narrative that XBRL does not contain. It is not trying to beat XBRL.

## 2. Provenance is the point

Every `TextBlock`, `Table` and `DocumentSection` carries a `DocumentLocation`
with `char_start`/`char_end` offsets into `ExtractedDocument.text`. That single
invariant — *a location always slices back to the content it describes* — is
what SC-01 ("100% of displayed values have resolvable provenance") and SC-03
("evidence quotes are present verbatim") are later checked against. It is
covered directly by tests in `tests/test_extraction_html.py` and
`tests/test_extraction_pdf.py`.

Format-specific detail rides alongside: `page` for PDFs, `element_path` (an
XPath) for HTML.

## 3. Two paths, one interface

| | HTML (`HtmlDocumentExtractor`) | PDF (`PdfDocumentExtractor`) |
|---|---|---|
| Input | EDGAR 10-K primary document | Analyst upload (FR-04); generated golden-set PDFs |
| Library | `lxml` | `pdfplumber` ([D-015](decision_log.md)) |
| Location detail | `element_path` | `page` |
| Tables | `<table>` elements, cells verbatim | Geometric detection from ruling lines |

Both satisfy the `DocumentExtractor` protocol in `extraction/base.py`, so Phase
5 depends on the interface rather than on either library.

### HTML specifics

- **Inline XBRL is read as text, not as facts.** `<ix:nonFraction>` wraps the
  value a human sees, so reading element text yields the displayed string.
  Tags are matched on their local name, so `<ix:table>` behaves like `<table>`.
- **Block boundaries are what make offsets meaningful.** Without them a filing
  collapses into one block. Whitespace inside a block is collapsed to single
  spaces — newlines included, because a stray newline inside a block would let
  the line-anchored heading patterns match mid-paragraph.
- **Table text is mirrored into `text`.** Item 8 is almost entirely tables; if
  they were not in `text`, that section would appear empty.
- **Empty tables are skipped silently.** Filings use borderless empty tables
  for page layout — a real 10-K carries several. They lose no content, and
  reporting them would bury genuine errors.

### PDF specifics

- Text-based PDFs only. A page with no extractable text yields a
  `page_without_text` error rather than contributing nothing silently; OCR is
  out of MVP scope ([scope.md §4](scope.md)).
- A table's location is its **page's** text span, not a span of its own:
  pdfplumber finds tables geometrically, so the cells are already part of the
  page text. Appending them again would duplicate content and break offsets.

## 4. Section detection

`extraction/sections.py` locates 10-K items as character spans. Naive heading
matching fails in three specific ways, and the design addresses each:

| Problem | Why it breaks matching | Handling |
|---|---|---|
| **Table of contents** | Every item heading appears there first | Rank candidates by how much text follows; a TOC line is bounded by the next TOC line, so it scores near zero |
| **Cross references** | "…described in Item 1A. Risk Factors…" | Headings must begin a line; span ranking removes the rest |
| **`Item 1` vs `Item 1A`** | Prefix collision, in both directions | Trailing `(?![A-Za-z0-9])` guard |

The full item list (1 through 16) is declared even though only Item 1, 1A, 3,
7, 7A and 8 are returned. The rest exist as **boundaries** — a section ends
where the next item begins. This matters most for Item 8: it is the last
reported item, so without Items 9–16 its span would run to the end of the
document, and the table-of-contents match would then win on length. That was a
real bug caught against a live filing, and `tests/test_sections.py` guards it.

A required section that cannot be located with a plausible body produces a
`section_not_found` error and no section. It is never approximated —
"insufficient information" is a valid answer ([principle 4](product_requirements.md)).

Detection accuracy on a real sample is measured in **Phase 10** (A-10); Phase 4
delivers the mechanism and a filing-level sanity check (§6).

## 5. Upload validation (FR-04)

`extraction/upload.py` checks uploads before anything parses them, and every
rejection names a reason:

| Code | Trigger |
|---|---|
| `unsupported_type` | Extension not `.pdf`, **or** the bytes are not a PDF regardless of extension |
| `empty_file` | Zero bytes |
| `too_large` | Over `Settings.max_upload_bytes` (default 25 MB) |
| `not_parseable` | PDF cannot be opened, or has no pages |
| `no_extractable_text` | Opens fine but has no text layer — i.e. a scan |

The file is inspected as bytes and never executed, rendered or resolved
(NFR Security, R-16). The extension is never trusted on its own: a renamed
file must not reach a parser that assumes the suffix told the truth.

## 6. Verified against a real filing

Run against Apple's FY2025 10-K (accession `0000320193-25-000079`, 1.5 MB of
HTML) the HTML extractor produced 222,705 characters, 645 blocks, 54 tables and
**zero errors**, with all six reported sections landing on real section bodies
rather than contents entries:

| Section | Body | Starts with |
|---|---:|---|
| Item 1 | 16,051 | "Company Background / The Company designs, manufactures…" |
| Item 1A | 68,045 | "The following summarizes factors that could have a material adverse effect…" |
| Item 3 | 5,399 | "Digital Markets Act Investigations…" |
| Item 7 | 18,202 | "The following discussion should be read in conjunction with…" |
| Item 7A | 3,035 | "The Company is exposed to economic risk from interest rates…" |
| Item 8 | 62,765 | "Index to Consolidated Financial Statements…" |

## 7. Known limitations

- Section detection is tuned to US 10-K item conventions. Filings that deviate
  (unusual heading wording, items split across exhibits) will report
  `section_not_found` rather than mis-locate — the safe failure, but still a
  failure. Measured properly in Phase 10.
- Table extraction returns raw cells with no notion of which column is which
  fiscal year, or whether figures are in thousands. Phase 5.
- Multi-document filings are not followed: only the primary document is
  extracted. Financial statements filed as separate exhibits would be missed.
- HTML tables are matched structurally, so financial data laid out with
  positioned `<div>`s rather than `<table>` would not be seen as a table.
- Generated golden-set PDFs are cleaner than real-world PDFs; see
  [golden_set.md](golden_set.md) for why that makes QM-01's PDF figure an
  upper bound.
