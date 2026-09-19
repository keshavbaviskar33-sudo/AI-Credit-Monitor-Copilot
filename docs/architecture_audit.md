# Architecture & Build-vs-Buy Audit — Phases 1–7

| | |
|---|---|
| **Status** | **Historical.** Audit complete 2026-09-17, against the code as it stood at Phase 7. Migration: M-1, M-3, M-4 done; **M-2 resolved by events, M-5 still open** — see [§7](#7-recommended-migration-sequence) |
| **Date** | 2026-09-17 (status reviewed 2026-09-19, Phase 19) |
| **Scope** | Everything built through Phase 7, plus library/tooling posture for Phases 8–20 |
| **Baseline verified** | 324 tests pass · 97% line coverage · `ruff check` clean · `ruff format` clean · `mypy --strict` clean (35 files) — *the Phase 7 baseline; the current one is 758 tests, 94% coverage, 79 files* |
| **Related** | [architecture.md](architecture.md) · [roadmap.md](roadmap.md) · [decision_log.md](decision_log.md) · [canonical_schema.md](canonical_schema.md) · [ratios.md](ratios.md) · [financial_health.md](financial_health.md) |

> **Read [architecture.md](architecture.md) for the architecture as it is now.**
> This document is a Phase 1–7 artifact and is kept as one ([D-056](decision_log.md)):
> it records what was considered and rejected as a dependency and why the
> custom code is custom, which is reasoning that does not expire — and it
> contains its own most important finding, [§F-1](#f-1-the-multi-filing-path-is-built-tested-and-unused),
> that the multi-filing point-in-time path was built, tested, exported and had
> never been run against real data. That finding and its M-4 resolution are the
> reason two phases of quality numbers had to be re-measured, and preserving
> them in place is worth more than folding them into a current-state document.
>
> Everything below describes eleven packages when there were eight. Four of the
> nine boundaries [architecture.md §2](architecture.md) documents did not exist
> yet.

---

## Executive Summary

**1. Is the current architecture fundamentally sound?** Yes. The layering is
clean and the dependency direction is correct: `ratios/` imports exactly one
Phase 5 symbol (`financials.models.CanonicalFact`) and reaches its input
through a `FactGetter` callable rather than a Phase 5 object; `health/` sits on
Phase 6 results and never touches XBRL. Deleting the entire extraction package
would not break the ratio engine. Every layer is already an adapter over a
mature library where one exists (`lxml`, `pdfplumber`, `pymupdf`, `pydantic`,
`requests`), and the custom code sits above those adapters, where the domain
logic belongs. This is the hybrid shape §21 of the audit brief asks for — it is
already the architecture, not a proposal.

**2. What is unnecessarily custom?** Almost nothing. Two small items: `numpy` is
declared as a direct dependency and imported nowhere in the repository, and
`pandas` is a *core* dependency used only by `scripts/`. Neither is a design
flaw; both are dependency hygiene.

**3. What should definitely remain custom?** The canonical concept resolution
(`concept_map.py` + `resolver.py`), the provenance/confidence/status model, the
derivation rules, the ratio catalog and its four-state result model, and the
whole of `health/`. These are the product. Every external candidate examined
either lacks the as-filed provenance the point-in-time rule (D-008) depends on,
or requires a commercial data vendor, or imposes its own opaque
"standardization" in place of the reviewable per-concept policies D-016/D-018
deliberately built.

**4. What should be wrapped rather than adopted?** Nothing new today. For Phase
8 specifically, SEC's bulk **Financial Statement Data Sets** should be brought
in *behind the existing `XbrlFact` interface* rather than as a second data
model — see §7 and the migration plan.

**5. What should be replaced now?** No component. Zero replacements are
justified by evidence.

**6. What should be left alone?** Phases 1–6 in their entirety, and the
substance of Phase 7. The only Phase 7 change recommended is an added
parameter, not a rewrite.

**7. What should be deferred?** Arelle / inline-XBRL parsing, OCR, `edgartools`,
any financial-ratio package, any vector database, MLflow, FastAPI. None is
needed and several would be actively harmful to provenance.

**8. Is the project ready for Phase 8?** **Not yet — but the gap is two to
three days of wiring, not a library decision, and it is a gap in the project's
own already-written code rather than a missing capability.** See
[Phase 8 Readiness](#phase-8-readiness).

> **The single most important finding of this audit has nothing to do with open
> source.** The multi-filing, point-in-time path that D-001 (monitoring) and
> D-008 (as-filed) are built on — `CompanyFinancials.as_of()` →
> `ratios_from_facts()` → `analyze_financial_health()` — is fully implemented,
> unit-tested against fakes, exported from `financials/__init__.py`, and **has
> never been executed against real data by any script in the repository.**
> Running it changes the project's headline quality numbers more than any
> library swap could. Measurements in [§F-1](#f-1-the-multi-filing-path-is-built-tested-and-unused).
>
> **Resolved (M-4, 2026-09-18).** Wired up, measured and validated: ratio
> coverage 60.5% → 81.2%, conclusive trends 40.4% → 91.7%, and Pfizer's
> single-filing "0 signals" turns out to have been a false negative. The
> re-inspection found 3 endpoint artefacts in 90 trend signals and no
> fabrications. See [financial_health.md §7a](financial_health.md).

---

## 1. The architecture as actually implemented

The brief's assumed diagram is close but wrong in two places. Corrected against
the code:

```text
                    SEC EDGAR (data.sec.gov + www.sec.gov)
                              │
                 sec_edgar.py │ 174 LOC: throttle, User-Agent, on-disk cache
                              │
          ┌───────────────────┴────────────────────┐
          │                                        │
   companyfacts JSON                        10-K primary document (HTML)
   (SEC's own parsed XBRL)                          │
          │                                         │
   financials/xbrl.py                        extraction/ (lxml | pdfplumber)
   typed facts, accession-filtered                  │
          │                                  ExtractedDocument
          │                                  text · tables · sections · errors
          │                                         │
   financials/concept_map.py                        │  (one-directional,
   financials/resolver.py  ◄─────────────────────── │   corroboration only)
   financials/periods.py                 financials/reconciliation.py
   financials/validation.py                    ▲ raises confidence;
          │                                      absence changes nothing (D-017)
   CanonicalFilingFacts  (one filing)
          │
   financials/company.py  ── CompanyFinancials.as_of(cutoff)   ◄── BUILT, UNUSED
          │                  (multi-filing, as-filed, D-008)
          ▼
   ratios/  (13 definitions, FactGetter protocol)
          │
          ▼
   health/  (trends · 5 dimensions · 9 signal codes · no composite score)
          │
          ▼
   ── Phase 8 ML ── Phase 10 NLP ── Phase 12 synthesis ── human analyst ──
```

Two corrections to the assumed diagram:

**(a) There is no XBRL parsing in this project.** `financials/xbrl.py` reads
SEC's `companyfacts` JSON — SEC has already parsed the instance documents,
resolved contexts, and normalised periods. The audit brief's §6 checklist
(contexts, dimensions, decimals, segments, taxonomy variation) is therefore
largely *already outsourced to the SEC itself*, which is the strongest possible
form of "don't build it yourself." What the project builds on top is concept
*resolution*, which is a different problem and is genuinely product-specific.

This has a real cost that should be stated: `companyfacts` exposes only
dimensionless (consolidated) facts, drops `decimals`, and carries no statement
presentation or line ordering. The project has correctly decided it does not
need any of those yet. If it ever does, that is when Arelle enters the
conversation — not before.

**(b) Document extraction does not feed the canonical model.** D-017 made
reconciliation one-directional and secondary. The arrow in the brief's diagram
from "Evidence extraction" into "Financial fact resolution" does not exist in
the code, deliberately.

---

## 2. Component inventory

| Component | Current implementation | Problem solved | Commodity / Core | Existing alternatives | Evidence | Recommendation | Migration | Risk |
|---|---|---|---|---|---|---|---|---|
| SEC HTTP access | `sec_edgar.py`, 174 LOC: throttle, UA enforcement, byte cache | Rate-limited, cached EDGAR fetch | Commodity, but trivially so | `edgartools` (MIT), `sec-edgar-downloader` | 174 LOC, 83% covered; handles the `filings.files` overflow most wrappers miss | **KEEP** | — | — |
| Filing discovery | `annual_filings()` over `submissions` + overflow pages | Annual-form history per CIK | Commodity | `edgartools` | Correctly paginates overflow; verified on 157 real accessions | **KEEP** | — | — |
| XBRL parsing | *None — SEC `companyfacts`* | Instance → facts | Commodity, already outsourced | Arelle (Apache-2.0), py-xbrl | Project never sees an instance document | **KEEP (already borrowed)** | — | — |
| Typed XBRL facts | `financials/xbrl.py`, 95 LOC | JSON → `XbrlFact`, accession filter, extension flag | Thin adapter | — | 97% covered | **KEEP** | — | — |
| Period handling | `financials/periods.py`, `is_annual_period` | Duration vs instant; reject quarterly footnote collisions | **Core** | — | Prevents a documented real failure | **KEEP** | — | — |
| Concept mapping | `concept_map.py`, 597 LOC, 26 concepts, 3 tag policies | Canonical concept ← many tags | **Core product IP** | `edgartools` standardization, FinanceToolkit | D-018: accuracy 87.0% → 97.2%; `total_debt` 25% → 86% | **KEEP — do not outsource** | — | — |
| Resolution / derivation | `resolver.py`, 439 LOC, fixpoint derivation | Facts → canonical facts w/ provenance | **Core product IP** | — | QM-01 97.2%; 157 real accessions resolved, zero exceptions | **KEEP** | — | — |
| Validation | `validation.py`, 192 LOC, 100% covered | Balance-sheet, cash tie-out, sign sanity | **Core** | — | Non-circular by construction (D-018) | **IMPROVE** — extend to `CompanyFinancials` | S | LOW |
| Reconciliation | `reconciliation.py`, 78 LOC | XBRL value visible in the filing's own HTML | **Core** | — | 73.6% corroboration | **KEEP** | — | — |
| Multi-filing / PIT | `company.py`, 92 LOC — **built, never run on real data** | As-filed history across filings (D-008) | **Core** | — | §F-1: coverage 60.5%→81.2%, trends 40.4%→89.1% | **WIRE UP — highest priority** | M | MED |
| HTML extraction | `html_extractor.py` over `lxml` | Text, tables, colspan/rowspan grid, provenance | Adapter + core | BeautifulSoup, trafilatura | 85.1% reference recall (100% on 2025–26) | **KEEP** | — | — |
| PDF extraction | `pdf_extractor.py` over `pdfplumber` | Upload path (FR-04) | Adapter | pymupdf, Camelot, Docling | D-015: pdfplumber/pymupdf tied 179/179; 2.4× speed | **KEEP** | — | — |
| Table extraction | Delegated to `lxml` / `pdfplumber` | Cells + bbox + context | Commodity | Camelot, Docling, table-transformer | Bottleneck measured as *isolation*, not library | **DEFER** | — | — |
| OCR | Absent; reported as `ExtractionError` | Scanned uploads | Commodity | Tesseract, PaddleOCR, docTR | No scanned filing in corpus (SEC publishes none) | **DEFER** | — | — |
| Section detection | `sections.py`, 268 LOC, 100% covered | 10-K item boundaries for Phase 10 | **Core** | — | Deterministic, fully covered | **KEEP** | — | — |
| Upload validation | `upload.py`, 124 LOC | FR-04 size/type gate | Commodity | — | Uses `Settings.max_upload_bytes` | **KEEP** | — | — |
| Ratio catalog | `registry.py` + `engine.py`, 615 LOC, 100% covered | 13 ratios, 4-state status, structured warnings | **Core product IP** | FinanceToolkit (MIT, **needs FMP API key**), OpenBB | D-019/D-021; M-2 | **KEEP — replacement would be a downgrade** | — | — |
| Trend engine | `health/trend.py`, 274 LOC, 100% covered | Direction, persistence, baseline, robust z | **Core** | `scipy.stats`, `statsmodels` | Uses stdlib `median`; §F-2 window gap | **IMPROVE** — add window param | S | MED |
| Health signals | `health/signals.py` + `dimensions.py` | 9 signal codes, 5 dimensions, no score | **Core product IP** | — | 100% covered | **KEEP** | — | — |
| Thresholds | `health/thresholds.py`, each documented | FR-10 | **Core** | dynaconf, hydra | Analytical constants, not ops config | **KEEP** | — | — |
| Config | `config.py`, pydantic-settings | Env/`.env` | Commodity, already borrowed | — | 100% covered | **KEEP** | — | — |
| Logging | `logging_config.py`, 64 LOC incl. JSON formatter | Structured logs | Commodity | structlog, loguru | 64 LOC vs a dependency; adequate | **KEEP** | — | — |
| Caching | Byte-for-byte file cache in `sec_edgar.py` | Reproducible offline corpus | Commodity | requests-cache, diskcache | ~20 LOC; no invalidation needed (filings are immutable) | **KEEP** | — | — |
| Persistence | None (Phase 13/15) | — | Commodity | SQLAlchemy (declared) | — | **DEFER** | — | — |
| Evaluation harness | 4 `scripts/evaluate_*.py` + golden set | QM-01/02/03 | **Core** | — | Reproduced exactly by this audit | **IMPROVE** — see §F-1 | S | LOW |
| CI | **None** | — | Commodity | GitHub Actions | 324 tests run only by hand | **ADD** | S | LOW |

---

## 3. Findings

### F-1 The multi-filing path is built, tested, and unused

**Severity: high. No external library is involved.**

`CompanyFinancials.as_of()` and `ratios.ratios_from_facts()` exist, are
exported, are unit-tested, and are referenced in three module docstrings as the
supported multi-filing entry point. Grepping the repository for real callers:
`as_of()` and `ratios_from_facts()` appear **only in `tests/`**.
`scripts/evaluate_financial_health.py` calls `ratios_for_filing(filing)` — a
*single accession*. Every headline number in M-2 and M-3 is therefore
measured on one filing's own 2–4 comparative periods.

`docs/financial_health.md` §9 already lists this as deferred, with the reason
"revisit once a multi-filing-per-company corpus exists." **That corpus already
exists in `data/raw/`.** The cached `companyfacts` payloads contain every
accession the filer ever tagged; no new download is required.

**Measurement.** I ran the existing engines, unmodified, two ways for each of
the 12 golden companies: (a) the single golden accession, exactly as
`evaluate_financial_health.py` does; (b) every 10-K filed on or before the same
`filed` date and present in the cache, merged through `CompanyFinancials.as_of(cutoff)`.
Offline, from cache only. Arm (a) reproduced M-2's `0.6054` calculated rate
and M-3's `40.4%` / 37-signal figures **exactly**, which validates the method.

| | Single filing (today) | Multi-filing (`as_of`) |
|---|---|---|
| Filings resolved | 12 | **157** (zero exceptions) |
| Fiscal periods | 3–4 per company | 9–20 per company |
| Ratio slots calculated | 362 / 598 — **60.5%** | 1,953 / 2,405 — **81.2%** |
| Conclusive trend direction | 63 / 156 — **40.4%** | 139 / 156 — **89.1%** |
| `INSUFFICIENT_DATA` dimensions | **21 / 60** | **0 / 60** |
| Signals fired | 37 | 140 |
| Restatements surfaced | 0 (corpus can't show any) | **453** |

Every filing's liquidity dimension being `INSUFFICIENT_DATA` — documented in
the roadmap as "expected" and verified by hand — is **not** a property of SEC
data. It is an artifact of feeding the engine one accession. With the project's
own multi-filing code it disappears entirely.

Two honest caveats, both of which are *work*, not blockers:

- **The 140 signals are unvalidated.** Phase 7's "no false positive found on
  manual inspection of all 12 reports" was a claim about 37 signals. It does
  not transfer. Re-inspection is required before any number here is published
  as a quality metric.
- **The 453 restatements are unreviewed.** `as_of()` correctly keeps the
  first-filed value (D-008). But nobody has checked whether those 453
  differences are genuine restatements or resolver artifacts — e.g. the same
  concept resolved under a different tag policy in a 2011 filing than in a 2024
  one. For Phase 8 training data this distinction matters directly, because a
  spurious restatement is a spurious feature change.

### F-2 The trend engine has no analysis window, and its direction is an endpoint comparison

**Severity: medium. Becomes acute the moment F-1 is fixed.**

`analyze_financial_health()` takes no window parameter; it analyses whatever
series it is handed. `trend._direction_and_magnitude()` computes
`values[-1] - values[0]` — a pure first-to-last comparison. With 3–4 periods
that is reasonable. With 20 periods it means `MARGIN_COMPRESSION` fires because
2025 margin is below 2006 margin, which is a secular fact about the business,
not a credit-monitoring signal.

**Measurement** (same multi-filing input, truncated to the last *N* periods):

| Window | Conclusive direction | Signals fired |
|---|---|---|
| Last 3 | 141 / 156 (90.4%) | 81 |
| Last 5 | 143 / 156 (91.7%) | **153** |
| Last 8 | 143 / 156 (91.7%) | 116 |
| Unbounded | 139 / 156 (89.1%) | 140 |

Coverage is robust across windows (89–92%) — which strengthens F-1
independently of this choice. **Signal count is not, and is not even
monotonic**, because an endpoint comparison can flip direction outright when
one earlier period enters the window. An engine whose primary output depends
this strongly on an unspecified parameter has a specification gap.

Two coupled consequences:

- A `window` (or `since`) argument on `analyze_financial_health` is a
  prerequisite for F-1, not a follow-up. `docs/scope.md` §2 already implies the
  floor (≥3 consecutive years); the ceiling is undeclared.
- The §9 deferral of a slope-fit trend method was justified by "typically 2–4
  usable periods per filing." At 9–20 periods that rationale inverts. This does
  **not** mean adopting `scipy`/`statsmodels` — a least-squares slope over ≤10
  points is a handful of lines and `statistics.linear_regression` is in the
  3.12 standard library. Reopen the decision; do not add a dependency for it.

### F-3 No continuous integration

324 tests, `mypy --strict`, `ruff`, and 97% coverage — all run by hand. For a
project whose defining discipline is measured claims, the absence of a CI
workflow is the largest gap between its standards and its automation. A
~30-line GitHub Actions job running `uv sync --extra dev --extra pdf` then
pytest/ruff/mypy costs nothing and protects everything. The golden-corpus
evaluations cannot run in CI (`data/` is gitignored and 700 MB) and should not
try to.

### F-4 Dependency hygiene

- **`numpy`** is declared in `[project.dependencies]` and imported by **no file
  in the repository**. It arrives transitively via `pandas` regardless.
  Remove the direct declaration.
- **`pandas`** is a *core* dependency but is imported only by `scripts/`.
  It belongs in an `eval` extra. This changes the install contract, so it is a
  recommendation rather than something this audit performed.
- `pdfplumber` + `pymupdf` look like duplication but are not: D-015 chose
  pdfplumber for extraction and keeps pymupdf solely to *render* the golden-set
  PDFs. Documented and correct. **No action.**
- `truststore`, `pydantic`, `pydantic-settings`, `requests`, `lxml` — all
  justified, all current, all permissively licensed. **No action.**

### F-5 README was three phases stale — fixed

The README claimed "Phase 4 of 20 — Document extraction (complete)" while the
roadmap recorded Phase 7 complete; the docs table omitted
`canonical_schema.md`, `ratios.md` and `financial_health.md`, and duplicated
the data-dictionary row. **Corrected in this audit** — the only code/docs
change made. Tests, lint and types re-verified green afterwards.

### F-6 Phase 8 will not scale on `companyfacts`

`data/raw/companyfacts` is **491 MB for 309 CIKs** ≈ 1.6 MB per filer. D-013's
negative-class universe is ~7,973 companies: roughly **13 GB** and 8,000
throttled requests, to extract perhaps a few hundred KB of annual facts per
filer. That is the wrong tool for a bulk training-set build (it remains exactly
the right tool for monitoring a watchlist of tens of companies).

SEC publishes **[Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets)**:
quarterly ZIPs covering 2009 Q1 – 2026 Q2, ≤122 MB each, containing `sub.txt`
(one row per submission, with CIK, form, period, filed date, SIC),
`num.txt` (every numeric fact as filed, with a `segments` field added in the
December 2024 reprocessing), `tag.txt` and `pre.txt` (statement placement —
information `companyfacts` does not expose at all). US government work; no
licence restriction; no API key; no rate limit.

This is a **clear reuse opportunity** and the only "borrow" recommendation in
this audit with material size. The critical constraint: it must enter behind
`financials/xbrl.py`'s existing `XbrlFact` interface — a `facts_from_fsds()`
alongside `facts_for_accession()` — so `resolver.py`, `concept_map.py` and
everything downstream are untouched and the canonical model remains the
architecture. Validate it by reproducing QM-01 on the same 12 filings from FSDS
input before using it for anything.

---

## 4. Phase-by-phase audit

### Phase 1 — Product definition
**Implemented:** PRD, scope, workflow, assumptions, risks, data feasibility,
23-entry decision log. **Strengths:** the human-in-the-loop boundary is
enforced structurally, not just documented (D-003, no composite score in D-022,
D-010's refusal of "probability of default"). Decisions carry alternatives,
evidence and consequences. **Weakness:** none material. **Open source:** none
applicable. **Action: KEEP.** Migration: n/a. Regression risk: n/a.

### Phase 2 — Environment
**Implemented:** `uv` + hatchling, Python 3.12 pinned, pydantic-settings config,
JSON/text logging, ruff (E/F/I/UP/B/SIM/C4), `mypy --strict`, pytest+coverage,
phase-scoped optional dependency groups. **Strengths:** strict mypy passing
across 35 files with almost no `ignore` is rare and valuable; the optional-extras
layout keeps each phase's install honest. **Weaknesses:** no CI (F-3); `numpy`
unused and `pandas` mis-scoped (F-4). **Open source:** structlog/loguru would
*replace* 64 working lines — not worth a dependency. **Action: IMPROVE** (add
CI, drop `numpy`). Migration: small. Regression risk: low.

### Phase 3 — Data acquisition
**Implemented:** `sec_edgar.py` + `scripts/phase3_data_audit.py`; BRD×SEC
linkage run at full scale (992/992 cases), 178 usable positive events, ~7,973
candidate negatives, licences verified against primary sources.
**Strengths:** the decision gate (D-011→D-013) was resolved against live data,
and the 299–426 estimate was corrected down to 178 rather than quietly reused —
exactly the discipline this project claims. Submission-overflow pagination is
handled, which most SEC wrappers get wrong. **Weaknesses:** the negative-class
sample and the SIC exclusions are still unbuilt (known, D-013); F-6 sizing.
**Open source:** `edgartools` (MIT, 2.7k★, active, 27 open issues) is credible
but would replace 174 working lines with a large dependency that does not
document as-filed/point-in-time semantics — the one property D-008 makes
non-negotiable. **Action: KEEP the client; BORROW FSDS for bulk (F-6).**
Migration: medium, additive. Regression risk: low if adapter-bounded.

### Phase 4 — Document extraction
**Implemented:** `DocumentExtractor` protocol, HTML extractor over `lxml` with
colspan/rowspan grid expansion and char-offset provenance, PDF extractor over
`pdfplumber` with bbox and page provenance, item-section detection, upload
validation, `pymupdf.Story` renderer for golden-set PDFs.
**Strengths:** R-19 was closed by *measurement* (179/179 tie, 2.4× speed), not
preference — and the measurement chose the right metric (reference-value recall,
not table count, which differed 2.7× while recovering identical values). The
`page.flush_cache()` fix for pdfplumber's unbounded page cache is the kind of
detail that only comes from running the thing at scale.
**Weaknesses:** borderless tables remain unsolved for real uploads (documented,
R-09/R-19); OCR absent (correctly out of scope). **Technical debt:** the
counting artefact where rendered PDFs report more "tables" than HTML is
documented rather than fixed — acceptable.
**Open source:** Camelot / Docling / table-transformer / Tesseract were
considered. D-015's own finding rules them out for now: *"Neither library is the
bottleneck; isolation is"* — 95% recall on isolated statements vs 42% on
whole-filing fallback. Swapping the parser addresses the wrong variable.
**Action: KEEP. DEFER OCR and layout models** until a real scanned-upload
requirement exists. Migration: n/a. Regression risk: n/a.

### Phase 5 — Canonicalization
**Implemented:** 26 concepts, three tag-resolution policies (`ALTERNATES` /
`PREFERRED_SCOPE` / `COMPONENTS`), explicit derivation rules run to a fixpoint,
annual-period and USD filtering, equity split by scope, non-circular validation,
one-directional HTML corroboration.
**Strengths:** this is the strongest work in the repository. D-018's audit is a
model of the genre: it found that the *original* design's central assumption was
false, quantified the damage (32 values wrongly discarded; Apple's short-term
debt understated by 7,979M; Tesla's liabilities overstated by 728M), and fixed
it with three declarative policies rather than resolver special-cases. Accuracy
87.0% → 97.2%, `CONFLICTING` 50 → 3, `total_debt` completeness 25% → 86%. The
refusal to score a validation check whose result is guaranteed by how its input
was derived — reporting 12 honest passes instead of 19 circular ones — is
exactly right and rarer than it should be.
**Weaknesses:** `short_term_debt`/`long_term_debt` remain the weakest concepts
(~32% completeness), documented and sized against the corpus rather than hidden.
`validation.py` runs per filing only; there is no cross-filing consistency check
(relevant once F-1 lands). **Open source:** none. Arelle solves a problem this
project does not have; `edgartools`' standardization would substitute an opaque
mapping for 26 reviewable, individually-justified policies — a direct downgrade
in explainability, which is a product requirement here, not a nicety.
**Action: KEEP. IMPROVE** validation to span `CompanyFinancials`. Migration:
small. Regression risk: low.

### Phase 6 — Ratio engine
**Implemented:** 13 ratios across 5 categories, `FactGetter` protocol, four-state
status model, structured `RatioWarning` codes, machine-readable
`missing_concepts`/`conflicting_concepts`, `calculation_method`. 100% line
coverage on `ratios/`.
**Strengths:** the Phase 5/6 boundary is the cleanest seam in the codebase —
structural typing on `.get`/`.period_labels` rather than importing
`CanonicalFilingFacts`. D-021's move from string warnings to coded warnings was
made *before* Phase 7 could depend on the string form; that is good timing
judgement, and Phase 7 duly branches on `WarningCode.NEGATIVE_EQUITY` rather
than substring-matching prose. D-019 resisted the brief's own six-state
suggestion and justified four. D-021 also *investigated and rejected*
generalizing the near-zero-denominator warning, having checked all 362
`CALCULATED` results and found no case needing it — rejecting a plausible
feature on evidence is harder than adding it.
**Weaknesses:** ending-balance ROA/ROE is a stated simplification (D-020), not a
defect. Comparative-year coverage (48.2%) was attributed to Phase 5 tag
completeness; **F-1 shows the larger share is actually the single-accession
harness.**
**Open source:** FinanceToolkit (MIT, v2.2.0, Aug 2026, 180+ ratios) is the
serious candidate and fails on fit: it is built around **FinancialModelingPrep**
with an API key, falling back to Yahoo Finance. Adopting it would replace SEC
as-filed facts with a third-party vendor's normalised figures — destroying
provenance, point-in-time correctness (D-008) and the entire warning/confidence
chain, in exchange for ratios this project computes in ~600 fully-covered lines.
OpenBB is a data platform, not a ratio library. **Action: KEEP — replacement
would be a strict downgrade.** Migration: n/a. Regression risk: n/a.

### Phase 7 — Financial health
**Implemented:** per-ratio `RatioTrend` (direction, economic direction,
persistence, median baseline, robust-MAD unusual-movement flag, gap and
data-quality handling), 5 dimensions with a `MIXED` state, 9 signal codes,
change summary, all thresholds gathered and individually justified in
`thresholds.py`. 100% coverage on `health/`.
**Strengths:** the design decisions are consistently the disciplined ones — no
composite score, no severity labels, `MIXED` never netted to a direction,
`NOT_MEANINGFUL` for negative-equity windows across the *whole* window rather
than the flagged period, and a 3-of-5 majority for cross-dimension breadth
because leverage and coverage share inputs. `direction.py` keeping
`RATIO_DIRECTIONS` out of `ratios/registry.py` — Phase 6 states what a ratio
equals, never whether that is good — is a genuinely sharp boundary. Finding and
fixing the D-023 ordering bug *before* building on it, by checking real
`period_labels` order instead of trusting the recap, is the process working.
**Weaknesses:** F-2 (no window; endpoint-comparison direction). The engine also
inherits F-1's input starvation — its own M-3 is measuring the harness more
than the engine.
**Technical debt:** the §9 slope-fit deferral rests on a period-count premise
that F-1 invalidates.
**Open source:** `scipy`/`statsmodels` for trend fitting — **not justified**;
`statistics.median` and `statistics.linear_regression` are stdlib and the
robust-MAD z-score is 6 lines. Adding scipy to compute a slope over ≤10 points
is dependency growth for nothing.
**Action: KEEP the design; IMPROVE with a window parameter and re-validated
signals.** Migration: small. Regression risk: **medium** — signal counts move
substantially, so the false-positive review must be redone, not assumed.

---

## 5. Open-source / official tool opportunities

### Strong candidate
- **SEC Financial Statement Data Sets** (official, public domain) for Phase 8's
  bulk training-set build. Eliminates ~13 GB and ~8,000 throttled requests, adds
  `pre.txt` statement placement that `companyfacts` cannot provide. Must enter
  behind the existing `XbrlFact` interface. See F-6.
- **GitHub Actions** for CI. Not a library; the largest process gap. See F-3.

### Possible candidate
- **`statistics.linear_regression`** (stdlib, already available) if F-2's
  reopened slope-fit decision goes that way. Zero new dependency.
- **Arelle** (Apache-2.0) — *only* if a future phase needs dimensional facts,
  `decimals` precision, or XBRL from an uploaded filing with no `companyfacts`
  entry. Heavy; no current requirement.
- **`edgartools`** (MIT, 2.7k★, active) — credible and well-maintained, but it
  would replace 174 working lines and does not document the as-filed /
  point-in-time semantics D-008 requires. Revisit only if EDGAR full-text
  search or many new form types are needed (plausible around Phase 10/16).

### Not worth replacing
- The ratio engine (FinanceToolkit requires a commercial API key; no provenance).
- The health/trend engine (no equivalent exists that preserves these semantics).
- The canonical schema, concept map and resolver (this is the product).
- `sec_edgar.py`, `logging_config.py`, the file cache, `upload.py` — each is
  tens of lines doing exactly one thing, fully covered.
- PDF/table libraries — D-015 measured a tie; the bottleneck is isolation.

### Future candidate
- **Phase 8/9:** `scikit-learn` (logistic-regression baseline — matches D-004
  and the transparency requirement) and `shap`, both already declared under the
  `ml` extra. Correct choices; no change needed. Do **not** add XGBoost/LightGBM
  for a 178-event dataset — a gradient-boosted model on that sample size buys
  variance, not accuracy, and costs the interpretability D-010 depends on.
- **MLflow: defer.** For a single-analyst MVP with one baseline model, a
  versioned artefact plus the existing evaluation scripts is sufficient. Revisit
  at Phase 17.
- **Phase 10 NLP:** the roadmap's "rules/classical methods first" is right.
  `scikit-learn` + `spaCy` before any transformer. **No vector database** —
  Phase 12 is one grounded call over one filing's own sections, which is a
  lookup, not a retrieval problem.
- **Phase 13/15:** `SQLAlchemy` (declared) or plain `sqlite3`. Given D-012's
  "plain Python functions, not a network API," `sqlite3` with hand-written SQL
  may be the lighter honest answer for an append-only schema.
- **Phase 14:** `streamlit` (declared, D-012). Revisit at Phase 14 as planned.
- **FastAPI: not needed** unless D-012 is superseded.
- **`polars` over `pandas`: no.** Nothing here is large enough to notice.

---

## 6. Recommended target architecture

Unchanged in shape from what exists — the additions are marked:

```text
   ┌──────────────────────────────┬────────────────────────────┐
   │  SEC companyfacts API        │  SEC Financial Statement   │   ★ NEW, Phase 8
   │  (watchlist monitoring)      │  Data Sets (bulk training) │
   └──────────────┬───────────────┴──────────────┬─────────────┘
                  │                              │
                  ▼                              ▼
        financials/xbrl.py  ◄── one interface: XbrlFact ──►  ★ facts_from_fsds()
                  │
                  ▼
        concept_map · resolver · periods · validation        ← UNCHANGED
                  │
                  ▼
        CanonicalFilingFacts ──┐
                               ├─► CompanyFinancials.as_of(cutoff)   ★ WIRED UP
        10-K HTML ─► extraction┘         (point-in-time, D-008)
             │                           │
             └─► reconciliation          ▼
                 (corroborate only)   ratios/  (FactGetter)
                                         │
                                         ▼
                                   health/  + window param   ★ F-2
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              Phase 8 ML           Phase 10 NLP        Phase 12 synthesis
              (sklearn, shap)      (rules first)       (grounded, cited)
                    └────────────────────┼────────────────────┘
                                         ▼
                                   Human analyst
```

The one architectural rule to hold: **external tooling enters at
`financials/xbrl.py` or `extraction/`, never below `financials/models.py`.**
The canonical model is the product's spine; an upstream parser must always be
replaceable without touching it. The codebase already honours this — the
recommendation is to keep honouring it when FSDS arrives.

---

## 7. Recommended migration sequence

### SAFE NOW

> **Status, 2026-09-18.** M-1, M-3 and M-4 are complete (delivered
> during Phase 8). M-2 and M-5 remain open. Outcomes are recorded inline
> below rather than in a separate changelog, so the plan and what came of
> it stay in one place.
>
> **Reviewed again 2026-09-19 (Phase 19). M-2 is closed — not done, but
> dissolved**, because its premise stopped being true. See its entry below.
> **M-5 remains open** and is now the oldest unactioned recommendation in the
> project.

**M-1 · CI workflow** (F-3) — ✅ **done.** `.github/workflows/checks.yml`:
`uv sync --extra dev --extra pdf --extra ml`, then pytest / ruff check /
ruff format --check / mypy. No corpus.

**M-2 · Drop `numpy` from `[project.dependencies]`** (F-4) — ⏸ **not done,
and now partly superseded.** `numpy` is still declared and still imported
nowhere directly, but Phase 8 made it a genuine transitive requirement of the
`ml` extra (scikit-learn), so removing the direct declaration is now cosmetic
rather than a real dependency reduction. `pandas` remains core while used only
by `scripts/`. ~~Both remain open, both are hygiene.~~

> **Closed 2026-09-19 (Phase 19) — the recommendation is void, because its
> premise is no longer true.** Re-deriving the imports for
> [architecture.md](architecture.md) found that **both libraries are now
> imported directly by the library itself**, not only by `scripts/`:
>
> | Library | Direct imports in `src/credit_risk_copilot/` | Arrived in |
> |---|---|---|
> | `numpy` | `explain/adapters.py`, `explain/local.py`, `modeling/metrics.py`, `modeling/model.py` | Phases 8–9 |
> | `pandas` | `workspace/build.py` | Phase 14 |
>
> So each is a correctly declared core dependency and **dropping either would
> now break the package.** Acting on this recommendation at any point after
> Phase 9 would have been a regression. Recorded rather than deleted, because
> a dependency-hygiene note that goes stale while sitting in a table is worth
> knowing about: the finding was accurate when written and wrong within two
> phases.

**M-3 · Add an analysis window to `analyze_financial_health`** (F-2) — ✅
**done** ([D-024](decision_log.md), `tests/test_health_window.py`).
`analysis_window: int | None = DEFAULT_ANALYSIS_WINDOW`, applied over the union
of periods across ratios and counting period *labels* so a gap stays a gap;
`FinancialHealthReport.analysis_window` records it.
`evaluate_financial_health.py` passes it explicitly, and M-3's summary now
carries `analysis_window` and `input_path` so a published figure states the
span it was taken over.

**One deliberate deviation from the plan above.** The default is **5 periods**,
not "all supplied periods". Defaulting to the old behaviour looked
conservative but would have been the wrong default: the audit's own evidence
(§F-2) is that unbounded is incorrect once real history is supplied, and a
default that is wrong in the new normal case is a trap for the next consumer.
It is a no-op in practice — no pre-Phase-8 caller supplies more than four
periods, all 324 prior tests passed unmodified, and re-running M-3 returns
40.38% and 37 signals unchanged.

**M-4 · Wire the multi-filing path into a real evaluation** (F-1) — ✅
**done, with all three validation conditions met.**

Delivered as `scripts/evaluate_multi_filing.py` (M-4) plus
`scripts/validate_multi_filing.py`. One change to `src/` beyond the plan's
"purely additive": `financials/history.py`, because assembling a company's
resolved history with per-filing skip diagnostics is reusable pipeline code,
not script code — Phase 8's dataset builder depends on it too. Both
measurements are published side by side in
[financial_health.md §7a](financial_health.md) and
[ratios.md §6](ratios.md); the single-filing figures are annotated, not
overwritten.

Headline: ratio coverage 60.5% → **81.2%**, conclusive trends 40.4% →
**91.7%**, `INSUFFICIENT_DATA` dimensions 21 → **0**. The single-filing column
reproduces M-2 and M-3 exactly, which is what validates the harness.

The three conditions:

1. **False-positive re-inspection — done, and it found something.** All 153
   signals dumped with series, magnitude, persistence and evidence; all 56
   healthy-cohort signals read individually. Most are true positives, and the
   path *corrects a false negative*: Pfizer goes from 0 signals to 10 real
   ones (net margin 27.0% → 3.6%, interest coverage 19.8× → 1.5×). **3 of 90
   trend-based signals are endpoint artefacts**, all healthy-cohort, all
   clearing the 5% floor only because the window's first period was its peak —
   Walmart's `MARGIN_COMPRESSION` has a *positive* least-squares slope. 0 of
   97 distressed-cohort signals are affected. This is the residual of F-2 that
   the window bounds but does not remove, and it is now the evidence for
   reopening the slope-fit deferral.
2. **Restatement triage — done.** All 453 classified by cause from
   canonical-fact provenance (270 genuine same-tag, 110 immaterial, 52
   amendments, 21 tag changes, 0 origin changes), then a stratified sample of
   32 re-derived straight from the raw `companyfacts` JSON: **32/32
   confirmed**. Building that verifier exposed a bug in the verifier itself —
   it looked up the *original* tag under the restated accession, which for a
   `tag_change` is absent by definition, and scored 7 of 8 as failures. Fixed;
   the classifier was right all along. Exactly one of the 453 is not a
   restatement at all: Tesla's FY2016 `DebtCurrent`, a 1000× filer scale error.
3. **Pre-phase-in degradation — done and benign.** Mean ratio coverage by
   filing vintage: 21% (2009), 51% (2010), 72% (2011), 90% (2013), 96-97%
   (2017+). Thin old periods produce `MISSING_INPUT` → `INSUFFICIENT_DATA` →
   no signal. No endpoint artefact and no distressed-cohort signal involves a
   pre-2013 period. Thinness lowers coverage; it does not manufacture trends.

**M-5 · Extend validation across filings** (Phase 5 weakness) — ⏸ **not done.**
Cross-filing consistency checks inside `validation.py`. Partly anticipated by
M-4's restatement classifier, which surfaces and categorises the disagreements;
what remains is turning that into `ValidationResult`s on `CompanyFinancials`
rather than a script's CSV. Additive. **Risk: low.**

### WAIT

**W-1 · SEC Financial Statement Data Sets adapter** (F-6). Do this *inside*
Phase 8, when the negative-class build actually needs it — not before. Sequence:
`facts_from_fsds()` behind `XbrlFact` → reproduce QM-01 on the same 12 filings
from FSDS input → compare fact-for-fact against `companyfacts` → only then use
it for the bulk build. `companyfacts` stays the monitoring path. **Never** let
FSDS's schema reach `resolver.py`.

**W-2 · Reopen the slope-fit trend decision** — after M-4 shows the real period
distribution. Stdlib only.

**W-3 · `edgartools`** — only if full-text search or many new form types are
needed (Phase 10/16).

**W-4 · Arelle, OCR, table-layout models, MLflow, vector DB, FastAPI** — no
current requirement. Do not pre-build.

---

## 8. Final decision matrix

| Area | Current state | Recommendation | Why | Urgency | Risk |
|---|---|---|---|---|---|
| SEC ingestion | 174-LOC cached, throttled client | **KEEP** | Correct, covered, handles overflow pagination; wrappers add weight not capability | — | LOW |
| Bulk data for ML | `companyfacts` per CIK (~1.6 MB each) | **BORROW** (FSDS, behind adapter) | ~13 GB / 8,000 requests otherwise; FSDS adds `pre.txt` | Phase 8 | MED |
| XBRL parsing | Delegated to SEC `companyfacts` | **KEEP** | Already the strongest form of reuse | — | LOW |
| PDF extraction | pdfplumber adapter | **KEEP** | D-015 measured a tie; bottleneck is isolation | — | LOW |
| HTML extraction | lxml adapter + grid expansion | **KEEP** | 85.1% recall, 100% on modern filings | — | LOW |
| OCR / layout models | Absent, reported as error | **DEFER** | No scanned corpus; SEC publishes none | — | LOW |
| Canonicalization | 26 concepts, 3 tag policies, fixpoint derivation | **KEEP** | Core IP; QM-01 97.2%; alternatives lose provenance | — | LOW |
| Validation | Per-filing checks, non-circular | **IMPROVE** | Extend across `CompanyFinancials` | LATER | LOW |
| **Multi-filing / point-in-time** | **Built, tested, never run on real data** | **WIRE UP** | 60.5%→81.2% ratio coverage; 40.4%→89.1% trends; 21→0 insufficient dimensions | **NOW** | **MED** |
| Ratios | 13 definitions, 4 states, coded warnings | **KEEP** | FinanceToolkit needs a commercial API key and drops provenance | — | LOW |
| **Financial health** | No analysis window; endpoint-comparison direction | **IMPROVE** | Signals swing 81→153 across windows | **NOW** | **MED** |
| Health signals / dimensions | 9 codes, 5 dimensions, no score | **KEEP** | Core IP; no equivalent preserves these semantics | — | LOW |
| Config / logging / caching | pydantic-settings, 64-LOC logger, file cache | **KEEP** | Small, covered; structlog/loguru would replace working code | — | LOW |
| Testing | 324 tests, 97%, strict mypy, clean ruff | **KEEP** | Excellent | — | LOW |
| **CI** | **None** | **ADD** | Everything is verified by hand | **NOW** | LOW |
| Dependencies | `numpy` unused; `pandas` mis-scoped | **IMPROVE** | Hygiene | NOW | LOW |
| Phase 8 ML stack | sklearn + shap declared | **KEEP** | Right for 178 events; no boosted trees | Phase 8 | LOW |
| Persistence / UI | SQLAlchemy / Streamlit declared, unused | **DEFER** | Decide at Phases 13–15 with real requirements | LATER | LOW |

---

## 9. Conclusions

### What we should keep
The canonical schema, concept map, resolver, derivation rules and provenance
model; the ratio catalog and its status/warning model; the health engine's
design decisions (no composite score, no severity, `MIXED`, `NOT_MEANINGFUL`,
3-of-5 breadth); the SEC client; both extractors and their adapter protocol;
the config/logging/caching layer; the testing discipline. None of these should
be rewritten, and none should be replaced by a dependency.

### What we should change
Wire up the multi-filing point-in-time path (M-4) and give the health engine an
explicit analysis window first (M-3). Add CI (M-1). Drop `numpy`, re-scope
`pandas` (M-2). Extend validation across filings (M-5). That is the complete
list.

### What we should borrow
SEC's Financial Statement Data Sets, inside Phase 8, behind the existing
`XbrlFact` interface. GitHub Actions. `statistics.linear_regression` if W-2
goes that way. Nothing else.

### What we should defer
Arelle, `edgartools`, OCR, table-layout models, FinanceToolkit/OpenBB, MLflow,
vector databases, FastAPI, `polars`, XGBoost/LightGBM. Each is a real tool; none
solves a problem this project currently has.

### Phase 8 readiness

**Proceed to Phase 8 — after M-3 and M-4, which are prerequisites, not
polish.**

The reason is not code quality; Phases 1–7 are in better shape than most
projects are at Phase 15. The reason is that Phase 8 needs something the
repository has never produced: **point-in-time feature rows for a company-year,
assembled across multiple filings.** Today, every measurement in the project is
single-accession. Building an ML training set on that basis would inherit a
60.5% feature-completeness ceiling and a 40.4% trend-conclusiveness ceiling that
are artifacts of the evaluation harness rather than of the data — and would bake
those artifacts into the model's features before anyone noticed.

The fix is not a library and not a redesign. It is running code the project
already wrote and has already tested. Prerequisites, in order:

1. **M-3** — analysis window on `analyze_financial_health` (default-preserving).
2. **M-4** — real multi-filing evaluation, with the three validation steps:
   re-inspect signals for false positives, triage the 453 restatements, confirm
   pre-2011 filings degrade gracefully.
3. **M-1** — CI, before the codebase grows a scikit-learn pipeline.
4. **Confirm the negative-class strategy against F-6's sizing** before
   downloading anything at scale.

With those done, Phase 8 starts on a feature layer whose coverage is measured at
~81% rather than ~61%, with the point-in-time rule actually exercised rather
than only unit-tested — which is precisely what D-008 exists to guarantee and
what an out-of-time evaluation will live or die on.
