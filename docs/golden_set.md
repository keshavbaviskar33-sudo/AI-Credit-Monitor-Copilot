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
filing HTML (EDGAR primary document)      -> extracted (HtmlDocumentExtractor)
  narrowed to Item 8, rendered to PDF     -> extracted (PdfDocumentExtractor)
companyfacts filtered to that accession   -> reference values
```

Both extractions run over the **same** filing, and the reference values come
from that filing's own XBRL — so the two paths are directly comparable against
one ground truth. The PDF is narrowed to the financial statements (§6); when
that is not possible the whole filing is rendered instead.

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

### As built (2026-09-15)

12 filings, **342 reference values**, spanning 2016–2026 and eleven SIC
industries. No filing failed to extract, and none lacked XBRL reference values.

| Company | Cohort | SIC | Filed | HTML tables | PDF tables | Sections |
|---|---|---|---|---:|---:|---:|
| Expand Energy (Chesapeake) | distressed | 1311 | 2020-02-27 | 359 | 507 | 6 |
| iHeartMedia | distressed | 4832 | 2017-02-23 | 323 | 371 | 5 |
| Frontier Communications | distressed | 4813 | 2020-03-31 | 275 | 953 | 6 |
| Peabody Energy | distressed | 1221 | 2016-03-16 | 556 | 1,239 | 6 |
| Pyxus International | distressed | 5150 | 2019-06-14 | 194 | 466 | 6 |
| SandRidge Energy | distressed | 1311 | 2016-03-30 | 365 | 1,202 | 5 † |
| Apple | healthy | 3571 | 2025-10-31 | 54 | 234 | 6 |
| Tesla | healthy | 3711 | 2026-01-29 | 77 | 585 | 6 |
| Walmart | healthy | 5331 | 2026-03-13 | 109 | 427 | 6 |
| Pfizer | healthy | 2834 | 2026-02-26 | 264 | 274 | 6 |
| Coca-Cola | healthy | 2080 | 2026-02-20 | 117 | 349 | 6 |
| UPS | healthy | 4210 | 2026-02-17 | 108 | 481 | 6 |

† SandRidge's **Item 8 could not be located** and is reported as
`section_not_found` — the intended failure, since the alternative is a
confidently wrong span. It uses the F-pages layout described below.

Two patterns in this table are worth carrying forward:

- **PDF table counts exceed HTML counts everywhere**, sometimes threefold
  (Frontier 275 → 953). That is the border artefact of limitation 2, not extra
  data recovered — and the reason §5 does not measure table counts.
- **The F-pages layout is common in older filings.** Four of the six distressed
  filings (2016–2020) satisfy Item 8 with a cross-reference and put the
  statements in an appendix, so they fell back to whole-filing rendering; none
  of the six 2025–26 filings did. Section detection tuned only on modern
  filings would look better than it is.

### Concept coverage — the most consequential finding

Measuring the 342 reference values per concept turned [A-06](assumptions.md)
from an assumption into a number, and the number is worse than assumed:
`Liabilities` is present for **6/12** filings, `LongTermDebt` **7/12**,
`Revenues` **9/12**, and `SalesRevenueNet` — which the Phase 3 concept list
named as the revenue fallback — for **0/12**. It is deprecated; modern filers
use `RevenueFromContractWithCustomerExcludingAssessedTax`.

Full table and the consequences for Phase 5 are in
[data_dictionary.md §6.1](data_dictionary.md). The short version: a ratio
engine doing single-tag lookups would return `missing_input` for half the
population on leverage ratios.

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
3. **The PDF holds the financial statements, not the whole filing.**
   `render.prepare_for_render` narrows each filing to Item 8 (see §6). That
   matches what QM-01 measures and what FR-04 users actually upload, but it
   means the PDF path cannot be used to evaluate narrative-section detection —
   that stays an HTML-path concern (A-10, Phase 10). When Item 8 cannot be
   isolated confidently the whole filing is rendered instead, so a few entries
   are full-length.
4. **BRD stops at December 2022**, so no bankruptcy after that date is labelled
   ([D-013](decision_log.md)); the distressed cohort cannot include recent events.
5. **Twelve filings is small.** It is enough to catch systematic extraction
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

## 6. Rendering cost, and a hypothesis that measurement killed

The first build attempt was killed by the operating system for exhausting
memory. Diagnosing it produced three findings worth recording, because two of
them contradict the obvious fix.

**Filing HTML must not have its presentation attributes stripped.** Stripping
inline `style` looked like an easy win — it took iHeartMedia's 2016 filing from
a ten-minute render to one second. It is also wrong. Modern filings carry their
table *column widths* in inline `style`; without them a many-column financial
statement gets near-zero column widths and wraps one character per line.
Measured on Apple's FY2025 10-K:

| Apple FY2025 10-K (Item 8) | Pages | PDF size | Render |
|---|---:|---:|---:|
| As filed | 41 | 2.9 MB | < 1 s |
| With `style` stripped | 2,500+ (did not converge) | 65 MB | 7 s |

**Narrowing to the financial statements is the fix that holds.** It bounds the
work without touching the filing's own markup, and produces the more faithful
artefact besides. Isolating Item 8 has to descend past single-child wrappers
first: Apple's filing puts ~800 siblings directly under `<body>`, while
iHeartMedia's and Chesapeake's wrap the whole document in one `<div>`, where
slicing the body would be a silent no-op.

**The expensive step is table extraction, not rendering.** After narrowing,
end-to-end cost is dominated by pdfplumber:

| Filing | Pages | Render | Extract | Reference values recovered |
|---|---:|---:|---:|---|
| Apple FY2025 | 40 | < 1 s | 29 s | **10 / 10** |
| iHeartMedia 2016 | 80 | 2 s | 77 s | — |
| Chesapeake 2019 | 152 | 6 s | 179 s | — |

pdfplumber caches each page's parsed objects and never releases them, so a few
hundred table-dense pages exhaust memory — the original crash.
`PdfDocumentExtractor` now flushes each page's cache once it is done with it.

The Apple row is the load-bearing one: all ten XBRL reference values for that
filing are recoverable from cells extracted out of the generated PDF, which is
what makes the corpus usable for QM-01 at all.
