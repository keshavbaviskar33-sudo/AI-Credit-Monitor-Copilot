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
| [D-016](#d-016-canonical-concept-set-fallback-chains-and-derivation-over-single-tag-mapping) | Canonical concept set: fallback chains and derivation over single-tag mapping | Accepted | 2026-09-16 |
| [D-017](#d-017-xbrl-is-phase-5s-primary-input-document-reconciliation-stays-small-and-secondary) | XBRL is Phase 5's primary input; document reconciliation stays small and secondary | Accepted | 2026-09-16 |
| [D-018](#d-018-tag-chains-declare-how-their-tags-relate-equity-is-split-by-scope) | Tag chains declare how their tags relate; equity is split by scope | Accepted | 2026-09-16 |
| [D-019](#d-019-ratio-status-model-four-states-caveats-are-warnings) | Ratio status model: four states, caveats are warnings | Accepted | 2026-09-16 |
| [D-020](#d-020-roaroe-use-ending-balances-not-average-balances-for-phase-6) | ROA/ROE use ending balances, not average balances, for Phase 6 | Accepted | 2026-09-16 |
| [D-021](#d-021-phase-6-audit-structured-warnings-machine-readable-missingconflicting-concepts) | Phase 6 audit: structured warnings, machine-readable missing/conflicting concepts | Accepted | 2026-09-16 |
| [D-022](#d-022-phase-7-financial-health-design-economic-direction-no-composite-score-mixed-status) | Phase 7 financial-health design: economic direction, no composite score, MIXED status | Accepted | 2026-09-17 |
| [D-023](#d-023-phase-6-correction-ratios_for_filing-sorts-periods-chronologically) | Phase 6 correction: `ratios_for_filing` sorts periods chronologically | Accepted | 2026-09-17 |
| [D-024](#d-024-phase-7-gains-an-analysis-window-default-5-periods) | Phase 7 gains an analysis window, default 5 periods | Accepted | 2026-09-17 |
| [D-025](#d-025-phase-8-target-a-365-day-discrete-time-bankruptcy-hazard-with-measured-censoring) | Phase 8 target: a 365-day discrete-time bankruptcy hazard, with measured censoring | Accepted | 2026-09-17 |
| [D-026](#d-026-the-observation-unit-is-a-filing-and-the-cutoff-is-its-receipt-date) | The observation unit is a filing, and the cutoff is its receipt date | Accepted | 2026-09-17 |
| [D-027](#d-027-evaluation-is-walk-forward-out-of-time-not-a-single-holdout) | Evaluation is walk-forward out-of-time, not a single holdout | Accepted | 2026-09-17 |
| [D-028](#d-028-model-family-regularised-logistic-hazard-as-primary-gradient-boosting-as-comparator) | Model family: regularised logistic hazard as primary, gradient boosting as comparator | Accepted | 2026-09-17 |
| [D-029](#d-029-explanations-are-a-domain-schema-not-an-attribution-librarys-output) | Explanations are a domain schema, not an attribution library's output | Accepted | 2026-09-18 |
| [D-030](#d-030-attribution-method-is-chosen-per-model-family-shap-is-not-used-on-the-linear-model) | Attribution method per model family; SHAP not used on the linear model | Accepted | 2026-09-18 |
| [D-031](#d-031-explanations-lead-with-financial-dimensions-not-feature-rankings) | Explanations lead with financial dimensions, not feature rankings | Accepted | 2026-09-18 |
| [D-032](#d-032-the-negative-universe-becomes-point-in-time) | The negative universe becomes point-in-time | Accepted | 2026-09-18 |
| [D-033](#d-033-the-model-output-is-a-ranking-and-the-schema-says-so) | The model output is a ranking, and the schema says so | Accepted | 2026-09-18 |
| [D-034](#d-034-gradient-boosting-becomes-the-primary-model-supersedes-d-028s-choice) | Gradient boosting becomes the primary model (supersedes D-028's choice) | Accepted | 2026-09-18 |
| [D-035](#d-035-narrative-signals-are-gated-on-assertion-not-on-keywords) | Narrative signals are gated on assertion, not on keywords | Accepted | 2026-09-18 |
| [D-036](#d-036-phase-11-produces-an-evidence-package-not-a-combined-score) | Phase 11 produces an evidence package, not a combined score | Accepted | 2026-09-19 |
| [D-037](#d-037-evidence-is-content-addressed-and-identity-is-a-separate-key) | Evidence is content-addressed, and identity is a separate key | Accepted | 2026-09-19 |
| [D-038](#d-038-disagreement-is-an-output-and-no-rule-adjudicates-it) | Disagreement is an output, and no rule adjudicates it | Accepted | 2026-09-19 |
| [D-039](#d-039-the-as-of-gate-runs-over-assembled-evidence-and-fails-closed) | The as-of gate runs over assembled evidence, and fails closed | Accepted | 2026-09-19 |
| [D-040](#d-040-the-synthesis-deliverable-is-the-verdict-on-the-draft-not-the-draft) | The synthesis deliverable is the verdict on the draft, not the draft | Accepted | 2026-09-19 |
| [D-041](#d-041-a-numbers-precision-comes-from-the-claim-not-from-a-tolerance-constant) | A number's precision comes from the claim, not from a tolerance constant | Accepted | 2026-09-19 |
| [D-042](#d-042-one-call-no-repair-loop-and-a-rejected-draft-is-returned) | One call, no repair loop, and a rejected draft is returned | Accepted | 2026-09-19 |
| [D-043](#d-043-the-model-provider-lives-behind-one-seam-and-the-phase-is-measured-without-it) | The model provider lives behind one seam, and the phase is measured without it | Accepted | 2026-09-19 |
| [D-044](#d-044-a-second-provider-and-the-prompt-leaves-the-vendors-envelope) | A second provider, and the prompt leaves the vendor's envelope | Accepted | 2026-09-19 |

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

## D-016 Canonical concept set: fallback chains and derivation over single-tag mapping
**Status:** Accepted (delegated to engineering judgement, 2026-09-16) — design in [canonical_schema.md](canonical_schema.md), resolves the mandatory mitigation [R-11](risks.md) named.

**Context.** [R-11](risks.md)/[A-06](assumptions.md) measured that a single XBRL tag per canonical concept fails for roughly half the golden set: `Liabilities` 6/12, `LongTermDebt` 7/12, `Revenues` 9/12, and the Phase 3 concept list's assumed revenue fallback `SalesRevenueNet` **0/12** — it is deprecated. Phase 5 had to decide how to map a canonical concept to XBRL reality without either (a) accepting that failure rate, or (b) blindly summing whatever tags happen to be present.

**Decision.** Every canonical concept in `financials/concept_map.py` carries an **ordered tuple of XBRL tags** tried in priority order, plus, where no tag is reliable, an explicit **derivation rule** stating the accounting relationship (`total_liabilities = total_assets - shareholders_equity`; `total_debt = short_term_debt + long_term_debt`). `resolver.py` runs two passes — direct tags, then one derivation pass — and marks a `DERIVED` fact's `formula` and `origin` so it is never mistaken for a reported figure (FR-07). When two tags in a chain are both present and disagree beyond rounding, the fact is `CONFLICTING`, not silently resolved to one of them.

**Alternatives.**
- **Single tag per concept**, as the original Phase 3 concept list assumed — ruled out by the measurement itself.
- **Blind summation of any XBRL fact that "looks related"** — rejected per the phase brief's explicit instruction not to assume candidates can simply be summed; every derivation here states the specific accounting identity it relies on.

**Consequences.** QM-01 (measured in [canonical_schema.md §12](canonical_schema.md)) shows the design working as intended: `total_liabilities`'s coverage rises from 6/12 raw-tag filings to a materially higher canonical completeness once the derivation is added, and `revenue` resolves for filers (Apple, UPS, Pyxus) that tag no `Revenues` concept at all. The residual gap is concrete and named, not hidden: `short_term_debt`/`long_term_debt` remain the weakest concepts (~32% completeness) because filers split debt across more tag variants than this phase's chains cover yet — a sizing decision against the 12-filing golden set, not a structural limitation, and listed as a deferred idea.

## D-017 XBRL is Phase 5's primary input; document reconciliation stays small and secondary
**Status:** Accepted (delegated to engineering judgement, 2026-09-16) — design in [canonical_schema.md §1, §7](canonical_schema.md).

**Context.** [D-005](decision_log.md) already established XBRL as the source of record for SEC filers. Phase 5's own brief (§13) separately asks for "source reconciliation" across whatever evidence Phase 4 produced (XBRL, HTML, PDF) — but also explicitly warns against building "an enormous reconciliation framework." Phase 5 had to decide how much of that framework was actually worth building now.

**Decision.** The resolver (`resolver.resolve_filing`) reads **only** XBRL `companyfacts`; it does not parse Phase 4's document tables into facts at all. A single, one-directional function (`reconciliation.corroborate_filing`) separately checks whether an already-resolved XBRL value is *also* independently visible in the filing's own cached HTML tables, reusing Phase 4's extraction and a numeric-rendering helper adapted from the Phase 4 R-19 spike. Finding it raises confidence and adds a provenance entry; not finding it changes nothing, because HTML recall on this same golden set is measured at 85.1%, not 100% ([golden_set.md §3](golden_set.md)) — treating absence as a conflict would manufacture distrust the data does not support.

**Alternatives.**
- **A general N-way reconciliation engine** comparing XBRL, HTML and PDF for every fact — rejected as the "enormous framework" the brief warns against, for a benefit (catching a genuine XBRL-vs-filing-text disagreement) never observed in the golden set.
- **No document reconciliation at all** — simpler, but forgoes a cheap, real corroboration signal (measured at 73.6% after the Phase 5 audit, [canonical_schema.md §12](canonical_schema.md)) that costs one extra HTML extraction Phase 4 already knows how to do, and gives up a mechanism for the (currently unobserved but plausible) case where XBRL and the filing's own text genuinely disagree.

**Consequences.** The PDF path is not used for reconciliation at all — only HTML, per [D-014](decision_log.md)'s primacy — so this decision inherits PDF's known weaknesses (borderless tables, older-filing recall) as "out of scope for corroboration," not as a gap to close here. If a future phase needs PDF-sourced canonicalization (e.g. an FR-04 upload with no XBRL at all), that is new resolver work, not an extension of this reconciliation function.

## D-018 Tag chains declare how their tags relate; equity is split by scope
**Status:** Accepted (delegated to engineering judgement, Phase 5 audit, 2026-09-16) — refines [D-016](#d-016-canonical-concept-set-fallback-chains-and-derivation-over-single-tag-mapping); detail in [canonical_schema.md §3, §15](canonical_schema.md).

**Context.** D-016 gave each concept an ordered list of XBRL tags, resolved by "highest-priority present tag wins; disagreement is a conflict". The Phase 5 audit ran the resolver against the golden set and found that rule false for most chains. Tags in one chain relate in three different ways, and treating them identically produced two failure modes: 32 correct values discarded as false conflicts, and — worse — silently understated debt, because additive components were read as alternatives (Apple's short-term debt omitted 7,979M of commercial paper and was returned as a confident `FOUND`). Separately, parent-only and total equity shared one chain, so the `total_liabilities` derivation subtracted the wrong equity and overstated liabilities by the noncontrolling interest (Tesla: 728M), while the balance-sheet validation confirmed the value using the same identity it was derived from.

**Decision.**
- Every concept declares a `TagResolution`: `ALTERNATES` (synonyms; disagreement is a conflict), `PREFERRED_SCOPE` (different scopes; keep the preferred value and record the others as candidates), or `COMPONENTS` (additive groups, each with alternative tagging, summed — never added within a group).
- Equity becomes three concepts: `shareholders_equity` (parent), `noncontrolling_interest`, and `total_equity`. The balance-sheet identity and the `total_liabilities` derivation use `total_equity`.
- Derived facts record `derived_from`, and validation refuses to score a check whose result is guaranteed by how an input was derived.
- Derivation runs to a fixpoint; only USD facts are candidates; synonym agreement tolerance tightens from 1% to 0.1%; one tag with two values for one period is a conflict.

**Alternatives.**
- **Keep flat chains and widen the tag lists** — would have added tags without fixing double counting or the scope conflicts; rejected by the Apple and Walmart debt figures.
- **Sum every related tag** — rejected for capital expenditures specifically, where the data cannot distinguish additive from overlapping tags; it stays `ALTERNATES` and conflicts visibly.
- **A full concept ontology** — unnecessary: three explicit policies covered every conflict observed.

**Consequences.** Value/period accuracy 87.0% → 97.2%, with the 7 remaining mismatches all a documented ground-truth definition difference (`LongTermDebt` reference rows); `CONFLICTING` facts 50 → 3; `total_debt` completeness 25% → 86%, cross-checked against filers' own debt totals. The balance-sheet check's reported pass count falls from 19 to 12 because the circular ones are no longer counted — a more honest number, not a regression. Each concept's policy is now a reviewable claim about accounting meaning, so a wrong policy is a one-line, testable fix rather than a hidden resolver behaviour.

## D-019 Ratio status model: four states, caveats are warnings
**Status:** Accepted (delegated to engineering judgement, 2026-09-16) — detail in [ratios.md §3](ratios.md).

**Context.** The Phase 6 brief (§9) lists up to six candidate ratio statuses (`CALCULATED`, `MISSING_INPUT`, `INVALID_DENOMINATOR`, `NOT_APPLICABLE`, `CONFLICTING_INPUT`, `LOW_CONFIDENCE`) and explicitly asks for "the minimum useful set" rather than all of them by default. Phase 5 already gives every input a `FactStatus` and a `Confidence`; a ratio status that duplicated those would be redundant, and one used to flag a caveat rather than a genuine inability to compute would blur "could this be calculated" with "should you look closer at it."

**Decision.** `RatioStatus` has four states: `CALCULATED`, `MISSING_INPUT`, `INVALID_DENOMINATOR`, `CONFLICTING_INPUT`. Everything else the brief's six-state list would flag — a derived input, a low-confidence input, a manually corrected input, a negative-but-legitimate equity denominator, a near-zero interest-expense denominator — is a `warnings` entry on an otherwise `CALCULATED` result, not a fifth or sixth status. When more than one required input has a problem, priority is `CONFLICTING_INPUT` > `MISSING_INPUT` > a bad denominator: a conflicting value is stronger evidence of a real number than an absent one, so it is reported first.

**Alternatives.**
- **Six states matching the brief's full list verbatim** — rejected: `NOT_APPLICABLE` has no case Phase 5's own model doesn't already collapse into "no value" (canonical_schema.md §16 explicitly treats an absent statement and an unresolved line the same way), and `LOW_CONFIDENCE`/`REQUIRES_REVIEW` would either duplicate `CanonicalFact.confidence` or sit unused, exactly like Phase 5's own `REQUIRES_REVIEW` (canonical_schema.md §6, "not yet raised").
- **Encode every caveat as its own status** (e.g. a `CALCULATED_FROM_DERIVED_INPUT` status) — rejected: it would make the status enum grow with every new caveat type discovered, and a caller filtering on "is this a usable number" would still need to special-case most of them back to "yes."

**Consequences.** A caller can branch on exactly four values to know whether a value exists, and separately inspect `warnings` (a list, so it composes — a ratio can carry more than one) to know whether to trust it fully. Tested in `tests/test_ratios_engine.py` (`test_conflicting_input_takes_priority_over_missing`, the low-confidence/derived/manually-corrected warning tests, the negative-equity tests).

## D-020 ROA/ROE use ending balances, not average balances, for Phase 6
**Status:** Accepted (delegated to engineering judgement, confirmed with the user during the Phase 6 design review, 2026-09-16) — detail in [ratios.md §4](ratios.md).

**Context.** The phase brief (§15) explicitly asks for a deliberate, documented choice between ending-balance ROA/ROE (simpler, always computable from one period) and average-balance ROA/ROE (more rigorous, needs the prior period's balance sheet to also have resolved). Phase 5's `companyfacts`-derived comparatives usually do carry a prior year, so average balances are technically available most of the time — the question was whether the added correctness was worth the added coupling.

**Decision.** Phase 6 ships ending-balance ROA/ROE only. Every ratio in the catalog, including these two, is a pure function of one period's own resolved facts — no ratio depends on another period's data. Average-balance ROA/ROE is deferred, not rejected: `ratios.md §7` names it as a future *additive* `RatioDefinition` (`roa_avg`, `roe_avg`), never a change to the existing ones' meaning.

**Alternatives.**
- **Average balances when the prior year resolved, silently falling back to ending balances otherwise** — rejected: two periods' worth of data quietly producing two different formulas under one `ratio_id` is exactly the kind of hidden behaviour §31/§34 warn against ("no hidden magic"), and it would couple a period's `RatioResult` to a second period's `CanonicalFact`s, complicating provenance (which period's facts does a `roa` result actually reference?) for a benefit — removing one year's balance-sheet timing noise — that is real but secondary for an MVP.
- **Average balances only, `MISSING_INPUT` when there is no prior year** — rejected: it would make ROA/ROE unavailable for a filer's very first monitored year purely as an artefact of this choice, not a real data gap.

**Consequences.** Every `RatioResult` — not only ROA/ROE — has the same guarantee: it was computed entirely from the named `period_label`'s own facts. `docs/ratios.md §4` states the simplification explicitly so it is never mistaken for a rigorous average-balance figure. M-2 measured ROA/ROE at 12/12 primary-period coverage on the golden set (`docs/ratios.md §6`) — the ending-balance choice costs nothing in coverage on this corpus, since `total_assets`/`shareholders_equity` are themselves near-universally complete.

## D-021 Phase 6 audit: structured warnings, machine-readable missing/conflicting concepts
**Status:** Accepted (delegated to engineering judgement, Phase 6 audit, 2026-09-16) — detail in [ratios.md §8](ratios.md).

**Context.** Before starting Phase 7, a deep audit of Phase 6 inspected every ratio's formula, inputs, and edge-case handling, and stress-tested the engine against the real 12-filing corpus including its most distressed filers (SandRidge, Peabody, iHeartMedia, Frontier, Expand Energy). The audit found no formula errors, no accounting-semantic errors, and no circularity — but found that `RatioResult.warnings` being plain strings (D-019's original design) was a real gap: `total_debt` and `ebit` have no direct XBRL tag at all (`concept_map.py`), so they resolve as `DERIVED` for nearly every filer, meaning a majority of `CALCULATED` real-corpus results already carry at least one warning. A downstream consumer (Phase 7) would have to substring-match English sentences to tell "routine derivation" apart from "negative equity" or "near-zero denominator" — exactly the fragility structured data is supposed to avoid.

**Decision.**
- `RatioResult.warnings` becomes `tuple[RatioWarning, ...]`, where `RatioWarning = {code: WarningCode, concept: str, message: str}`. Five codes, one per caveat the engine actually raises: `NEGATIVE_EQUITY`, `NEAR_ZERO_DENOMINATOR`, `DERIVED_INPUT`, `LOW_CONFIDENCE_INPUT`, `MANUAL_INPUT`. `message` keeps the exact human-readable text `explain()` already printed, so nothing is lost.
- `RatioResult.missing_concepts` and `.conflicting_concepts` are added as computed properties (empty unless the matching `RatioStatus` applies), giving machine-readable access to what `reason`'s prose already said, per the phase brief's own request (§13).
- `RatioDefinition.calculation_method` / `RatioResult.calculation_method` is added (`"ending_balance"` on `roa`/`roe`, `None` on every other ratio), making D-020's MVP simplification part of the typed result, not only this decision log and `docs/ratios.md`.

**Alternatives.**
- **Leave `warnings` as strings, document the convention for substring-matching** — rejected: it is exactly the fragility (parsing prose to make decisions) the rest of this schema's design (`FactStatus`, `RatioStatus`, `Confidence`) deliberately avoids everywhere else.
- **Generalize the near-zero-denominator warning to every ratio's denominator, not just `interest_coverage`'s** — investigated (checked all 362 `CALCULATED` real-corpus results for a near-zero-denominator artifact outside `interest_coverage`; found none — every extreme value traced to a real, materially-sized denominator and a genuinely extreme numerator, e.g. SandRidge's 2015 impairment). Deferred rather than implemented: there is no real-corpus evidence it is needed, and adding it speculatively would be exactly the "sounds sophisticated" complexity §34 warns against.
- **A larger structured-warning taxonomy anticipating future caveats** — rejected: five codes cover every caveat this engine raises today; a new caveat gets a new code when it is actually implemented, not preemptively.

**Consequences.** `scripts/evaluate_ratios.py` produces identical coverage numbers before and after (598 slots, 362 calculated, 0 conflicting, 0 invalid denominator) — this was a pure data-model change, no formula or status logic changed. 246/246 project tests pass (6 new/updated regression tests over the prior 244); 100% line coverage maintained on `ratios/`. This is a breaking change to `RatioResult.warnings`'s type, made deliberately now — before Phase 7 or any other consumer depends on the string form — rather than later, when it would be a harder migration.

## D-022 Phase 7 financial-health design: economic direction, no composite score, MIXED status
**Status:** Accepted (delegated to engineering judgement, Phase 7, 2026-09-17) — detail in [financial_health.md](financial_health.md).

**Context.** The Phase 7 brief asks for a deterministic financial-health and early-warning layer on top of Phase 6's ratios, with several open design questions it explicitly refuses to answer up front: whether ratio direction can be generalized (§8), whether to build a composite score (§5, §25), how a dimension with mixed ratio movements should be reported (§26), how negative-equity ratios should be trended (§21), and how broad a cross-dimension signal should require before firing (§15, §38).

**Decision.**
- **Ratio direction is per-ratio metadata, not inferred.** `health/direction.py::RATIO_DIRECTIONS` gives each of the 13 ratios an explicit `RatioDirection` (`HIGHER_IS_STRONGER`/`LOWER_IS_STRONGER`), kept in `health/`, not `ratios/registry.py` — Phase 6 states what a ratio equals, never whether that is stronger or weaker. A completeness test enforces the two catalogs cannot drift apart.
- **No composite score anywhere.** `FinancialHealthReport` has no overall number; only per-dimension `DimensionStatus` and per-ratio `RatioTrend`/`Signal` objects, each with its own evidence.
- **A dimension with both improving and deteriorating ratios is `MIXED`**, a fifth `DimensionStatus` value alongside `IMPROVING`/`STABLE`/`DETERIORATING`/`INSUFFICIENT_DATA` — never silently netted into one direction.
- **A negative-equity ratio's trend is `NOT_MEANINGFUL`, not a numeric increase/decrease claim**, whenever a `WarningCode.NEGATIVE_EQUITY` warning appears anywhere in the analyzed window (not just the latest period) — a sign-crossing denominator breaks the ordinary interpretation for every period the ratio spans while it holds, not only the one period the warning is attached to.
- **`MULTI_DIMENSION_DETERIORATION` requires a majority (3 of 5) dimensions**, not "any 2" — two dimensions can move together from shared inputs (leverage and coverage both use debt-adjacent concepts) without a genuinely broad-based move.
- **No signal severity (`INFO`/`WATCH`/`ALERT`).** Considered per the brief's own §30 and rejected: a severity label is one step from a hidden credit-risk score; `persistence` and dimension breadth already give a downstream consumer (Phase 12) what it needs to weight a signal itself.
- **Thresholds are collected in `health/thresholds.py`**, one module, each constant documented with its rationale — satisfies FR-10 ("thresholds live in configuration, not hard-coded constants") the same way `ratios/engine.py`'s own documented module constants already do, without introducing environment/settings plumbing for values that are analytical, not operational.

**Alternatives.**
- **A single financial-health score** — rejected per the brief's own explicit instruction (§5, §25) and this project's existing avoidance of manufactured precision (mirrors D-010's refusal to call the future ML output a "probability of default").
- **Silently resolving a mixed dimension to whichever direction has more ratios** — rejected: hides genuinely ambiguous information from exactly the audience (an analyst) who needs to see it.
- **A relative near-zero-denominator-style warning generalized to every trend** — not needed; the existing `STABLE_MAGNITUDE_THRESHOLD` noise floor already serves this role for trend magnitude, and Phase 6's own equivalent generalization was already investigated and rejected for the same reason (D-021).

**Consequences.** `docs/financial_health.md` documents the full methodology, signal catalog and every threshold's rationale. `scripts/evaluate_financial_health.py` (M-3) measured the real 12-filing corpus: 40.4% of ratio-trend slots reach a conclusive direction (the rest `INSUFFICIENT_DATA`, expected given `ratios.md` §6's own comparative-year coverage findings — every filing's liquidity dimension is `INSUFFICIENT_DATA` on this corpus, verified by hand, not a bug), 37 signals fired across 12 filings with no false positive found on manual inspection of all 12 reports. Real-corpus inspection of SandRidge FY2015 (the same distressed filer Phase 6's own audit stress-tested) surfaced one real bug, fixed the same day: `RatioTrend.explain()` could print a percent change whose sign disagreed with the absolute change it sat beside, when the ratio's baseline value was negative — fixed by omitting the percentage from the printed line (not the underlying field) whenever the two signs disagree, with a regression test built directly from the real SandRidge numbers.

## D-023 Phase 6 correction: `ratios_for_filing` sorts periods chronologically
**Status:** Accepted (delegated to engineering judgement, found ahead of Phase 7, 2026-09-17) — fix in `ratios/engine.py`.

**Context.** Phase 7's own kickoff process (§3 of its brief: "inspect the current repository... do not assume the recap fully describes the current implementation") checked what order `CanonicalFilingFacts.period_labels` actually returns on real filings before building a trend engine on top of it. It is **not** chronological: `period_labels` follows XBRL fact insertion order from the filer's raw `companyfacts` JSON, and real golden-set filings return it out of order — e.g. iHeartMedia's own filing reports `('FY2014', 'FY2015', 'FY2016', 'FY2013')`, oldest year last. `ratios/engine.py`'s own `calculate_ratio_history` and `ratio_history_changes` both require chronological input to produce correct deltas, and `ratios_for_filing`'s default (`periods=None` → every period on the filing) was passing `filing.period_labels` straight through, unsorted — a real latent bug, simply never triggered because every existing test's `_FakeFiling` fixture happened to supply already-sorted labels.

**Decision.** `ratios_for_filing` sorts `filing.period_labels` into fiscal order (parsing the year out of each `"FYnnnn"` label) before passing it to `calculate_ratio_history`, when `periods` is not given explicitly. An explicit `periods=` argument is trusted exactly as given — a caller naming periods directly is choosing an order on purpose, not asking for the filing's default.

**Alternatives.**
- **Fix it only in Phase 7's own `health/trend.py`** (defensively re-sort there too, regardless of this fix) — done anyway, since `health/` must never trust any caller's ordering by design. But leaving the Phase 6 bug unfixed would leave `ratios_for_filing`'s own documented contract (`calculate_ratio_history`'s docstring: "in the given period order") silently false for its own default path, and any other future Phase 6 consumer (not just Phase 7) would inherit the same latent bug.
- **Leave it and document the caveat** — rejected: this is a correctness bug with a cheap, well-tested fix, not a design trade-off worth just disclosing.

**Consequences.** New regression test (`test_ratios_for_filing_sorts_periods_chronologically_by_default`) reproduces the real out-of-order pattern with a `_FakeFiling` fixture. Zero behavior change for every existing test (all supplied already-sorted labels) and zero change to `scripts/evaluate_ratios.py`'s M-2 numbers (that script calls `resolve_filing` → `ratios_for_filing` per filing but never chains into `ratio_history_changes`, so the previously-unsorted order never affected its output). 322/322 project tests pass after this fix plus Phase 7's own test suite.

## D-024 Phase 7 gains an analysis window, default 5 periods
**Status:** Accepted (delegated to engineering judgement, Phase 8 prerequisite A, 2026-09-17) — implementation in `health/engine.py`, constant in `health/thresholds.py`, tests in `tests/test_health_window.py`.

**Context.** The Phase 1–7 architecture audit ([architecture_audit.md §F-2](architecture_audit.md)) found that `analyze_financial_health` had no analysis-window parameter and that `trend._direction_and_magnitude` computes direction as a pure first-to-last comparison (`values[-1] - values[0]`). With the 2–4 periods a single filing supplies, that is unremarkable. Once the multi-filing path supplies 9–20 periods it is not: a `MARGIN_COMPRESSION` signal can fire because 2025's margin is below 2006's, which is a fact about two decades of business mix, not a monitoring signal. The audit measured the engine's sensitivity directly — on multi-filing input the signal count moved 81 → 153 → 116 → 140 across windows of 3, 5, 8 and unbounded, **non-monotonically**, because adding one earlier period can flip an endpoint comparison outright. Conclusive-direction rate, by contrast, was stable at 89–92% across all four.

**Decision.** `analyze_financial_health(..., analysis_window: int | None = DEFAULT_ANALYSIS_WINDOW)` restricts the analysis to the most recent *N* fiscal periods. `DEFAULT_ANALYSIS_WINDOW = 5`. `None` restores the previous unbounded behaviour. The window is applied over the **union** of period labels across every ratio, so all ratios in one report span the same window rather than a sparsely covered ratio silently reaching further back than its neighbours. It counts **period labels, not calculated values**, so a gap inside the window stays a gap — taking "the last 5 calculated periods" would bridge a missing year silently, which is exactly what `DISCONTINUOUS_HISTORY` exists to prevent. `FinancialHealthReport.analysis_window` records the request and `periods_considered` records the effective result.

**Why 5.** Three reasons, none of them a round number: (a) it is the span a credit analyst conventionally reads, and more than a filing itself presents — a 10-K carries three income-statement years and two balance-sheet dates; (b) it leaves slack above `MIN_CONSECUTIVE_PERIODS_FOR_TREND = 3`, so one missing year does not collapse a trend to `INSUFFICIENT_DATA`; (c) **it is a no-op for every pre-Phase-8 caller** — a single filing never yields more than four periods — so adopting it as the default changed no existing result and all 324 prior tests passed unmodified.

**Alternatives.**
- **Keep the default unbounded and require callers to opt in.** Rejected: the audit's evidence is that unbounded is the *wrong* answer once real history is supplied, and a default that is wrong in the new normal case is a trap for the next consumer, not a conservative choice.
- **Express the window in calendar years rather than periods.** Rejected: the data is fiscal-period indexed with real gaps, so "the last 5 years" and "the last 5 periods" differ exactly when a filer missed a year — and the period count is what the trend arithmetic actually consumes.
- **Make the window adaptive (e.g. all periods since the last gap).** Rejected as hidden behaviour: two companies' reports would then describe different spans without saying so.

**Consequences.** Signals become interpretable as "over the last five reporting periods", which is a statement an analyst can check. The deferred slope-fit trend method ([financial_health.md §9](financial_health.md)) was deferred on the premise of "typically 2-4 usable periods per filing"; at 5–20 periods that premise no longer holds and the deferral should be revisited — not by adopting `scipy`, since `statistics.linear_regression` is in the standard library. Phase 7's "no false positive found on manual inspection of all 12 reports" was a claim about 37 signals from single-filing input and does **not** transfer to the 153 signals the windowed multi-filing path produces; re-validation is outstanding and recorded as a limitation.

## D-025 Phase 8 target: a 365-day discrete-time bankruptcy hazard, with measured censoring
**Status:** Accepted (delegated to engineering judgement, Phase 8, 2026-09-17) — implementation in `modeling/labels.py`, full rationale in [predictive_model.md](predictive_model.md).

**Context.** Phase 8 had to choose a prediction target rather than inherit one. The only externally observed outcome available is the Florida-UCLA-LoPucki Bankruptcy Research Database ([D-013](#d-013-training-data-candidate-b-self-built-sec--brd-as-primary)): 1,218 cases, one row per petition, with a filing date, chapter and CIK. Phase 7's deterioration signals, ratio thresholds and any model output are explicitly *not* candidates for ground truth.

**Decision.** The target is **a BRD-recorded Chapter 7/11 petition filed within 365 days after the observation's information cutoff**. Stacked across companies and filings this is a **discrete-time hazard** in person-period form, which is the standard multi-period bankruptcy specification rather than a single-snapshot classification; it is estimated by a binary classifier over the at-risk intervals.

Two parameters that could have been guessed were measured instead:

- **Label completeness is 2020-12-31, not BRD's 2022-12-11 release date.** Case entry lags the petition, so the final release years are thin: BRD records 25 cases/year on average across 2011–2019, 56 in 2020, then **8 in 2021 and 6 in 2022**. `measure_label_completeness` compares each year against a normal-conditions reference median and walks back to the last year that does not look truncated; on this data that is 2020. Rows whose forward window ends after 2020-12-31 are **censored, not scored as survivals** — an event that had not yet been catalogued is unobserved, and labelling it `0` would teach the model that the recent past was safe.
- **The horizon is set from the filing-to-event gap.** A company stops filing once it fails, so the horizon must reach the petition from the last 10-K. Measured across the 298 event companies with any prior annual filing: median 235 days, p75 337, p90 398. A 365-day window reaches **81.5%** of events; 547 days reaches 96.6%; 730 days reaches 98.7%.

**Why 365 despite reaching only 81.5% of events.** Consecutive annual filings are ~12 months apart, so a 365-day window makes consecutive observations *tile* the timeline without overlapping — one at-risk interval, one outcome, uncorrelated labels. A longer window makes one event label two or three consecutive rows, which inflates the apparent positive count with duplicates of the same event and correlates the errors. It also matches the product: [D-001](#d-001-product-framing-monitoring-copilot) re-assesses a company when it publishes, so "before the next annual report" is the question an analyst is actually asking. And because the horizon is subtracted from the completeness cutoff, 365 days preserves prediction dates through 2020-01-01 where 730 days would stop at 2019-01-01 — losing the observation years that carry 2020's 56 events. A 730-day panel is built alongside as a robustness check so the cost of this choice is measured, not asserted.

**A `0` is a genuine negative, not a mislabelled positive.** An event 500 days after the last filing makes that row's label correctly `0` — the company genuinely did not file within 365 days. The cost of the short horizon is a *smaller positive count*, not label noise.

**Alternatives.**
- **Continuous-time survival (Cox).** Rejected: the covariates only change when a filing arrives, so the data is intrinsically interval-based; a discrete-time hazard is the matched specification and yields a directly interpretable per-period probability. Cox would also add a dependency for no gain in what the product can say.
- **One row per company at its final pre-event filing.** Rejected: it discards the survival years that identify the baseline hazard, and builds a dataset where every failing company appears only at its worst — which teaches the model to recognise distress it has already been told about.
- **A distress proxy (negative equity, covenant-style thresholds, Phase 7 signals).** Rejected outright under the phase's absolute rule. These are features or comparators, never outcomes.
- **Rating downgrades.** No licensed source available to this project.

**Consequences.** BRD's inclusion rule (large public filers) means a `0` says "no *large public* bankruptcy was recorded", not "nothing bad happened" — label noise confined to the negative class, documented rather than corrected because no better event source is available here. The usable prediction-date span is bounded on the left by XBRL phase-in (~2010) and on the right by label completeness (2020-01-01), which is the binding constraint on statistical power for the whole phase.

## D-026 The observation unit is a filing, and the cutoff is its receipt date
**Status:** Accepted (delegated to engineering judgement, Phase 8, 2026-09-17) — implementation in `modeling/contract.py` and `modeling/dataset.py`.

**Context.** A supervised row needs a timestamp. Two candidates: the fiscal period end (FY2019 ends 2019-12-31) or the SEC filing receipt date (the FY2019 10-K arrives 2020-03-31). They differ by two to four months, and that gap is where leakage lives.

**Decision.** One observation per company per annual filing. `information_cutoff = prediction_date =` the filing's SEC `filingDate`. A row may use only filings received on or before that date, and for any fiscal period reported by more than one such filing it uses the **earliest-filed** value ([D-008](#d-008-point-in-time-as-filed-data-rule)), never a later restatement.

Three enforcement layers, deliberately redundant:
1. `financials.history.resolve_company_history(filed_on_or_before=T)` drops later filings **before the resolver sees them**, so their facts cannot influence a conflict, a derivation or a period set. Filtering facts after resolution would not be enough: a `total_liabilities` derived at a fixpoint that consumed a 2024 filing is contaminated even if the surviving fact's provenance points at a 2019 accession.
2. `CompanyFinancials.as_of(T)` keeps the earliest-filed value per (concept, period).
3. `Observation.assert_no_future_information` **re-checks every emitted row** against the filing dates and raises `LeakageError`. Layers 1 and 2 are claims about how the builder was written; layer 3 is a check on the object that was built.

**Cost, accepted deliberately.** Re-resolving the visible history at every cutoff is O(filings²) per company rather than O(filings). `resolve_filing` is memoised per accession within a build (a pure-function cache — the *set* of filings fed to `CompanyFinancials` still changes at every cutoff), but the panel build still takes tens of minutes over ~690 companies. Correctness is worth it; a single silent leak would invalidate every number in the phase.

**Alternatives.**
- **Index by fiscal period end.** Rejected: it credits the model with knowing a year's results on 31 December, three months before anyone did. It is also the most common way published bankruptcy-prediction results become unreproducible.
- **Resolve each company once and filter afterwards.** Rejected for the derivation-contamination reason above — far cheaper, and wrong in a way that no downstream check would catch.
- **Use the latest restated value, as most convenient datasets do.** Rejected: M-4 measured 453 restatements across just 12 companies, with the largest exceeding 100% of the original value. Hindsight would be substantial and invisible.

**Consequences.** Features and labels are separated by construction, and the separation is testable — `tests/test_modeling_contract.py` and `tests/test_modeling_dataset.py` deliberately violate each rule and assert the refusal. `Observation.contributing_accessions` carries the provenance chain (feature → ratio/concept → fact → accession → filing date) the product requires (FR-07). Rebuilding observations from the flat CSV drops that list, so a rebuilt row cannot re-run the assertion; the guarantee belongs at build time, where the filing dates are known.

## D-027 Evaluation is walk-forward out-of-time, not a single holdout
**Status:** Accepted (delegated to engineering judgement, Phase 8, 2026-09-17) — implementation in `modeling/splits.py`.

**Context.** The panel is company × time with repeated companies and a rare, macro-clustered event (2009, 2015–16 energy, 2020). A random split is meaningless: it trains on 2020 and tests on 2016, and puts a company's 2016 row in train with its 2017 row in test when the two share most of their history.

**Decision.** **Expanding-window walk-forward**: train on every row dated before year *Y*, test on year *Y*, stepping *Y* across the usable span. Every observation after the burn-in is scored exactly once by a model that never saw it or anything after it, and the pooled out-of-fold predictions give one evaluation set with the full event count. `assert_temporal_ordering` independently verifies, per fold, that no training row is dated at or after the earliest test row.

A fold is skipped when its training data holds fewer than 20 events (the estimate would be noise dressed as evidence) or its test year holds none (only negatives, which shifts the pooled base rate without adding discrimination information). Skipped years are reported, not silently dropped.

**Company overlap is reported, not assumed away.** A company can be in an early fold's training set and a later fold's test set. That is the production situation — you *do* have history on the company you are scoring — so it is the headline design. But persistent company characteristics could let a model memorise rather than generalise, so `company_disjoint_folds` builds the stricter variant (a test company is removed from that fold's training set entirely) and both are reported. A large gap is evidence of memorisation; a small one is evidence against it.

**Alternatives.**
- **A single out-of-time holdout.** Rejected: it wastes the scarce resource. Reserving the last quarter of the timeline leaves a test set whose confidence interval is wider than any effect being measured.
- **Grouped k-fold by company, ignoring time.** Rejected: it lets a model trained on 2020 score 2012, which no deployment can do, and hides regime shift entirely.
- **Nested CV with hyperparameter search inside each fold.** Rejected under §24: with this event count the search would fit noise, and the phase's goal is a defensible first model, not a tuned one.

**Consequences.** Every headline metric carries a **company-clustered** bootstrap interval — resampling rows would treat one company's ten filings as ten independent draws and report an interval far too narrow. Model comparisons use a **paired** bootstrap on the difference, because both models score identical rows and comparing two overlapping intervals is the wrong (and over-conservative) test.

## D-028 Model family: regularised logistic hazard as primary, gradient boosting as comparator
**Status:** Accepted (delegated to engineering judgement, Phase 8, 2026-09-17) — implementation in `modeling/model.py`, results in [predictive_model.md](predictive_model.md).

**Context.** [D-004](#d-004-ml-model-uses-financial-features-only) fixes the inputs (financial features only) and the roadmap names logistic regression, but Phase 8's brief explicitly refuses to let any algorithm be assumed correct. The deciding facts are the data's: a low-hundreds event count, tens of features, a heavily imbalanced panel, repeated companies, and a product requirement that the output be explainable to an analyst who must act on it.

**Decision.** Three families, each answering a different question, all evaluated on identical folds:

- **Heuristics** (no fitting): rank directly on `debt_to_assets`, on `working_capital_to_assets`, on `ebit_to_assets`, and on Phase 7's own `n_deteriorating_ratios`. The last is the most important comparator in the phase — it asks whether the ML layer beats the product's *existing* output used as a score.
- **L2-regularised logistic regression** (`C=0.1`) on standardised features with median imputation and explicit missingness indicators — the **primary** model. It is the specification the hazard framing implies, its coefficients are directly readable as log-odds per standard deviation, and it produces probabilities that can be calibration-checked.
- **`HistGradientBoostingClassifier`** with deliberately small capacity (`max_leaf_nodes=4`, `min_samples_leaf=40`, `max_iter=150`, early stopping) — the serious alternative, included because it handles missing values natively and captures interactions, and because assuming linearity without checking would be exactly the unexamined assumption the phase forbids.

`C=0.1` and the tree constraints are set from the sample size, not tuned. **No hyperparameter sweep** (§24): with this events-per-variable ratio a search optimises noise, and an unregularised fit produces large unstable coefficients that read as findings.

**Imputation lives inside the pipeline**, so it is refit on each fold's training rows only. Imputing on the full panel would leak the future's medians into the past — a quiet, common, and completely invalidating error.

**Alternatives.**
- **XGBoost / LightGBM.** Rejected: a new heavy dependency for a capability `HistGradientBoostingClassifier` already provides, on a dataset far too small for the extra capacity to be anything but variance. This also matches the Phase 1–7 audit's own recommendation.
- **Synthetic oversampling (SMOTE).** Rejected: it interpolates between minority rows, which for a company × time panel would fabricate companies that never existed, and it must never cross a temporal fold boundary. The event rate here does not require it.
- **A neural model.** Rejected: hundreds of events, tens of tabular features, and an explainability requirement.
- **Altman Z-score as the model rather than a baseline.** Its components are in the feature set (`working_capital_to_assets`, `ebit_to_assets`, `revenue_to_assets`), but its published coefficients were fitted on 1960s manufacturers; using them unchanged would import a different population's parameters. The components are offered to the model instead, and the single-ratio heuristics play the baseline role.

**Consequences.** Interpretability for Phase 8 is standardised coefficients only (§22) — Phase 9 owns anything beyond that, and `shap`, though installed via the `ml` extra, is deliberately unused here. The shipped artifact is the primary model refit on all usable history, with a JSON sidecar recording family, configuration, feature set, target definition, seed, training span, evaluation strategy and metrics; every *number reported about* it comes from the walk-forward evaluation, which never trained on what it scored.

## D-029 Explanations are a domain schema, not an attribution library's output
**Status:** Accepted (delegated to engineering judgement, Phase 9, 2026-09-18) — implementation in `explain/schema.py`, tests in `tests/test_explain_local.py`.

**Context.** Phase 9 needed to expose *why* the model says what it says, to phases that do not exist yet (12's synthesis, 13's review, 14's UI). The obvious shortcut is to hand those phases whatever the attribution library returns — a SHAP `Explanation`, a coefficient vector, a permutation-importance array. Each is a different shape, each is library-specific, and none of them carries the thing this product actually needs: the chain from a model contribution back to the filing it came from.

**Decision.** `explain/` defines its own schema — `ModelExplanation`, `FeatureContribution`, `DimensionAttribution`, `EvidenceLink`, `Caveat` — and every attribution method is converted into it by an adapter. **Nothing outside `explain/` imports `shap` or touches a scikit-learn internal.** Adding a model family means writing one `Attributor` (three methods), not touching the schema, the grouping or the provenance walk.

Two properties of the schema are load-bearing rather than decorative:

- **`Caveat` is structured data, not prose.** Same reasoning as D-021's move from string warnings to `WarningCode`: a downstream consumer must be able to branch on "is this explanation trustworthy" without substring-matching English. Eight codes, one per specific checkable problem (`NOT_CALIBRATED`, `MISSINGNESS_DRIVEN`, `COHORT_CONFOUNDED`, `PROVENANCE_INCOMPLETE`, `DERIVED_INPUT`, `LOW_CONFIDENCE_INPUT`, `LIMITED_HISTORY`, `UNSTABLE_ATTRIBUTION`).
- **Model-level caveats travel with every prediction.** Calibration and cohort confounding are properties of the *model*, established by its evaluation, not of any one row. They are attached to each explanation anyway, because a caveat that lives only in a document alongside the number is a caveat that will be separated from it.

**Alternatives.**
- **Return SHAP objects directly.** Rejected: it would make `shap` a load-bearing dependency of Phases 12-14, and SHAP's `Explanation` has no field for an accession number or a filing date.
- **A dict of feature → float.** Rejected for the same reason — it is the attribution without the evidence, which is the half that makes it usable in a credit product.
- **A single "explanation confidence" score.** Rejected explicitly (§43, and consistent with D-010/D-022): caveats name specific, checkable problems; a number would hide exactly the distinctions the rest of this project keeps apart.

**Consequences.** Phases 10+ consume `ModelExplanation` and are insulated from whatever explains the model. The cost is one conversion layer and the discipline of keeping it; the benefit is that replacing the attribution method — or the model family — is a change inside `explain/adapters.py`.

## D-030 Attribution method is chosen per model family; SHAP is not used on the linear model
**Status:** Accepted (delegated to engineering judgement, Phase 9, 2026-09-18) — implementation in `explain/adapters.py`, verified in `tests/test_explain_adapters.py`.

**Context.** `shap` was installed in the `ml` extra in Phase 2 and deliberately unused in Phase 8. The Phase 9 brief (§8) is explicit that "Phase 9 = add SHAP" is not the answer and asks for the question to be settled on merit.

**Decision.** The method is dispatched from the fitted estimator, not chosen by the caller:

- **Logistic pipeline → exact linear contributions.** For `SimpleImputer → StandardScaler → LogisticRegression`, feature *j*'s contribution to observation *i*'s log-odds is exactly `coefficient_j × scaled_value_ij`, and those terms plus the intercept **are** the model's own log-odds rearranged. Measured on the real artifact, the decomposition reconstructs the model's `decision_function` to **3.6e-15**. A linear SHAP explainer computes the same decomposition with the mean folded into the baseline instead of the intercept, at more cost and with a dependency in the middle. **SHAP adds nothing here and is not used.**
- **Gradient boosting → TreeSHAP.** A tree ensemble's prediction is not a weighted sum of its inputs, so there is no closed form. TreeSHAP computes exact additive Shapley values for tree models in polynomial time, which is the one capability in this phase that cannot be reproduced in a few lines. This is the only place `shap` is imported, and it is imported lazily.

Both methods produce **additive contributions in the model's own link units**, so both land in the same `FeatureContribution` objects. `AttributionResult.reconstruction_error` checks the decomposition against the model's own output; an attribution that does not reconstruct the prediction is wrong and silently so, and `local.py` raises an `UNSTABLE_ATTRIBUTION` caveat if it ever fails.

**Alternatives.**
- **SHAP everywhere, for consistency.** Rejected: consistency of *library* is not a goal; consistency of *output shape* is, and the adapter layer already delivers it. Using an approximation where an exact answer exists would be strictly worse.
- **Permutation importance as the primary method.** Rejected as the primary: it is global-only, so it cannot explain an individual prediction, which is the product requirement. Retained as a cross-check in `phase8_train_evaluate.py`.
- **Partial dependence / ICE / ALE.** Not implemented. They answer "how does the model respond to this feature across its range", which is a model-behaviour question. With attribution already exact for the primary model and the phase's real uncertainty lying in *what the features mean* rather than *how the model maps them*, these would add plots without adding evidence. Reconsider if a non-additive model becomes primary.
- **Counterfactuals.** Considered and rejected for this dataset (§29). With features this correlated — `debt_to_assets`, `debt_to_equity` and `liabilities_to_assets` cannot move independently — a minimal counterfactual would routinely propose a financially impossible combination. Revisit only with explicit constraints.

**Consequences.** The primary model's explanations are exact and free. `shap` remains an optional dependency exercised only by the challenger. The honest finding for the phase brief is recorded rather than the expected one: **SHAP was evaluated and is unnecessary for the model that ships.**

## D-031 Explanations lead with financial dimensions, not feature rankings
**Status:** Accepted (delegated to engineering judgement, Phase 9, 2026-09-18) — implementation in `explain/groups.py`.

**Context.** The model has 97 columns (57 features plus 40 missingness indicators). The default output of any attribution method is a ranked list of those columns.

**Decision.** The headline unit of explanation is a **group**, on one of two axes — the five Phase 7 financial dimensions (liquidity, leverage, profitability, coverage, cash flow) plus named residual groups (`size`, `data_quality`, `cross_cutting`, `missingness`), or the six Phase 8 feature families. Individual features appear only inside their group.

Two reasons, one statistical and one about the audience:

- **Correlated features make individual rankings arbitrary.** `debt_to_assets`, `debt_to_equity` and `liabilities_to_assets` measure one idea three ways; every additive attribution splits a shared effect among them in a way that is unstable between them and stable across them. Ranking the three separately invites a conclusion about *which leverage measure matters* that the data does not support.
- **Dimensions are the vocabulary an analyst can argue with.** "Leverage is the main driver" can be challenged against the filing. "`trend_pct_debt_to_equity` ranked fourth" cannot.

Dimensions are derived from `RatioDefinition.category`, so the explanation catalog cannot drift from the ratio catalog. A feature with no financial dimension records `None` rather than being forced into the nearest one.

**Missingness is its own group, never folded into the dimension it is about.** `ratio_roa__missing` keeps ROA's dimension for display but groups under `missingness`, because the whole Phase 9 missingness question turns on separating "the model reacted to profitability" from "the model reacted to profitability being unavailable".

**Alternatives.**
- **Rank all 97 features.** Rejected above.
- **Group only by feature family.** Rejected as the sole axis: families are an engineering artefact (`levels` vs `ratios` is about how Phase 8 computed a number, not about what it means). Both axes are produced; dimension leads.
- **Cluster features by empirical correlation.** Rejected: data-driven groups would shift between datasets and be unnameable, defeating the point of speaking the analyst's vocabulary.

**Consequences.** Phase 9's headline tables are per-dimension. The measured payoff is visible immediately: at group level the primary model's driver ordering is stable across eras (Spearman 0.83-0.97), which no individual-feature ranking achieves.

## D-032 The negative universe becomes point-in-time — and that is not the confound
**Status:** Accepted (delegated to engineering judgement, Phase 9, 2026-09-18) — implementation in `scripts/phase9_pit_universe.py`, `phase9_pit_corpus.py`, `phase9_pit_panel.py`, `phase9_size_matched.py`; results in [model_evaluation_explainability.md §13](model_evaluation_explainability.md).

**Context.** Phase 8 named a survivorship-selected comparison cohort as its largest limitation and assumed correcting it was a substantial data-acquisition project, to be done "later". Phase 9's brief (§26) asked for that assumption to be tested rather than inherited.

**Decision, part 1 — build it, because it is cheap.** EDGAR publishes `full-index/YYYY/QTRn/form.idx`, a quarterly list of every filing received, which is the authoritative point-in-time record and includes companies that have since delisted. 48 requests, streamed and discarded rather than cached, a few hundred KB kept. That is not a project; it is an afternoon.

It immediately quantified what Phase 8 could only describe: of the **16,008** companies that filed an annual report between 2009 and 2020, only **3,625 (22.6%)** appear in SEC's current ticker file. Phase 8 sampled its comparison cohort from under a quarter of the real population, selected for survival.

**Decision, part 2 — report the negative result rather than the expected one.** A size-matched panel was rebuilt on the point-in-time cohort (264 event companies unchanged, 426 comparison companies, only 139 still listed today) and re-measured. **Performance did not move and the confound got worse:**

| | Survivor | Point-in-time |
|---|---:|---:|
| Logistic ROC-AUC | 0.803 | 0.797 |
| Boosting ROC-AUC | 0.887 | 0.894 |
| Cohort separability (logistic) | 0.792 | **0.843** |

**The cause, measured.** BRD records only large public bankruptcies, so the event cohort is large by construction. Median log total assets: event 21.24, Phase 8 comparison 19.94 (3.7× gap), point-in-time comparison 18.56 (**14.5× gap**). Sampling from the real population made the mismatch worse, because the survivor frame was already tilted large. **The confound is eligibility, not survival.**

A size-matched variant (comparison rows restricted to the event cohort's 10th–90th percentile band) narrows it — separability 0.843 → 0.819 logistic, 0.916 → 0.878 boosting — but does not close it: the gap between cohort separability and bankruptcy AUC stays at +0.035 to +0.038, and the model's lift over its own base rate *falls* (3.6× → 3.1×).

**Alternatives.**
- **Leave it as a documented limitation, as Phase 8 did.** Rejected: the cost of testing it turned out to be trivial, and the test overturned the diagnosis. A limitation that has never been measured is a guess.
- **Replace the survivor panel with the point-in-time one as the headline.** Rejected: it is not better, it is differently biased. Both are reported, bracketing the truth — the survivor cohort hides failures among its negatives, the point-in-time cohort includes small failures BRD never recorded.
- **Keep sampling until the probe comes down.** Rejected as the wrong shape of effort: three constructions were tested and the residual is structural, not a sampling-luck problem.

**Consequences.** The point-in-time universe is retained as infrastructure and is the frame the eligibility-matched design will need, but it does not on its own make pooled metrics interpretable. The **within-event-cohort** measurement remains the only defensible headline (logistic 0.733, boosting 0.787). The concrete next step is no longer "build a point-in-time negative universe" — that is done — but **"match the negative universe on BRD's own eligibility conditions"**, which is a narrower and better-specified problem than the one Phase 8 handed forward.

## D-033 The model output is a ranking, and the schema says so
**Status:** Accepted (delegated to engineering judgement, Phase 9, 2026-09-18) — formalises Phase 8's conclusion; implementation in `explain/schema.py`.

**Context.** Phase 8 measured a calibration slope of 0.33 for the primary model (1.0 is calibrated) and concluded the output should not be read as a probability. That conclusion lived in a document. Phase 9 re-measured it (0.326) and asked whether lightweight recalibration could fix it.

**Decision.** The output is a **position in a monitored ranking**, and this is enforced in the type rather than asserted in prose:

- `ModelExplanation.score_percentile` exists alongside `score`, because the percentile is the number that means something.
- Every explanation from a model whose calibration slope falls outside [0.8, 1.25] carries a `NOT_CALIBRATED` caveat automatically.
- Metrics quoted for the model are ranking metrics — ROC-AUC, PR-AUC against its base rate, and recall/precision at an alert rate. Brier score and calibration are reported but never as headline.

**Recalibration was investigated and not adopted.** The miscalibration is not a fixable scaling problem: it is driven by unbounded `trend_pct_*` features (ranges to ±42,000) producing a small number of extreme log-odds, and by a base rate that is a property of the sampling design rather than of any real portfolio (D-025 already notes the training base rate does not match a portfolio's). Fitting a Platt or isotonic layer on top would map one arbitrary base rate onto another and manufacture exactly the false precision D-010 exists to prevent.

**Alternatives.**
- **Ship the probability with a warning in the docs.** Rejected: a number in [0, 1] that looks like a probability and is not is the most dangerous shape a risk output can take, and a warning in a separate document does not travel with it.
- **Platt / isotonic recalibration.** Rejected for now, for the reasons above. Reconsider once the extreme-value problem in `trend_pct_*` is fixed and the negative universe reflects a real population — at that point calibration would be measuring something.
- **Report deciles only, discarding the score.** Rejected: the continuous score is needed for alert-rate analysis and for ordering within a decile. Both are kept; the caveat governs how they may be read.

**Consequences.** An analyst-facing phase can say "this company is in the top 2% of the monitored ranking this quarter" and cannot say "this company has a 72% chance of bankruptcy" without removing a caveat the schema attaches by default.

## D-034 Gradient boosting becomes the primary model (supersedes D-028's choice)
**Status:** Accepted (project owner challenge, Phase 10, 2026-09-18) — supersedes the *model-family choice* in [D-028](#d-028-model-family-regularised-logistic-hazard-as-primary-gradient-boosting-as-comparator); measurement in `scripts/phase10_primary_model.py`, results in `data/processed/phase10/primary_model_review.json`.

**Context.** The project owner asked the obvious question: *if gradient boosting wins every metric, why is logistic regression still primary?* D-028 gave four reasons, and re-reading them, only two were claims about the data:

- **(a)** boosting's lead is largest exactly where the cohort confound is largest, so it is the *less* trustworthy of the two;
- **(b)** boosting's dominant feature is `log_total_assets`, which is the confound's own marker.

Reason **(c)** — that only the logistic model's coefficients are readable — had already been overtaken by Phase 9: `explain/adapters.py` gives the boosting model exact TreeSHAP contributions in the same `ModelExplanation` schema ([D-029](#d-029-explanations-are-a-domain-schema-not-an-attribution-librarys-output), [D-030](#d-030-attribution-method-is-chosen-per-model-family-shap-is-not-used-on-the-linear-model)), so both families are equally explainable to Phases 12–14. Reason **(d)**, that the simpler model is easier to defend line by line, is a preference, not evidence.

Neither (a) nor (b) had been tested. Both are cheap to test on the panel that already exists, and D-028 itself named the test ("the within-cohort gap is the strongest argument for revisiting that choice"). So it was run.

**What the measurement found.** Walk-forward out-of-time throughout, paired bootstrap on the difference ([D-027](#d-027-evaluation-is-walk-forward-out-of-time-not-a-single-holdout)), company-clustered. "Size-blind" removes the `scale` feature family (`log_total_assets`, `log_revenue`) from both models and changes nothing else.

| Population | logistic | boosting | boosting − logistic (95% CI) |
|---|---:|---:|---|
| Pooled | 0.803 | 0.887 | **+0.084 [0.050, 0.118]** |
| Pooled, size-blind | 0.803 | 0.860 | **+0.058 [0.019, 0.096]** |
| Within event cohort | 0.733 | 0.787 | **+0.054 [0.016, 0.091]** |
| Within event cohort, size-blind | 0.732 | 0.776 | **+0.044 [0.008, 0.080]** |

Every interval excludes zero. The cost to boosting of losing the size features is −0.027 [−0.044, −0.009] pooled but only −0.011 [−0.023, +0.003] within the event cohort — **not distinguishable from zero in the frame where the confound is neutralised.**

Permutation importance *inside the event cohort* settles reason (b) outright, and reverses it. Boosting's leading features there are `ratio_liabilities_to_assets` (23%), `ebit_to_assets` (23%) and `ratio_current_ratio` (10%) — leverage, profitability, liquidity. `log_total_assets` and `log_revenue` are fifth and sixth at ~5% each. The **logistic** model's leading features in the same frame are `max_deterioration_persistence`, then `ratio_ocf_to_revenue__missing`, `ratio_gross_margin__missing` and `log_total_assets__missing`: three of its top seven are missingness indicators. On the confound-free population it is the *linear* model whose top drivers are data-availability artefacts, which is the objection D-028 raised against boosting.

Reason (a) survives in direction but not in force: the gap does narrow as the confound is removed (0.084 → 0.054), and boosting's cohort separability is still higher (0.913 vs 0.792; size-blind 0.880 vs 0.780). That is a real reason to keep refusing to quote *pooled* boosting numbers as credit discrimination. It is not a reason to ship the weaker model.

**Decision.** **`gradient_boosting_all` is the primary model.** The logistic model is retained — as the measured comparator, as the source of every "primary model" figure in [predictive_model.md](predictive_model.md) and [model_evaluation_explainability.md](model_evaluation_explainability.md), and because a decision that erases its own predecessor cannot be audited. Both artifacts sit in `data/processed/phase8/artifacts/`.

Nothing about either model is retuned by this decision. The shipped estimator is the existing `build_model_specs()` entry, refit on all usable history, only re-designated — so the numbers above remain the numbers that describe it.

**The promotion exposed a defect, which is fixed here rather than inherited.** [D-033](#d-033-the-model-output-is-a-ranking-and-the-schema-says-so) gave two *independent* reasons the output is a ranking and not a probability: the calibration slope, and a training base rate that is a property of the sampling design rather than of any portfolio. Only the first was implemented, and it was implemented as the gate on both — `local.py` attached `NOT_CALIBRATED` when the slope fell outside [0.8, 1.25]. The boosting model's slope is **0.81**, inside that band, so promoting it would have silently dropped *both* reasons. A new caveat code `BASE_RATE_NOT_PORTFOLIO` now fires unconditionally on this corpus, independent of any slope, with `tests/test_explain_local.py::test_an_acceptable_slope_does_not_remove_the_base_rate_caveat` pinning the reason.

**Alternatives.**
- **Keep logistic primary.** Rejected: on the one population where the confound cannot operate, boosting is better by an interval excluding zero, is better with size removed, and leans on financial ratios where logistic leans on missingness. Every surviving argument for logistic was about convenience of exposition, and Phase 9 removed even that.
- **Ship both as co-primary.** Rejected: two primaries is no primary. Phases 11–14 need one number to combine, contradict and display; the comparator stays measured and reported, which is what it is for.
- **Wait until the eligibility-matched cohort exists ([D-032](#d-032-the-negative-universe-becomes-point-in-time--and-that-is-not-the-confound)).** Rejected: the within-cohort frame already neutralises the confound for the purpose of *choosing between two models*, and deferring a decision the data supports, for data that does not exist yet, is how a wrong default survives.

**Consequences.** Phase 9's explanation path for the primary model is now TreeSHAP rather than the exact linear decomposition — **which does not weaken [D-030](#d-030-attribution-method-is-chosen-per-model-family-shap-is-not-used-on-the-linear-model), it activates its other branch.** D-030's finding was that SHAP is unnecessary *for a linear model*, and that a tree ensemble is the one case in this project where it is the only correct tool; that remains exactly true, and `shap` moves from an optional dependency exercised only by a challenger to a load-bearing one. `AttributionResult.reconstruction_error` still guards the decomposition, and `UNSTABLE_ATTRIBUTION` still fires if TreeSHAP fails to reconstruct a score. The narrative claims in Phase 8/9 that rest on the logistic model's *coefficients* (e.g. "`n_deteriorating_ratios` +0.60") are now claims about the comparator, and are labelled as such wherever they appear.

## D-035 Narrative signals are gated on assertion, not on keywords
**Status:** Accepted (delegated to engineering judgement, Phase 10, 2026-09-18) — implementation in `nlp/assertion.py`, catalog in `nlp/catalog.py`, measurements in [nlp_risk_signals.md](nlp_risk_signals.md).

**Context.** Phase 10 produces risk signals from 10-K narrative text with verbatim evidence (FR-14, SC-03). [A-15](assumptions.md) commits the project to "rules plus classical NLP first", so the obvious implementation is a keyword or phrase matcher over Item 1A and Item 7.

**That implementation does not work, and the reason is structural rather than fixable by better keywords.** Item 1A's statutory purpose is to enumerate everything that could go wrong, so every 10-K ever filed discusses default, covenant breach, liquidity exhaustion and bankruptcy — in the conditional. Measured on the Phase 4 golden set before any gating: Apple's risk factors discuss default; Coca-Cola's discuss liquidity. Neither company is in any difficulty. A matcher that reports these fires on essentially every filing, and a signal that fires on everything carries no information.

**Decision.** Every match is classified into one of four **assertion** classes before it is emitted, and the shipped default emits only two of them:

| Class | Meaning | Emitted by default |
|---|---|---|
| `ASSERTED` | the filer states this about itself | ✅ |
| `NEGATED` | the filer explicitly denies it ("no event of default has occurred") | ✅ |
| `HYPOTHETICAL` | conditional or modal — the bulk of Item 1A | ❌ (available on request) |
| `CROSS_REFERENCE` | a pointer ("see Note 1"), which asserts nothing | ❌ (available on request) |

Three properties of the design are load-bearing:

- **Each cue class gets the scope its grammar has.** An attached denial is looked for in the ~14 characters before the trigger; conditionals, compliance denials and factual overrides in the preceding clause; modals across the whole sentence. This is not tuning: a conditional governs what follows it, so it precedes the trigger, while the modal governing a trigger in *subject* position follows it. Walmart's "Any downgrade of our credit ratings could increase our future borrowing costs" was read as an asserted downgrade under a backward-only rule, because the only thing before the trigger is the word "any".
- **Polarity cannot be decided by proximity.** "we were not in compliance" is a breach and "we were not in default" is a denial; both contain "were not". The difference is that the catalog's breach pattern is `not in compliance`, so the negative is *inside* the trigger in one case and outside it in the other — which adjacency distinguishes and a sentence-wide negation search cannot.
- **Gated is not discarded.** `HYPOTHETICAL` matches are withheld, not dropped, because "this filer's risk factors newly discuss covenant breach" is a weaker signal rather than a non-signal, and Phase 11 may want it. `NEGATED` is emitted by default because an explicit statement of covenant compliance is itself worth putting in front of an analyst — SandRidge's FY2015 10-K affirms compliance with its note covenants two months before its petition, while disclosing a covenant violation elsewhere in the same filing.

**Alternatives.**
- **Keyword or phrase counting ("risk vocabulary density").** Rejected: it mostly measures how long the risk factors are, and it is the composite-score-with-uninspectable-inputs pattern this project already refuses ([D-022](#d-022-phase-7-financial-health-design-economic-direction-no-composite-score-mixed-status), [D-010](#d-010-ml-output-is-not-called-a-probability-of-default)).
- **A supervised sentence classifier.** Rejected for this phase, and not on dogma: there is no labelled corpus to train one on, building one is the larger part of the work either way, and a classifier cannot tell an analyst *which rule* fired — where a false positive here traces to one `pattern_id` and is fixed by editing one line. Reconsider once the hand-labelled set is large enough to be training data rather than only evaluation data.
- **An LLM per sentence.** Rejected: tens of thousands of sentences per filing at one call each contradicts the cost NFR (one LLM call per assessment), and it would make a deterministic, reproducible layer non-reproducible. Phase 12's single grounded call is where the LLM belongs.
- **Emitting everything and letting Phase 11 filter.** Rejected: the mood classification needs the sentence, which Phase 11 does not have. Doing it here and passing the class forward gives Phase 11 strictly more information at no cost.

**Consequences.** The measured effect of the gate, the per-signal precision, and each signal's rate in pre-bankruptcy versus comparison filings are in [nlp_risk_signals.md](nlp_risk_signals.md); the catalog's `Specificity` values are set from those rates rather than from intuition. Two false positives found during development were **word-boundary** failures rather than mood failures — "on*going concern*" in Coca-Cola's risk factors, and "conse*cut*ive quarterly dividend" in Pfizer's, the latter turning a 349th consecutive dividend into a dividend cut — and both are pinned as regression tests, because they are exactly the kind of decoy nobody invents while writing the pattern.

## D-036 Phase 11 produces an evidence package, not a combined score
**Status:** Accepted (delegated to engineering judgement, Phase 11, 2026-09-19) — implementation in `assessment/`, measurement in [combined_assessment.md §6](combined_assessment.md).

**Context.** Four layers now analyse a company and none of them share a type. The phase brief is "combine the analytical outputs", and the obvious build is a weighted combination producing one risk number for Phases 12–14 to display.

**Decision.** There is no combined score. Phase 11 emits an `Assessment`: an addressable evidence register, explicit contradictions ([D-038](#d-038-disagreement-is-an-output-and-no-rule-adjudicates-it)), explicit corroborations, and a record of which layers did not speak and why. `Assessment` has no overall status field.

The refusal is consistent with [D-010](#d-010-ml-output-is-not-called-a-probability-of-default), [D-022](#d-022-phase-7-financial-health-design-economic-direction-no-composite-score-mixed-status) and [D-033](#d-033-the-model-output-is-a-ranking-and-the-schema-says-so), but consistency is the weaker half of the argument. The stronger half is what a composite here would be made of: a measured ranking metric, a threshold-driven trend label and a regex hit, averaged into one uninspectable digit that would then be the only thing anyone read.

**And the measurement says the composite would not even have paid.** The phase tested its own product claim rather than assuming it — at a matched alert budget, is a list built from agreement between layers better than the model's own top k? Company-clustered paired bootstrap on 202 labelled filings:

| Selector | k | precision | model top-k | Δ (95% CI) |
|---|---:|---:|---:|---|
| `ALL_LAYERS_ELEVATED` | 43 | 0.930 | 0.930 | **+0.000 [−0.082, +0.098]** |
| `MODEL_AND_NARRATIVE` | 38 | 0.947 | 0.921 | +0.026 [−0.056, +0.122] |
| `MODEL_AND_HEALTH` | 153 | 0.601 | 0.634 | −0.033 [−0.065, 0.000] |
| `HEALTH_AND_NARRATIVE` | 81 | 0.679 | 0.877 | **−0.198 [−0.306, −0.074]** |
| Narrative layer alone | 80 | 0.675 | 0.875 | **−0.200 [−0.307, −0.082]** |

Every interval contains zero or is negative. Three-layer agreement fires on 40 of 100 pre-bankruptcy filings and 3 of 102 comparison filings — a lift of 13.6 read in isolation, and *exactly the precision of the model's own top 43* read against the budget it spends. Combining does not improve the ranking.

**Alternatives.**
- **A weighted composite, calibrated on the corpus.** Rejected on the measurement above: there is nothing for the weights to buy. Fitting them anyway would produce a number whose only property is that it was fitted.
- **Rank by the count of agreeing layers.** Rejected as the same thing with fewer digits, and it inherits [D-022](#d-022-phase-7-financial-health-design-economic-direction-no-composite-score-mixed-status)'s objection directly: three layers agreeing on a low-specificity impairment is not two layers agreeing on going-concern doubt.
- **Emit the layers side by side with no relationship at all.** Rejected: that is what Phases 7–10 already produce, and it leaves FR-15 unbuilt and Phase 12 with nothing to cite.

**Consequences.** The phase's value is relocated, honestly, from discrimination to the three things §7 of the doc guarantees: every finding's citations resolve, every quote survives the boundary verbatim, and every assessment is reproducible as of its date. Those are what Phases 12 and 13 are built on. One result does survive on the discrimination side and is reported as the narrow claim it is: `ALL_LAYERS_ELEVATED` overlaps the model's top 43 by only 0.63, so it is an independently constructed list of equal quality — different, not better.

## D-037 Evidence is content-addressed, and identity is a separate key
**Status:** Accepted (delegated to engineering judgement, Phase 11, 2026-09-19) — implementation in `assessment/evidence.py` and `assessment/change.py`.

**Context.** Phase 12 makes one grounded LLM call whose draft cites evidence, FR-17 requires *code* to reject a citation that does not exist, and Phase 13 stores the draft immutably. Something has to name the facts.

**Decision.** `evidence_id` is `EV-<kind tag>-<blake2s of the item's content>`; `identity_key` is the same item's subject with no values and no period. Both are on every `EvidenceItem`.

A positional or counter ID fails in a specific, silent way: re-running the pipeline after a data fix could repoint a stored citation at a different fact, and the stored draft would still validate while now being wrong. A content hash cannot — change a cited value and the ID changes, the stored citation fails validation, and the failure is visible. Float inputs are formatted to four significant figures before hashing, never through `repr`, so an ID is identical on every machine.

The cost is that content hashes are useless for FR-11's "is this the same signal as last quarter?", since a deteriorating company shares almost no IDs between periods. Hence the second key, and hence `compare()` diffs on `identity_key` while citations stay pinned to content. That split is what makes `CHANGED` — same subject, worse number — expressible at all; a set difference over IDs can only produce appeared and gone.

**Alternatives.**
- **One key for both.** Rejected: the two jobs have opposite requirements. A key that is stable across value changes cannot detect them, and a key that detects them cannot track a subject.
- **Let Phase 12 quote facts inline instead of citing IDs.** Rejected: that is the design where a hallucinated figure is indistinguishable from a real one, which is exactly what FR-17 exists to prevent.
- **A UUID assigned at registration.** Rejected: it makes a re-run produce a different register for identical inputs, which breaks both reproducibility and the stored-draft guarantee.

**Consequences.** `Assessment.validate_citations` and `known_numbers()` live in Phase 11 rather than Phase 12, because the check belongs with the thing it checks. Measured over 202 assessments: 0 unresolved citations, and evidence IDs identical on independent re-assembly. `EvidenceItem.numbers` carries every figure a summary states as a float, so a drafted number can be checked without parsing English.

## D-038 Disagreement is an output, and no rule adjudicates it
**Status:** Accepted (delegated to engineering judgement, Phase 11, 2026-09-19) — implementation in `assessment/contradictions.py`, rates in [combined_assessment.md §6.3](combined_assessment.md).

**Context.** FR-15 asks for contradictions between components to be detected by explicit rules and listed. The two live questions are what counts as a contradiction and what the product does with one.

**Decision, part 1 — seven named rules, no similarity metric.** Each is a testable condition over cited evidence. A learned disagreement detector, or a threshold on a distance between layer outputs, would be a second opaque model on top of the first, and a contradiction an analyst cannot check is worse than none.

**Decision, part 2 — a finding names both sides and stops.** No rule says which side is right. This is not modesty: in each case the information needed to decide is genuinely absent from the assessment. `resolution_hint` names the next thing to check, which is an action rather than an answer.

**Part 2 was then vindicated by the measurement, against my own draft.** `NARRATIVE_SEVERE_MODEL_QUIET`'s first hint told the analyst to treat the model as the weaker side, on the reasoning that a filer's verbatim words outrank a fitted score. Measured, the rule fired on **11 comparison filings and 1 pre-bankruptcy filing** — lift 0.09. The hint now states the measurement. Had the rule adjudicated in the schema rather than hinting in prose, that error would have been unfixable without a migration.

**What the rules are worth, measured on 202 filings:**

| Contradiction | pre-bankruptcy | comparison | lift |
|---|---:|---:|---:|
| `NARRATIVE_SELF_CONTRADICTION` | 16.0% | 7.8% | **2.04** |
| `ABSENCE_NOT_OBSERVED` | 28.0% | 18.6% | 1.50 |
| `DIMENSION_DISAGREEMENT` | 37.0% | 63.7% | 0.58 |
| `NARRATIVE_SEVERE_MODEL_QUIET` | 1.0% | 10.8% | 0.09 |
| `MODEL_ELEVATED_HEALTH_QUIET`, `NARRATIVE_SEVERE_HEALTH_QUIET`, `SCORE_NOT_EVIDENCE_BACKED` | 0.0% | 0.0% | — |

`NARRATIVE_SELF_CONTRADICTION` is the phase's one positive discrimination result and the only thing here no single layer can produce: a filing that both asserts and denies the same condition is twice as likely to precede a petition. It exists only because [D-035](#d-035-narrative-signals-are-gated-on-assertion-not-on-keywords) kept `NEGATED` rather than dropping it — without the mood classification both sentences are just covenant language.

**`SCORE_NOT_EVIDENCE_BACKED` was rewritten mid-phase and the reason is a result.** Its first version read `ModelExplanation.missingness_share`, the 44% pathology Phase 9 measured on the logistic model. That field is *structurally* zero for the gradient-boosting model [D-034](#d-034-gradient-boosting-becomes-the-primary-model-supersedes-d-028s-choice) promoted, which handles absent values natively rather than through `__missing` columns — so the rule could only ever have fired on the retired comparator. Rewritten against the `missingness` and `data_quality` attribution groups, the primary model's share has a median of 0.004 and a 99th percentile of 0.029. **D-034's promotion removed the missingness pathology rather than inheriting it**, which D-034 itself did not claim.

**Alternatives.**
- **Resolve contradictions into a single adjudicated view.** Rejected on the evidence above: my one attempt to adjudicate in prose was wrong by a factor of ten in the wrong direction.
- **Suppress rules that fire too often.** Rejected for `DIMENSION_DISAGREEMENT` (102 of 202) in favour of reporting the rate: part of its noise traces to the reconstructed health layer ([combined_assessment.md §5](combined_assessment.md)), and deleting a rule to make a table look better is how a measurement becomes decoration.
- **Drop the three rules that never fired.** Rejected: two cannot fire on a corpus where 87% of filings have a deteriorating dimension, which is a property of this corpus and not of the rules, and the third is a standing guard whose passing is itself the reported finding.

**Consequences.** Phase 12 must render `contradictions` and `layers_absent`; a synthesis that omits a disagreement, or reads a missing layer as a calm one, is the failure this phase exists to prevent. Phase 13's reviewer sees both sides of every disagreement and is the one who decides, which is [D-003](#d-003-analyst-owns-every-final-judgement) reaching the place it was always headed.

## D-039 The as-of gate runs over assembled evidence, and fails closed
**Status:** Accepted (delegated to engineering judgement, Phase 11, 2026-09-19) — implementation in `assessment/asof.py`; FR-05.

**Context.** FR-05 requires an assessment to be runnable as of a chosen date using only filings available then. [D-008](#d-008-point-in-time-as-filed-data-rule) established the rule and [D-026](#d-026-the-observation-unit-is-a-filing-and-the-cutoff-is-its-receipt-date) enforced it inside the training panel with three layers of checks. Phase 11 is the first place a *user* picks the date.

**Decision, part 1 — the gate runs at the bottom, not at the caller.** The tempting shape is "filter the filings before you start", and it is the shape that fails: by the time four layers have each fetched what they need, the assessment holds a model explanation with a prediction date, a narrative report with an accession, and a health report built from a window nobody kept a list of. A filter at the top cannot see any of that. `AsOfGate.verify` walks the assembled evidence and asks every item for its filing date, so a layer that over-fetched is caught by the assessment it produced rather than by its caller's discipline.

This is also why `assemble_assessment` requires a `FilingStamp` whenever a health report is supplied: a Phase 7 report spans several filings and belongs to none, so it cannot say when it became knowable, and without the stamp the gate would have to wave every health item through while appearing to check everything.

**Decision, part 2 — undated evidence is rejected, not admitted.** An item with no provenance is precisely the shape leakage takes. A gate that admits it guarantees only the filings it happened to be able to see.

**Decision, part 3 — the comparison is against the filing date, never the fiscal period end.** FY2014 figures are not public on 2014-12-31; a backtest keyed on the period end reads the future by a quarter.

**Measured, not asserted.** All 202 assessments in the phase corpus were re-assembled one day before their filing date and **all 202 were refused**. The gate also caught a leak in this phase's own test fixture before it could reach anything else: the first draft stamped a 2014 assessment with a 2015 filing date, which is exactly the error the gate exists for, appearing in the test that was meant to exercise it.

**Alternatives.**
- **Trust the callers and document the rule.** Rejected: that is the arrangement that produced the survivorship problem [D-032](#d-032-the-negative-universe-becomes-point-in-time) had to measure its way out of, one layer up.
- **Filter silently instead of raising.** Rejected for the assembly path — dropping an item there would hide a layer that over-fetched. `AsOfGate.admissible` exists for callers replaying from a cached superset, and is documented as not what the assembly uses.
- **Admit undated evidence with a caveat.** Rejected: a caveat on an item that might be from the future is not a point-in-time guarantee, it is a note attached to the absence of one.

**Consequences.** FR-05 is a guarantee rather than a convention, and every stored assessment is auditable after the fact. A new evidence kind must carry its filing date to pass the gate, which is the requirement rather than an inconvenience.

## D-040 The synthesis deliverable is the verdict on the draft, not the draft
**Status:** Accepted (delegated to engineering judgement, Phase 12, 2026-09-19) — implementation in `synthesis/validator.py`, measurement in [grounded_synthesis.md §5](grounded_synthesis.md).

**Context.** FR-16 asks for one grounded LLM call producing a structured draft; FR-17 asks that claims citing non-existent evidence IDs, or containing numbers not present in the evidence, are detected by code. Read as a build order, that is "write the call, then add validation".

**Decision.** The order is reversed and the emphasis with it. The call is four lines in `engine.py`; the validator is the largest module in the package, imports no provider SDK, needs no network, and is what the phase is measured on. An LLM writes the sentences and is not trusted to have written true ones.

The reason is that this is the one place in the pipeline where everything underneath can be silently undone. A paraphrased quotation destroys Phase 10's SC-03. A percentile rounded into a different number destroys Phase 9's provenance chain. "A 72% probability of default" destroys [D-010](#d-010-ml-output-is-not-called-a-probability-of-default). None of those failures is visible in the output — they all read as fluent prose — so the only defence is a check that runs on every draft and does not depend on the prose being reasonable.

**Two consequences shaped the schema.**

- **The draft is a list of typed claims, not a paragraph.** A paragraph cannot be validated: three assertions resting on different evidence share one citation list, which attaches to none of them in particular. Each `Claim` carries its own `evidence_ids` and is checked alone.
- **Claim kinds are required rather than inferred.** Two of the eight checks are about *completeness* — did the draft describe a contradiction, did it declare an absent layer — and code can ask that only if attempting one is a typed thing rather than a stylistic one.

**Measured by fault injection, because that is the only honest way to measure a validator.** A live model returns whatever it produced that day: if it behaves you learn nothing about what the validator catches. So a reference draft is built for each of 176 assessments — grounded by construction, and deliberately doing what breaks a naive validator — then broken in seven named ways.

| | Result |
|---|---|
| **False positives** (correct drafts rejected) | **0 of 176 — 0.000** |
| `fabricated_citation`, `dropped_citation`, `reworded_quote`, `probability_claim`, `omitted_contradiction`, `miscited_number` | **100% detected** |
| `fabricated_number` | 100% detected; 99.4% as a rejection, 1 of 176 downgraded to a flag by colliding with a different real value |

**The false-positive rate was not zero on the first run, and the defect is the record's point.** A correct draft for *21st Century Oncology Holdings, Inc.* was rejected because the `21` in the company's own name parsed as an unsupported numeric assertion. Identity — name, CIK, as-of date, fiscal period — is not measurement, and now grounds every claim. The fix widened what counts as identity, not what counts as grounded, and the regression test asserts a genuinely absent number in the same sentence is still caught.

**Alternatives.**
- **Ask a second LLM to check the first.** Rejected: it reintroduces exactly the ungrounded step the phase exists to remove, doubles the cost NFR, and produces a check that cannot be audited line by line or regression-tested.
- **Validate a prose draft with heuristics over sentences.** Rejected: sentence splitting is the least reliable part of the pipeline (Phase 10 built a segmenter and measured its limits), and a validator whose first step can fail is a validator that reports on itself.
- **Trust the system prompt.** Rejected, though the prompt states every rule anyway: an instruction makes a compliant draft likely and a validator makes a non-compliant one *detected*. Neither substitutes for the other.

**Consequences.** Phase 13 receives a `SynthesisResult` carrying the draft, the verdict and every finding, and must render rejections and flags differently. The validator's largest hole is stated rather than patched: it does not check whether a claim is *true* given its evidence — "leverage is improving" citing a deteriorating-leverage item passes every check. The only tools for that judgement are another model or the analyst, and [D-003](#d-003-analyst-owns-every-final-judgement) already assigns it to the analyst.

## D-041 A number's precision comes from the claim, not from a tolerance constant
**Status:** Accepted (delegated to engineering judgement, Phase 12, 2026-09-19) — implementation in `synthesis/numbers.py`; sensitivity measured in [grounded_synthesis.md §5.3](grounded_synthesis.md).

**Context.** FR-17's "numbers not present in the evidence" reads like a set membership test and is not one. The evidence holds `97.8312`; a competent draft writes "the 97.8th percentile". Exact matching rejects every correct draft. A fixed epsilon either rejects honest rounding or accepts a fabrication that lands nearby, and its value would be arbitrary.

**Decision.** The admissible gap is **half a unit in the last place the writer chose to state**. A number written to one decimal is checked to one decimal: `97.8` matches `97.8312` and `97.9` does not. `37` matches `37.4` and not `37.6`. `$199.5 million` admits fifty thousand either way, because that is what stating a figure to the hundred-thousand means. No epsilon constant appears anywhere in the module.

Three supporting rules, each present because a real draft needs it:

- **Every reading of a literal is tried, but no value is invented.** `22%` is `22.0` against a percentile field and `0.22` against a rate; `$199.5 million` is `199,500,000` raw and `199.5` in a field already denominated in millions. The layer cannot know which the evidence used, so it offers both scales — never a different magnitude.
- **An unsigned literal carries its sign in the verb.** "fell 0.31" restates a stored `-0.31` correctly. This is the module's **one deliberate permissiveness** and is documented as such: it also grounds "the change was 0.31" against `-0.31`. Rejecting it would fail on ordinary correct prose; the magnitude still has to be real.
- **What the evidence writes as text is quotable as text.** `FY2014`, an accession, "3 of 4 ratios" — facts the summaries state in words that no float records. Checked as strings, so the numeric rule never loosens to reach them. Evidence IDs are masked instead of checked, so a fabricated figure cannot be grounded on the coincidence of an ID's hex tail.

**The boundary was measured, not asserted.** Perturbing a stated number by *k* units in its last stated place, over 176 assessments:

| k | 0.2 | 0.4 | 0.6 | 1.0 | 2.0 | 10.0 |
|---|---:|---:|---:|---:|---:|---:|
| passed | 100% | 100% | — | — | — | — |
| detected | — | — | **100%** | **100%** | **100%** | **100%** |

Nothing below half a unit is flagged; everything above it is. The rule does what it claims, at the point it claims.

**Alternatives.**
- **A relative tolerance (1%, 0.1%).** Rejected: it is a number nobody can justify, and it behaves differently on a current ratio of 1.42 than on a percentile of 97.8 for no reason connected to what either means.
- **Require the draft to restate values at full stored precision.** Rejected: it would produce "the 97.8312th percentile", which is false precision of exactly the kind [D-033](#d-033-the-model-output-is-a-ranking-and-the-schema-says-so) removed, and it would make the prose unreadable.
- **Strip numbers from the draft entirely and render them from evidence.** Rejected: it solves grounding by removing the synthesis, and an analyst reading a note wants the figure in the sentence.

**Consequences.** `EvidenceItem.numbers` — added in Phase 11 for this — is the input, and its four-significant-figure formatting in summaries is compatible with the rule rather than in tension with it. The known collision effect is reported rather than hidden: with ~30 evidence items per assessment, a fabricated value can land on a *different* real one (1 of 176 measured) and is then caught as a mis-citation rather than a fabrication.

## D-042 One call, no repair loop, and a rejected draft is returned
**Status:** Accepted (delegated to engineering judgement, Phase 12, 2026-09-19) — implementation in `synthesis/engine.py` and `synthesis/client.py`.

**Context.** FR-16 allows one grounded call and the cost NFR is one call per assessment. The obvious product improvement is to regenerate when the validator rejects — the model gets the findings and tries again, and the analyst sees a better draft.

**Decision.** `synthesize` makes exactly one call and returns the draft together with its verdict, including when the verdict is a rejection. No retry, no repair loop, no fallback to a cheaper model. `AnthropicSynthesisClient` additionally sets `max_retries=0`, because the SDK's automatic retries would turn one logical call into several billed ones while the accounting still said one.

The reason is not only cost. **A repair loop hides the rejection rate**, and the rejection rate is the number Phase 13's reviewer needs in order to calibrate how much to trust the drafts that passed. A draft that reaches an analyst because the model was asked three times is a draft whose reliability nobody can state. A caller that wants to regenerate may call again, and will be able to see that it did.

Three smaller decisions follow the same logic:

- **Malformed output fails loudly.** `output_config.format` constrains the response to the draft schema, so a parse failure is a real breakage — a provider change, a truncation — and is raised rather than repaired. A best-effort salvage would produce a partial draft that gets validated, possibly accepted, and stored as though the model had written it.
- **`stop_reason` is checked before `content` is read.** A refusal returns HTTP 200 with no usable text; indexing the content first would raise something unrelated to what actually happened.
- **`api_calls` is a field on the result, asserted by a test.** A regression that adds a second call is then visible rather than invisible.

**Alternatives.**
- **Regenerate once on rejection.** Rejected on the visibility argument above, and because it doubles the worst-case cost precisely on the assessments where the model is least reliable.
- **Return only accepted drafts and raise on rejection.** Rejected: the rejected draft and its findings are the most informative artefact the phase produces, and discarding it would make the failure mode unmeasurable.
- **Absorb rate limits with SDK retries.** Rejected: the failure becomes invisible and the cost becomes untrue. The caller is in a better position to decide whether to wait.

**Consequences.** Measured prompt size is 7,798 characters (~1,950 estimated tokens; no tokenizer is available offline, and the assumption is labelled wherever the figure appears), giving roughly **$0.040 per assessment** at Claude Opus 5 list price. The live acceptance rate is not yet known — see [D-043](#d-043-the-model-provider-lives-behind-one-seam-and-the-phase-is-measured-without-it).

## D-043 The model provider lives behind one seam, and the phase is measured without it
**Status:** Accepted (delegated to engineering judgement, Phase 12, 2026-09-19) — implementation in `synthesis/client.py`; `anthropic` is the optional `llm` extra.

**Context.** [Q3](product_requirements.md) left "LLM provider and budget" to Phase 12. The environment this phase was built in has no `anthropic` package, no `ANTHROPIC_API_KEY` and no CLI credential, so no live call could be made.

**Decision.** The provider is confined to `client.py`, behind a `SynthesisClient` protocol with three implementations — the live Anthropic client, a `ScriptedClient` for tests and measurement, and a `RecordingClient` that keeps a live run for free re-analysis. Nothing else in `synthesis/` imports a provider SDK, and `anthropic` is an optional extra.

That is not provider-neutrality as a virtue. It is what made the phase measurable at all: the validator — the deliverable, per [D-040](#d-040-the-synthesis-deliverable-is-the-verdict-on-the-draft-not-the-draft) — is exercised over 176 real assessments with no key, no network, and no dependence on what a model happened to do on the day. A project whose test suite cannot run without a paid API key is a project whose test suite stops being run.

**The gap is recorded rather than papered over.** The number Phase 13 will most want — *how often does a real model produce a draft that passes?* — does not exist yet, and no document in this project implies it does. [A-16](assumptions.md) ("a single structured LLM call can produce a grounded synthesis when given evidence with IDs") **remains open**, with the validator and the live script both in place, so the measurement is one command and one key away. `scripts/phase12_synthesize.py` writes every draft, verdict and usage figure to disk so a later change to the validator can be re-measured against the same drafts without paying twice.

Model choice, when the key exists: **`claude-opus-5`**, with the response constrained by JSON Schema and a cache breakpoint on the stable system prefix. Whether that prefix clears the model's minimum cacheable length is **not claimed** — the result records `cache_read_input_tokens` and the live script reports what was actually measured.

**Alternatives.**
- **Block the phase until a key is available.** Rejected: it would have left the validator unwritten and unmeasured, which is the part that does not depend on a provider and the part everything downstream rests on.
- **Stub the model with a deterministic generator and call it done.** Rejected as the more tempting error. A deterministic "synthesizer" would be a second, competing implementation of the phase, and measuring the validator against its own generator would be circular. The reference drafts in the measurement script are explicitly *test fixtures* and live in `scripts/`, never in the package.
- **Write provider-agnostic code against a generic LLM interface.** Rejected: an abstraction over providers that have never both been used is an abstraction fitted to one of them anyway. One seam, one implementation, and a protocol narrow enough to add a second later.

**Consequences.** `pyproject.toml` gains an `llm` extra. The test suite runs with no credentials. Phase 13 may assume a `SynthesisResult` exists but may not assume it was accepted. **Amended by [D-044](#d-044-a-second-provider-and-the-prompt-leaves-the-vendors-envelope):** a Gemini credential arrived, a second client was added behind the same seam, and the live measurement this entry deferred was taken — so the claim here that no live call has been made is superseded, while the reasoning that the phase had to be measurable without one stands.

## D-044 A second provider, and the prompt leaves the vendor's envelope
**Status:** Accepted (project owner supplied a credential, Phase 12, 2026-09-19) — extends [D-043](#d-043-the-model-provider-lives-behind-one-seam-and-the-phase-is-measured-without-it); implementation in `synthesis/prompt.py` and `synthesis/client.py`, results in [grounded_synthesis.md §8](grounded_synthesis.md).

**Context.** [D-043](#d-043-the-model-provider-lives-behind-one-seam-and-the-phase-is-measured-without-it) confined the provider to one module and recorded that no live call had been made, leaving [A-16](assumptions.md) open. The project owner then supplied a **Gemini** key, not an Anthropic one. The existing client could not use it, and the phase's standing gap could be closed only by adding a second implementation.

**Decision, part 1 — the prompt stops being an Anthropic request.** `build_request` returned a Messages API dict, on the reasoning D-043 itself gave: an abstraction over one implementation is fitted to that implementation anyway. A second provider showed what that cost. The instructions, the evidence pack and the output schema are the things *this project* owns and versions; burying them in one vendor's envelope made `request_fingerprint` — which Phase 13 needs to prove a stored draft came from a stored assessment — permanently vendor-flavoured.

So `prompt.SynthesisRequest` now carries `system`, `user`, `schema`, `max_tokens` and **no model**: which model runs a prompt is a property of the client, and including it would make two providers fingerprint the same prompt differently. Each client renders the request into its own wire format, and `render_anthropic` was lifted to a module-level function so the wire shape is testable without the SDK installed.

**Decision, part 2 — keep both clients.** `GeminiSynthesisClient` joins `AnthropicSynthesisClient` behind the same protocol. Two providers on the same assessment, the same prompt and the same validator is a stronger statement about the grounding layer than either alone, and the neutral request makes that comparison exact rather than approximate.

**Decision, part 3 — provider errors become `SynthesisError`.** The first live batch died on a `429` from the SDK's own exception type, taking the whole run with it. Translated at the seam, a quota refusal on one company is one recorded failure instead of a dead batch. This does **not** weaken [D-042](#d-042-one-call-no-repair-loop-and-a-rejected-draft-is-returned): nothing is retried, the failure is surfaced, and the caller still decides.

**What the live run found.** `gemini-3.6-flash`, 120 assessments attempted, **12 drafts returned, 11 accepted (91.7%)**, 108 calls refused on free-tier quota. Pro-tier models report a quota of *zero* on a free credential, so the default model is the most capable one an ordinary key can reach — a deployment fact, not a quality judgement.

**The single rejection is the most useful result in the phase.** Drafting for GT Advanced Technologies, the model produced a quotation it had been told to copy character for character:

```text
model:  ...could have a further adverse effect on     share price.
filing: ...could have a further adverse effect on our share price.
```

It cited the correct evidence item and reproduced 195 characters exactly before dropping the word *our*. The draft reads as clean and well-sourced. That is exactly the invisible failure [D-040](#d-040-the-synthesis-deliverable-is-the-verdict-on-the-draft-not-the-draft) was built against — Phase 10's SC-03 guarantees the stored quote is verbatim, and one word removed downstream would have carried a misquotation into an analyst-facing draft. **The validator caught it on the first live batch, at n=12.**

**Two things this does not establish.** Twelve drafts put a 95% interval on the acceptance rate of roughly 62%–100%; it shows the pipeline works end to end and that the validator fires on real output, and it is not a reliability figure. And prompt caching **did not engage** — `cached_content_token_count` was zero on every call — so §6's refusal to claim a saving stands as measured rather than as caution.

**Alternatives.**
- **Translate the Anthropic dict inside the Gemini client.** Rejected: it would have shipped faster and left the fingerprint vendor-flavoured forever, which is the one property Phase 13 cannot work around.
- **Replace the Anthropic client with the Gemini one.** Rejected: the Anthropic path is written, tested and is the better-documented of the two; deleting it to match today's credential would discard a comparator for a reason that expires when a key arrives.
- **Retry the 429s to reach a larger sample.** Rejected: it contradicts [D-042](#d-042-one-call-no-repair-loop-and-a-rejected-draft-is-returned)'s accounting and would have bought a bigger number by making it less meaningful. Pacing *between* assessments was added instead, which is waiting before a first attempt rather than making a second one.

**Consequences.** [A-16](assumptions.md) moves from open to **partially validated**: a single structured call over an evidence pack does produce a grounded synthesis, measured once, at small n. `pyproject.toml`'s `llm` extra carries both SDKs. Two operational lessons were paid for and fixed: `--limit` now bounds *attempts* as well as successes, after a run with a dead credential walked all 202 assessments producing identical quota errors; and the script refuses to overwrite an output file that already holds drafts, after a paced re-run destroyed the only live measurement this phase had ([grounded_synthesis.md §8.4](grounded_synthesis.md)).
