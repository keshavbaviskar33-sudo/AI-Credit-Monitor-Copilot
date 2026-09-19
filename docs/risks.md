# Risk Register — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | Living — opened in Phase 1, reviewed at every phase gate, last revised in Phase 19. R-11 and R-19 are closed by measurement; R-13 is **open and was never mitigated**; the rest stand |
| **Date** | 2026-09-19 (created 2026-09-13) |
| **Related** | [assumptions.md](assumptions.md) · [data_feasibility.md](data_feasibility.md) · [measured_results.md](measured_results.md) · [decision_log.md](decision_log.md) |

> **Owner-phase columns below still name phases 15, 16 and 18.**
> [D-045](decision_log.md) merged 15 into 13, cut 16, and merged 18 into 14,
> and phase numbers are never reassigned, so the columns are annotated in place
> rather than rewritten.

**Impact / likelihood:** H = high · M = medium · L = low. Reviewed at the end of every phase.

## Top risks

| ID | Risk | Impact | Likelihood | Mitigation | Owner phase |
|---|---|---|---|---|---|
| R-01 | **Training data does not match the product** — wrong geography, company types, variable definitions or label meaning; the model learns something other than what the UI implies | H | H | Phase 3 decision gate; data dictionary; model card states population and label; applicability warnings at inference | 3, 8, 9 |
| R-02 | **Training/serving skew** — features in training data (e.g. from a commercial database) are defined differently from features computed from SEC XBRL | H | H | Feature-by-feature mapping; prefer a dataset built from the same source used at inference; measure distribution differences | 3, 5, 8 |
| R-03 | **Point-in-time leakage** — later restatements or later-filed comparatives used in training or historical replay | H | M | Select facts by filing date ≤ as-of date; first-reported values; dedicated tests (SC-07) | 3, 5, 8 |
| R-04 | **Temporal leakage in evaluation** — random splits mixing years of the same company inflate metrics | H | H | Out-of-time splits; group by company; report against a transparent baseline. (Public notebooks claiming near-perfect accuracy on bankruptcy datasets are a warning sign of exactly this.) | 8, 9 |
| R-05 | **Rare, late labels** — bankruptcy events are few and occur after deterioration is obvious | M | H | PR-AUC and calibration rather than accuracy; confidence intervals; frame output as one input among several | 3, 9 |
| R-06 | **Automation bias** — analysts approve fluent AI drafts without scrutiny | H | M | Draft labelling; contradictions next to review controls; no default action; mandatory comments on modify/reject | 13, 14 |
| R-07 | **Ungrounded LLM output** — invented numbers, sources or causes | H | M→**L** | ✅ **Mitigated and measured (Phase 12).** Eight grounding checks over a typed claim schema; fault injection on 176 real assessments gives a **0.000 false-positive rate and 100% detection across seven fault classes**, and the validator caught a real misquotation on the first live batch ([D-040](decision_log.md), [grounded_synthesis.md](grounded_synthesis.md)). Residual: the validator does not check whether a claim is *true* given its evidence — that is the analyst's, per [D-003](decision_log.md) | 12, ~~17~~ |
| R-08 | **Prompt injection via documents** — filing or uploaded text containing instructions to the LLM | M | L–M | Treat document text as data; delimit evidence; no tools/actions available to the LLM; output schema validation | 10, 12 |
| R-09 | **Extraction errors propagate silently** — wrong unit (thousands vs. millions), sign or column | H | M→**M-L** | Phase 4 built the "never silent" half: every located unit carries provenance and anything not extracted is an explicit `ExtractionError` ([extraction.md](extraction.md)). **Phase 5 adds the financial half:** only USD facts are accepted and values stay in whole dollars; the sign convention is explicit and checked (0 violations on the golden set); `balance_sheet_equation` (12/12 independent, circular checks suppressed) and `cash_tie_out` (20/21); QM-01 97.2% ([canonical_schema.md §8, §12, §14](canonical_schema.md)). The Phase 5 audit showed the risk was real *inside* structured XBRL too: debt understated 39% for Apple as a confident value, now fixed. Residual: scale detection for document-table cells is not wired into an upload extractor (FR-04) | 4, 5 |
| R-10 | **Universal thresholds misapplied across industries** | M | H | Thresholds in configuration; industry exclusions in MVP; flags framed relative to the company's own trend first | 7 |

