# Golden Evaluation Set — 10-K Documents with XBRL Reference Values

| | |
|---|---|
| **Status** | Draft v0.1 — Phase 4 |
| **Date** | 2026-09-15 |
| **Related** | [D-005](decision_log.md) · [D-014](decision_log.md) · [D-015](decision_log.md) · [extraction.md](extraction.md) · [product_requirements.md](product_requirements.md) (QM-01) · [risks.md](risks.md) (R-09, R-19) |

QM-01 measures field-level extraction accuracy against XBRL. That needs a fixed
corpus where the document and a trustworthy reference for the same numbers both
exist. This is that corpus.

Built by `scripts/build_golden_set.py`. Outputs land in
`data/processed/golden_set/` — gitignored like all of `data/`, and rebuilt by
rerunning the script (everything is cached, so a rerun costs no SEC requests).

## 1. What each filing contributes

```
filing HTML (EDGAR primary document)   ->  extracted  (HtmlDocumentExtractor)
same HTML rendered to PDF              ->  extracted  (PdfDocumentExtractor)
companyfacts filtered to that accession ->  reference values
```

| File | Contents |
|---|---|
| `manifest.json` | One entry per filing: company, CIK, SIC, cohort, accession, form, filing/period dates, document paths, and per-path extraction stats |
| `reference_values.csv` | The XBRL ground truth: one row per (filing, concept, unit, period) with `val`, `end`, `fy`, `fp`, `filed`, `accn` |
| `pdf/<accession>.pdf` | The generated PDF rendition |
| `table_extraction_spike.csv` | Per-filing R-19 measurements (§5) |

## 2. Why the reference is filtered by accession

`companyfacts` returns every fact SEC holds for a company, including values that
*later* filings restated. Filtering on `accn` returns only what **that filing
reported** — including its comparative prior-year columns, which is exactly what
a document extractor will find in the same table.

This is what makes the reference point-in-time honest ([D-008](decision_log.md)).
A reference built without the `accn` filter would quietly grade the extractor
against numbers the document never contained.

One nuance for Phase 5: in these rows `fy`/`fp` identify the *filing's* fiscal
context, not the period each value covers — several rows in one filing share
`fy=2025` while their `end` dates span different years. **`end` is the period
identifier; `filed` is the point-in-time key.**

## 3. Composition

Twelve filings in two cohorts, chosen to be a fair test rather than a flattering
one:

- **Distressed (6)** — companies that later filed for bankruptcy, drawn from the
  Phase 3 linkage audit (`data/processed/brd_sec_linkage_audit.csv`). For each,
  the script takes the **last 10-K filed before the bankruptcy petition** — the
  filing an analyst would actually have been monitoring. Picked by hand rather
  than "top N by history", which would have returned almost only oil and gas;
  the corpus needs industry spread to test extraction fairly.
- **Healthy (6)** — large non-financial filers with no bankruptcy event.

Financial-sector companies are deliberately absent ([D-006](decision_log.md)).
The exact SIC exclusion ranges are Phase 5/7 work, so the manifest **records**
each company's SIC rather than pre-empting that rule here.

> **Overlap warning for Phase 8.** These are extraction-evaluation filings, not
> a model test set. [scope.md §6](scope.md) requires demo companies to be
> excluded from model training data; whoever builds the Phase 8 splits must
> check this list against them rather than assume they are disjoint.

## 4. Limitations to carry forward

1. **Generated PDFs are cleaner than real ones.** They have a perfect text
   layer, consistent fonts and no scan artefacts. **QM-01's PDF figure is
   therefore an upper bound**, not an estimate of accuracy on a real analyst
   upload ([D-014](decision_log.md)).
2. **Rendering adds table borders, and that changes what counts as a table.**
   `render.TABLE_CSS` borders every table, including the borderless ones filings
   use purely for page layout. Table *counts* on the PDF path are consequently
   inflated relative to HTML — a counting artefact, not extra data. This is why
   §5 measures reference-value recall instead of table counts.
3. **BRD stops at December 2022**, so no bankruptcy after that date is labelled
   ([D-013](decision_log.md)); the distressed cohort cannot include recent events.
4. **Twelve filings is small.** It is enough to catch systematic extraction
   failures, not to produce a tight accuracy estimate. Report intervals, not
   just point estimates, when QM-01 lands in Phase 5.

## 5. R-19: which PDF library, measured

[R-19](risks.md) requires a spike and a measurement before committing to a
library. `scripts/table_extraction_spike.py` compares **pdfplumber** and
**pymupdf** across the golden set.

**The metric is reference-value recall, not table count** — counting tables
rewards a library for finding layout scaffolding. For each reference value, the
spike asks whether that number appears in any cell the library extracted,
allowing for the scales a filing may present it at (units, thousands, millions)
and the conventions it may use (comma grouping, parentheses for negatives).

This is a deliberate *preview* of QM-01, not QM-01: it asks "is this number
present in some extracted cell", where QM-01 asks "was it extracted as the
correct labelled field". Labelling needs Phase 5's canonical schema, so read
these figures as an upper bound on both paths.

<!-- RESULTS -->

### The finding that shaped the design

`pymupdf.Story` renders tables with **no ruling lines**, and a borderless render
defeats table detection in *both* libraries — pdfplumber's line strategy returns
nothing, its text strategy returns shredded cells (`"I"`, `"tem"`), and
pymupdf's `find_tables` also returns nothing. Adding borders restores exact
extraction in both.

This matters beyond the golden set: **real uploaded financial statements are
often borderless**, so this is a live limitation of the FR-04 upload path, not a
solved problem. It is recorded under [R-09/R-19](risks.md) and guarded by a
regression test (`tests/test_extraction_pdf.py::test_borderless_render_is_why_the_table_css_exists`).
