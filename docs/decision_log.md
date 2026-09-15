# Decision Log — AI Credit Risk Monitor Copilot

Lightweight architecture decision records. Each entry states the context, the
decision, alternatives considered and consequences. Decisions are never deleted;
a reversed decision gets a new entry that supersedes the old one.

**Status:** Proposed · Accepted · Superseded (by D-xxx) · Rejected

| ID | Title | Status | Date |
|---|---|---|---|
| [D-001](#d-001-product-framing-monitoring-copilot) | Product framing: monitoring copilot | Accepted | 2026-09-13 |
| [D-002](#d-002-initial-universe-us-sec-registrants) | Initial universe: US SEC registrants | Accepted | 2026-09-13 |
| [D-003](#d-003-analyst-owns-every-final-judgement) | Analyst owns every final judgement | Accepted | 2026-09-13 |
| [D-004](#d-004-ml-model-uses-financial-features-only) | ML model uses financial features only | Accepted | 2026-09-13 |
| [D-005](#d-005-xbrl-as-source-of-record-pdf-extraction-evaluated-against-it) | XBRL as source of record; PDF extraction evaluated against it | Accepted | 2026-09-13 |
| [D-006](#d-006-exclude-financial-sector-companies-from-mvp) | Exclude financial-sector companies from MVP | Accepted | 2026-09-13 |
| [D-007](#d-007-annual-periods-before-quarterly) | Annual periods before quarterly | Accepted | 2026-09-13 |
| [D-008](#d-008-point-in-time-as-filed-data-rule) | Point-in-time (as-filed) data rule | Accepted | 2026-09-13 |
| [D-009](#d-009-roadmap-amendments) | Roadmap amendments | Accepted | 2026-09-13 |
| [D-010](#d-010-ml-output-is-not-called-a-probability-of-default) | ML output is not called a "probability of default" | Accepted | 2026-09-13 |
| [D-011](#d-011-training-data-chosen-through-a-phase-3-decision-gate) | Training data chosen through a Phase 3 decision gate | Accepted | 2026-09-13 |
| [D-012](#d-012-initial-ui-framework-streamlit) | Initial UI framework: Streamlit | Accepted | 2026-09-14 |
| [D-013](#d-013-training-data-candidate-b-self-built-sec--brd-as-primary) | Training data: Candidate B (self-built SEC + BRD) as primary | Accepted | 2026-09-14 |
| [D-014](#d-014-html-is-the-primary-document-path-golden-set-pdfs-are-generated) | HTML is the primary document path; golden-set PDFs are generated | Accepted | 2026-09-15 |
| [D-015](#d-015-pdf-library-pdfplumber-for-text-and-tables) | PDF library: pdfplumber for text and tables | Accepted | 2026-09-15 |

---

## D-001 Product framing: monitoring copilot
**Status:** Accepted (project owner, 2026-09-13)

**Context.** The original brief describes single-company risk assessment; the project name says *Monitor*. Underwriting (assessing a new credit) and monitoring (re-assessing existing exposures as information arrives) differ in workflow, UI and which signals matter.

**Decision.** Build a **monitoring** product: a watchlist of companies, re-assessed per reporting period, with change-since-last-period as a first-class output.

**Alternatives.** Underwriting-style one-off assessment — simpler, but uses multi-year history less and fits the product name poorly.

**Consequences.** Point-in-time correctness, assessment versioning and change detection become core requirements. The same per-company assessment still serves one-off analysis.

## D-002 Initial universe: US SEC registrants
**Status:** Accepted (project owner, 2026-09-13)

**Context.** Candidate universes: US SEC filers or Indian listed companies.

**Decision.** Start with **US SEC registrants**; keep source-specific logic behind interfaces so other jurisdictions can be added.

**Alternatives.** Indian listed companies — PDF-heavy annual reports, fewer free structured sources and fewer labelled datasets.

**Consequences.** Free structured XBRL data with filing metadata; a US-GAAP-based canonical schema; IFRS/20-F filers out of MVP scope.

## D-003 Analyst owns every final judgement
**Status:** Accepted (from the project brief)

**Decision.** The system produces drafts only. Approve/modify/reject, the credit watch status and any final assessment require an explicit analyst action. AI drafts are immutable.

**Consequences.** Separate data entities for AI assessment and analyst review; tests enforce that no code path sets final status automatically (SC-05, SC-06).

## D-004 ML model uses financial features only
**Status:** Accepted (delegated to engineering judgement by project owner, 2026-09-13)

**Context.** The brief's target architecture diagram routes NLP risk signals into the ML model. A supervised model can only use inputs present in its training data; no available labelled dataset contains NLP signals extracted from the same filings.

**Decision.** The ML credit-risk model uses **financial statement features only**. NLP signals meet the ML output in the combination layer (Phase 11) and synthesis (Phase 12), where agreements and contradictions are made explicit.

**Alternatives.** (a) Build a labelled text+financials training set — large effort, few events. (b) Feed NLP signals at inference without training on them — invalid.

**Consequences.** Simpler, valid model; qualitative evidence remains visible rather than absorbed into an opaque score. A text-aware model remains a possible later extension.

## D-005 XBRL as source of record; PDF extraction evaluated against it
**Status:** Accepted (delegated to engineering judgement by project owner, 2026-09-13)

**Context.** The brief plans PDF extraction → parsing as the route to financial data. For US SEC filers, filings are HTML with machine-readable XBRL financial data; parsing a PDF to recover numbers that already exist in structured form is less reliable. PDF extraction still matters for documents without XBRL (private borrowers, lender presentations, audited statements).

**Decision.** For SEC filers, **XBRL facts are the source of record** for numbers. The PDF extraction pipeline (Phases 4–5) is still built, and its accuracy is **measured against XBRL** on a golden set of filings where both exist. Disagreements between sources are surfaced as validation findings.

**Alternatives.** (a) PDF-only, as in the original plan — weaker accuracy, no ground truth to measure it. (b) XBRL-only — drops document extraction, a real analyst need and a core portfolio component.

**Advantages.** Reliable numbers for the MVP; automatic ground truth for extraction evaluation (QM-01); reconciliation checks as a feature.
**Disadvantages.** Two input paths to maintain; XBRL concept mapping is its own problem (R-11).

## D-006 Exclude financial-sector companies from MVP
**Status:** Accepted (delegated to engineering judgement by project owner, 2026-09-13)

**Decision.** Exclude banks, insurers, broker-dealers, REITs, investment funds and shell companies (by SIC code) in MVP.

**Reason.** Standard corporate ratios (current ratio, debt/equity, interest coverage) are misleading or undefined for these business models, and they need different analysis frameworks.

## D-007 Annual periods before quarterly
**Status:** Accepted (delegated to engineering judgement by project owner, 2026-09-13)

**Decision.** MVP assesses annual (10-K) fiscal years. Quarterly (10-Q) comes later.

**Reason.** 10-Q cash-flow statements are reported year-to-date, and fourth quarters must be derived from annual minus nine-month figures — real complexity that should follow a working annual pipeline. Real monitoring is often quarterly; this is a stated MVP limitation (A-03).

## D-008 Point-in-time (as-filed) data rule
**Status:** Accepted (delegated to engineering judgement by project owner, 2026-09-13)

**Decision.** Any assessment, training example or historical replay "as of" date *T* uses only facts **filed on or before T**, using the values as originally filed for that period unless the analyst explicitly chooses restated values.

**Reason.** Later filings restate and re-present prior-period figures. Using them leaks future information into training and makes historical replays look more prescient than they were (R-03).

**Consequences.** Facts must be stored with filing date and accession number; dedicated tests (SC-07).

## D-009 Roadmap amendments
**Status:** Accepted (delegated by project owner, 2026-09-13) — see [roadmap.md](roadmap.md)

1. Data feasibility desk research added to Phase 1 (done), so the dataset constrains the schema before Phase 5.
2. Evaluation is built **incrementally in each phase**; Phase 17 consolidates rather than starts evaluation.
3. Core domain models (typed schemas with provenance) are introduced with Phase 5, and **SQLite persistence moves to be delivered with Phase 13** (review requires immutable history); Phase 15 becomes schema hardening and history/versioning queries.
4. Synthesis (Phase 12) must cite evidence IDs, validated by code (SC-04).

## D-010 ML output is not called a "probability of default"
**Status:** Accepted (delegated to engineering judgement by project owner, 2026-09-13)

**Decision.** Present the ML output as an *estimated likelihood of the modelled event (e.g. bankruptcy filing) within the modelled horizon, for companies resembling the training population*, with its applicability warnings. Avoid "PD" and avoid unqualified labels like "74% risk".

**Reason.** Public labels are bankruptcy filings, not defaults; the training base rate differs from any real portfolio (A-14); "PD" has a specific regulatory meaning.

## D-011 Training data chosen through a Phase 3 decision gate
**Status:** Accepted (delegated by project owner, 2026-09-13) — details in [data_feasibility.md §5](data_feasibility.md)

**Decision.** Do not select the training dataset on unverified details. Phase 3 begins with licence checks, a feasibility spike on a self-built SEC + bankruptcy-records dataset, and an inspection of the public US bankruptcy dataset, followed by a recorded decision.

## D-012 Initial UI framework: Streamlit
**Status:** Accepted (project owner, 2026-09-14) — open question Q4 in [product_requirements.md](product_requirements.md), initial choice due Phase 2, final choice due Phase 14.

**Context.** The MVP needs one analyst-facing surface: a watchlist and a per-company view built around approve/modify/reject review (Phases 13-14), reading a small amount of server-side state (drafts, reviews, filings). Non-goals rule out production infrastructure — no microservices, no multi-tenant SaaS ([scope.md §5](scope.md)). Two realistic options: (a) Streamlit, a single Python process rendering the UI; (b) a small API (FastAPI) plus a separate web frontend (React or similar).

**Decision.** Start with **Streamlit** for Phases 2-14. It renders tables, forms and simple charts directly from the pandas/pydantic objects the rest of the pipeline already produces, needs no separate frontend build or API contract to maintain, and matches the single-analyst, non-real-time MVP scope. `pyproject.toml` declares it under the `ui` optional dependency group.

**Alternatives.**
- **API + web frontend (FastAPI + React).** More control over interaction design and a clearer seam for a future multi-user product, but doubles the surfaces to build and test for no MVP requirement it unlocks.
- **Dash / Panel.** Similar trade-offs to Streamlit; Streamlit chosen for ecosystem maturity and the team's familiarity.

**Consequences.** Review actions (approve/modify/reject) are implemented as Streamlit forms/session state rather than API endpoints, so Phase 13's persistence layer should expose plain Python functions, not a network API, to avoid building a client only Streamlit will call. If Phase 14 needs richer interaction (e.g. concurrent multi-analyst editing) than Streamlit supports well, this decision is revisited then with real UI requirements in hand rather than guessed now — the log entry gets a superseding decision, not a silent change.

## D-013 Training data: Candidate B (self-built SEC + BRD) as primary
**Status:** Accepted (project owner, 2026-09-14) — resolves the [D-011](#d-011-training-data-chosen-through-a-phase-3-decision-gate) gate; full evidence in [data_feasibility.md §6](data_feasibility.md).

**Context.** D-011 set a Phase 3 gate before choosing between Candidate A (an anonymised, off-the-shelf US bankruptcy dataset) and Candidate B (a self-built dataset joining SEC XBRL financials to the Florida-UCLA-LoPucki Bankruptcy Research Database, BRD, by CIK), with a documented decision rule: use B as primary if it yields on the order of 100+ linkable bankruptcy events with usable history, otherwise fall back to A.

**What the gate found (2026-09-14, against live sources, not desk research):**
- **Licences clear on both.** The BRD User's Manual licenses the Cases table "for both commercial and academic use," with an attribution requirement and no redistribution ban found. Candidate A's source repo is CC-BY-4.0 (its Kaggle mirror's own metadata claims CC0 instead; treated as CC-BY-4.0, the more conservative reading).
- **Candidate B clears the event-count bar — at full scale, not just a spot-check.** Of 1,218 BRD cases, 992 carry a CIK. Running the linkage audit against SEC's `companyfacts` API for all 992 (`scripts/phase3_data_audit.py`, results in [data_dictionary.md §5](data_dictionary.md)) found **178 cases with ≥2 pre-bankruptcy annual XBRL periods** — above the "100+" heuristic, but well below the initial rough estimate of 299–426 "linkable" cases (that estimate only checked for a CIK + a plausible year, not real usable history; 144 cases turned out to have no XBRL data at all, mostly clustered in the 2008–2011 phase-in years). Per-fact `accn`/`form`/`fy`/`fp`/`filed` metadata (needed for the point-in-time rule, [D-008](decision_log.md)) is confirmed present. A rough negative-class universe (SEC filers with a ticker, minus any ever in BRD) is ~7,973 companies, unfiltered by SIC/history requirements.
- **Candidate A's licence and structure are now confirmed**, not merely believed: CC-BY-4.0, 78,682 firm-years (5,220 `failed`, ≈6.6%), features X1–X13 identified (X14–X18 still unconfirmed), industry via `Division`/`MajorGroup`.

**Decision.** **Candidate B (self-built SEC XBRL + BRD) is the primary training dataset.** Candidate A is kept as an external comparison/benchmark only — never as production training data, per the same reasoning as Candidate C (Polish UCI) in [data_feasibility.md §3.4](data_feasibility.md).

**Consequences.**
- Phase 3 now has committed engineering work, some already done: the CIK-linked entity audit ran at full scale (992/992 cases) and is cached under `data/raw/` for reuse in Phase 5's ingestion — this is real data-layer engineering, not throwaway spike code.
- What's still open for Phase 5/8: build the actual point-in-time feature extraction and the negative-class (non-bankrupt company-year) sample from the ~7,973-company candidate universe, apply the D-006 financial-sector SIC exclusions to that universe, decide whether any of the 144 "no XBRL" cases are recoverable (e.g. a stale `CikBefore`), and pin down Candidate A's X14–X18 feature definitions before using it as a comparison baseline.
- 178 usable positive events (not the earlier 299–426 estimate) is a real statistical-power constraint: an out-of-time train/validation/test split will leave only a few dozen events in some splits, so Phase 8/9 should plan evaluation (e.g. confidence intervals, wider validation windows) accordingly rather than assuming Candidate A's larger-sample statistics carry over.
- BRD's licence requires citing "Florida-UCLA-LoPucki Bankruptcy Research Database" as the data source wherever it is used; Candidate A's use follows its GitHub README's citation request.
- BRD stopped updating after its December 2022 release, so no bankruptcies after that date are labelled — a stated limitation for any "recent" demo companies (already noted as a scope constraint, [scope.md §6](scope.md)).

## D-014 HTML is the primary document path; golden-set PDFs are generated
**Status:** Accepted (project owner, 2026-09-15) — resolves how [A-07](assumptions.md) is satisfied; design in [extraction.md](extraction.md), corpus in [golden_set.md](golden_set.md).

**Context.** The roadmap gives Phase 4 a golden evaluation set of 10-K statements with XBRL reference values, and QM-01 is worded as "field-level extraction accuracy … (PDF vs. XBRL reference)". But **SEC publishes 10-Ks as HTML / inline XBRL and never as PDF.** The original brief assumed a PDF-first pipeline; for SEC filers that input does not exist. Meanwhile FR-04 does require a PDF path, because analysts upload PDFs. [A-07](assumptions.md) anticipated this and allowed golden-set PDFs to be "obtained **or generated**".

Three ways to get a PDF corpus were considered:
- **Generate PDFs by rendering the filing HTML.** Licence-clear, reproducible by anyone who clones the repo, and both paths get scored against identical ground truth.
- **HTML only, defer PDF to Phase 5.** Smaller phase, but leaves FR-04 and the R-19 library spike unaddressed where the roadmap puts them.
- **Collect real investor-relations PDFs by hand.** Most realistic input, but manual, not reproducible for anyone else, and the terms for redistributing them are unclear.

**Decision.** **HTML is the primary document path for SEC filings**, and the golden set's PDFs are **generated from that same HTML** with `pymupdf.Story` (`extraction/render.py`). Both extractors are built behind one `DocumentExtractor` interface and measured against the same XBRL reference values.

**Consequences.**
- QM-01 will be reported **per path**, and the PDF figure is an **upper bound**: a rendered PDF has clean text, no scan artefacts and consistent fonts, which a real analyst upload often will not. This is stated wherever the number appears rather than left implicit ([golden_set.md](golden_set.md)).
- Rendering forces a non-cosmetic choice: `pymupdf.Story` draws tables with no ruling lines, and measured during this phase, a borderless render defeats table detection in *both* candidate libraries. `render.TABLE_CSS` adds borders to restore it. Without that, the golden set would have measured the renderer instead of the extractor. The side effect is that layout tables also gain borders, so the PDF path reports more "tables" than the HTML path — a counting artefact, not extra data.
- Building the corpus is slow (roughly ten minutes per filing, dominated by rendering) but runs once and is cached; `data/` stays gitignored and rebuildable, as in Phase 3.
- If real-world PDF accuracy later matters more than this arrangement can show, the honest fix is a small hand-collected PDF set at that point — not a re-reading of the generated numbers.

## D-015 PDF library: pdfplumber for text and tables
**Status:** Accepted (delegated to engineering judgement, 2026-09-15) — closes the [R-19](risks.md) spike; measurements in [golden_set.md](golden_set.md).

**Context.** [R-19](risks.md) ("library capabilities assumed but not verified, e.g. PDF table extraction quality") explicitly asks Phase 4 to **spike and measure before committing to a library**. `pyproject.toml` declared both `pdfplumber` and `pymupdf` without choosing. `scripts/table_extraction_spike.py` measures them over the golden set.

**The metric is reference-value recall, not table count.** Counting tables rewards a library for finding page-layout scaffolding. What matters is whether the figures XBRL reports for a filing can be found among the cells the library extracted, allowing for the scales (units/thousands/millions) and conventions (comma grouping, parentheses for negatives, and decimals — filings "in millions" routinely print `14,133.4`) a filing may use. That is a deliberate *preview* of QM-01 and not QM-01 itself: it asks "is this number present in some extracted cell", where QM-01 asks "was it extracted as the correct labelled field". Labelling needs Phase 5's canonical schema.

**What the measurement found (11 of 12 filings, 271 reference values):**

| | Found | Recall | Time |
|---|---:|---:|---:|
| pdfplumber | 179 | 66.1% | 1,774 s |
| pymupdf | 179 | 66.1% | 4,292 s |

**The two are equal, to the value** — on each cohort separately as well as overall, differing on only three individual filings and never by more than two values. They are *not* equal on cost: pdfplumber is **2.4× faster**, and on the worst filing returned the same 6/48 in 798 s where pymupdf took 3,021 s.

Table counts, by contrast, differ by 2.7× (10,437 vs 3,808 on the healthy cohort) while recovering identical values — the clearest possible vindication of not using table count as the metric.

**Decision.** **`pdfplumber` is the PDF extractor** (`extraction/pdf_extractor.py`), **chosen for speed, not accuracy — there is no accuracy difference to choose on.** `pymupdf` is kept because it renders HTML to PDF for the golden set (D-014), but is not used for extraction.

**Consequences.**
- The honest reading is that this is a low-stakes decision. Over the same corpus the **HTML path recovers 85% of reference values against the PDF path's 66%**, and 100% on modern filings against 95% — so the library that matters most for extraction quality is `lxml`, not either PDF library. This decision governs a fallback path (FR-04 uploads), which is where it belongs.
- **Neither library is the bottleneck; isolation is.** PDF recall is 95% on filings narrowed to their financial statements and 42% on those that fell back to whole-filing rendering. If Phase 5 needs better upload accuracy, the lever is better statement isolation or a text-based line parser — swapping libraries would buy nothing. That PDF *text* extraction finds values PDF *table* extraction misses ([golden_set.md §5](golden_set.md)) points the same way.
- Both share one real weakness: borderless tables. pdfplumber's line strategy finds nothing in them and its text strategy returns shredded cells. Real uploaded statements are often borderless, so this is a live limitation for FR-04, not a solved problem — tracked under [R-09/R-19](risks.md).
- `extraction/base.py`'s `DocumentExtractor` protocol keeps the library swappable, so reversing this does not reach beyond one module. Given the measured tie, reversing it would also change nothing measurable.