## Other risks

| ID | Risk | Impact | Likelihood | Mitigation | Owner phase |
|---|---|---|---|---|---|
| R-11 | XBRL concept inconsistency (company extensions, changing tags) leaves fields missing | M→H→**M** | H→**M** | ✅ **Mitigated (Phase 5, audited).** Each concept declares how its tags relate — synonyms, differently-scoped versions, or additive components — plus explicit derivation rules recorded in provenance ([D-016](decision_log.md), [D-018](decision_log.md)). `total_debt` completeness 86%, `interest_expense` 92%, mean 88.8%; the remaining misses are mostly line items a business model does not present. Residual: chains are sized to 12 filings, extension concepts are not visible through `companyfacts`, and newer taxonomy elements (as `InterestExpenseNonoperating` was) will keep appearing — widen against a larger sample before scaling the universe | 5, 6 |
| R-12 | Dataset licence blocks public use | M | M | Check licence before download; prefer openly licensed or self-built data | 3 |
| R-13 | Demo companies leak into training data, producing a misleading demo | M | M→**Materialised** | ⚠️ **Not mitigated.** The hold-out was never built. The workspace runs on 163 companies from the labelled corpus ([workspace_ui.md §6](workspace_ui.md), [scope.md §6](scope.md)). Partly offset by construction: every displayed model score is **out-of-fold**, produced by a walk-forward fold that never saw the row (`scripts/phase11_assess.py::_out_of_fold`), so nothing shown is an in-sample fit. What is absent is a cohort the sampling design never touched, so the demo shows the pipeline rather than generalisation. Stated wherever the demo is described | 3, 8 — **carried forward** |
| R-14 | SEC access blocked for exceeding fair-access rules | L | L | Declared User-Agent (refuses to run without one); rate limiting at 8 req/s against a 10 req/s limit; on-disk caching. Never triggered across every phase's corpus builds | 3, ~~16~~ (cut) |
| R-15 | LLM cost or provider changes | L | M | One call per assessment; cache by input hash; provider behind an interface | 12 |
| R-16 | Sensitive uploaded documents or analyst comments committed or leaked | H | L | `.gitignore` for data/uploads; local storage; secrets via environment variables. `data/` is gitignored and rebuildable; `docs/` and `evaluation/` are the only committed outputs | 2, ~~15~~ → 13 |
| R-17 | Outputs mistaken for a credit decision or rating | H | L–M | Persistent disclaimer; "AI draft" labelling; analyst-only watch status | 12–14 |
| R-18 | Scope creep across 20 phases for a single developer | M | H | Phase gates; scope changes via decision log; MVP non-goals | All |
| R-19 | Library capabilities assumed but not verified (e.g. PDF table extraction quality) | M | M→**L** | ✅ **Closed (Phase 4).** `scripts/table_extraction_spike.py` measured pdfplumber vs pymupdf over 271 reference values by recall, not table count: **179/179 — identical**, with pdfplumber 2.4× faster, so it is chosen on speed and the risk of having picked wrong is now near zero ([D-015](decision_log.md), [golden_set.md §5](golden_set.md)). The measurement also relocated the real risk: PDF recall is 95% on filings narrowed to their statements and 42% on those that fall back to whole-filing rendering, so **isolation, not library choice, is the lever**. Residual: both libraries fail on borderless tables, which real uploaded statements often use | 2, 4 |
| R-20 | No real analyst feedback, so UX assumptions stay unvalidated | M | H | ⚠️ **Stands, unmitigated by anything but disclosure.** Phase 14 verified every page renders headlessly against the real store and checked the layout in a browser, but no practising analyst has seen it. [A-01](assumptions.md) and [A-02](assumptions.md) remain open for the same reason, and QM-07 is a scripted walkthrough rather than a user test | 14, ~~18~~ → 14 |
