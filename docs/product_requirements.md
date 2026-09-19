# Product Requirements — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | v1.0 — written in Phase 1, amended through Phase 19. Every FR and SC below is now either built and verified, or explicitly superseded by a decision and struck in place ([D-009](decision_log.md)) |
| **Date** | 2026-09-19 (created 2026-09-13) |
| **Related** | [user_workflow.md](user_workflow.md) · [scope.md](scope.md) · [assumptions.md](assumptions.md) · [risks.md](risks.md) · [data_feasibility.md](data_feasibility.md) · [decision_log.md](decision_log.md) · [measured_results.md](measured_results.md) |

> **This product is an analytical aid.** It produces *draft* assessments for a
> qualified credit analyst. It does not make, recommend as final, or execute
> credit decisions, and it is not a credit rating.

---

## 1. Problem statement

Lenders and credit investors hold exposure to many companies at once. Every time
one of those companies publishes new financial information, someone has to
answer: *did this borrower get riskier, and should we act?*

Today that reassessment is largely manual. For each company, each period, an
analyst reads long filings, re-keys ("spreads") the financial statements into a
spreadsheet, recomputes ratios, compares against prior periods, reads
management commentary for warning signs, and writes up a view. The process is:

- **repetitive** — the same mechanical steps for every company, every period;
- **error-prone** — manual re-keying and ad-hoc formulas;
- **slow to surface deterioration** — signals are spread across numbers and
  narrative, and portfolio reviews compete with other work;
- **hard to audit** — "where did this number come from?" and "why did we
  conclude this?" are often answered from memory.

**Product:** a monitoring copilot that, when new financial filings are
available, prepares an evidence-backed *draft* reassessment for each company in
an analyst's portfolio — what changed, why it matters, what supports it, what
contradicts it, and what to check — and then records the analyst's own
judgement alongside the draft, without overwriting either.

**One-line value proposition:**
> *"Show me which of my companies deteriorated this period, why, where the
> evidence is, and what I should check — then let me decide."*

## 2. Target users

### 2.1 Primary — Credit monitoring analyst

| | |
|---|---|
| **Works at** | Commercial bank corporate lending, private credit fund, or credit-focused asset manager |
| **Responsible for** | Periodic surveillance of a portfolio of existing borrowers / issuers; escalating deteriorating credits; documenting reviews |
| **Needs** | Fast triage across the portfolio; trustworthy numbers with sources; changes vs. prior period; early warning signs from narrative; a defensible written record |
| **Owns** | The final interpretation and the credit watch status for each company |

### 2.2 Secondary users

| User | Relationship to the product |
|---|---|
| **Credit risk manager / portfolio manager** | Consumes the watchlist and *analyst-approved* assessments. Should not act on unreviewed AI drafts. |
| **Model validator / internal auditor** | Needs model, feature, prompt and pipeline versions, data provenance, and evaluation evidence to judge whether outputs can be relied on. |

### 2.3 Explicitly not users

Borrowers; automated decisioning systems; retail investors seeking trading or
investment signals.

> **Caveat (see [A-01](assumptions.md)):** these personas and pain points are
> based on publicly described credit-monitoring practice, not interviews with
> practising analysts. That is a known limitation of this project.

## 3. Pain points and product response (hypothesised)

| # | Pain point | Product response |
|---|---|---|
| P1 | Manual spreading of financial statements is slow and error-prone | Automated extraction/normalisation with provenance and validation checks; the analyst verifies rather than re-keys |
| P2 | Ratios computed ad hoc, inconsistently, without a record of inputs | Deterministic, tested ratio engine; every ratio shows its formula and source values |
| P3 | Hard to see *what changed* since the last review | Period-over-period change detection is a first-class output |
| P4 | Warning signs hide in narrative text (MD&A, risk factors) | NLP risk signals with verbatim evidence and source location |
| P5 | Quantitative and qualitative evidence are reviewed separately; conflicts go unnoticed | Explicit agreement/contradiction detection across ratios, model and narrative |
| P6 | Reviews are hard to audit later | Immutable AI draft + separate analyst review, with timestamps and versions |
| P7 | Attention is spread evenly across the portfolio rather than where risk changed | Watchlist ordered by *change and unresolved concerns*, not by a single opaque score |

## 4. Product principles

1. **The analyst decides.** The system drafts; a named human approves, modifies or rejects.
2. **Deterministic before probabilistic.** Arithmetic, accounting checks and thresholds are plain code — never an LLM.
3. **Evidence or nothing.** Every displayed figure, flag, signal and conclusion links to its source. Unsupported output is a defect.
4. **"Insufficient information" is a valid answer.** Missing data is represented explicitly, never silently imputed in analyst-facing output.
5. **Point-in-time honesty.** An assessment "as of" a date uses only information that was public on that date.
6. **History is append-only.** New filings create new assessment versions; reviews never overwrite drafts.

## 5. Inputs

| Input | Source | MVP? | Notes |
|---|---|---|---|
| Company identifier (ticker or CIK) added to a watchlist | Analyst | ✅ | Resolved to SEC CIK |
| Company metadata (name, SIC industry code, fiscal year end) | SEC EDGAR submissions API | ✅ | Needed for scope filtering and future industry benchmarks |
| Structured financial facts (as filed) | SEC XBRL `companyfacts` API | ✅ | Source of record for public-filer numbers — [D-005](decision_log.md) |
| Annual report filing (10-K) | SEC EDGAR | ✅ | Primary document is HTML / inline XBRL |
| Narrative sections: MD&A (Item 7), Risk Factors (Item 1A) | 10-K text | ✅ | Input to NLP risk signals |
| Financial statement PDFs uploaded by the analyst | Analyst upload | ✅ | Text-based PDFs first; accuracy measured against XBRL where both exist |
| Quarterly reports (10-Q) | SEC EDGAR | Later | Year-to-date cash-flow reporting needs special handling — [D-007](decision_log.md) |
| Earnings call transcripts | Third party | Later | Licensing not yet evaluated |
| News, market data, credit ratings | External providers | Later | ~~Phase 16, behind an adapter layer~~ — **Phase 16 was cut** ([D-045](decision_log.md)): twelve phases of measurement produced no open question a second provider would answer. Reinstate on a real need |
| Scanned PDFs (OCR) | Analyst upload | Later | After text-based extraction is measured |

## 6. Outputs

### 6.1 Per company, per reporting period: an **Assessment**

Each section carries provenance and an explicit status. The shared status
vocabulary always includes `insufficient_data`.

| Section | Contents |
|---|---|
| **Financial data** | Normalised line items per fiscal year: value, unit, original label, source (filing accession + XBRL concept, or document + page), extraction confidence, transformations applied |
| **Validation results** | Accounting sanity checks (e.g. balance sheet balances, current assets ≤ total assets) and source-reconciliation discrepancies |
| **Ratios** | Value, formula, input values with provenance, and status: `ok` · `missing_input` · `zero_denominator` · `not_meaningful` (e.g. ROE with negative equity) |
| **Financial health flags** | Per dimension (liquidity, leverage, profitability, coverage, cash flow): level, trend direction, reasons, evidence references |
| **Change summary** *(monitoring)* | What materially changed vs. the previous assessed period, including flags that changed state |
| **ML distress estimate** | Estimated probability, model version, top local drivers, and applicability warnings (missing features, out-of-range inputs, excluded industry) |
| **NLP risk signals** | Signal type, severity, verbatim evidence quote, source filing, section, location |
| **Agreement / contradictions** | Points where components agree or disagree, framed as investigation items |
| **AI draft synthesis** | Structured summary, key risks, supporting evidence, contradictions, uncertainties, recommended analyst checks, and a *draft* risk level — every claim cites evidence IDs |
| **Analyst review** | Action (approve / modify / reject), analyst's assessment, credit watch status, comments, timestamp, reviewer, versions reviewed |

> **Naming the model output ([D-010](decision_log.md)).** The ML output is
> described as an *estimated likelihood of the modelled distress event within
> the modelled horizon, for the population the model was trained on* — not a
> regulatory "probability of default". Its exact definition is fixed in Phase 3
> once the training target is chosen.

### 6.2 Portfolio level: the **Watchlist**

A list of monitored companies showing, per company: latest assessed period,
review status (draft awaiting review / reviewed / superseded), analyst credit
watch status, health flags that changed, unresolved contradictions, and data
gaps. ~~Default ordering prioritises *unreviewed deterioration and unresolved
contradictions* rather than a single model probability.~~

> **Amended in Phase 14 ([D-051](decision_log.md)).** There is **no ordering at
> all.** Ordering companies against each other requires a severity number, and
> producing one would reintroduce the composite score [D-050](decision_log.md)
> had just refused — as a sort key, where it is harder to notice. The desk
> instead **groups by named reason**: six checkable facts about the assessment
> (the filer states a severe condition; all three layers are elevated; the
> layers disagree; the draft failed grounding; filing sections were unread;
> nobody has reviewed it). A company appears under every reason that applies,
> and within a bucket the order is alphabetical — as `ReviewStore.watchlist()`
> already was, for the same reason. The intent of the struck sentence survives;
> the mechanism does not.

## 7. Functional requirements (MVP)

Priority: **M** = must, **S** = should.

### Watchlist & ingestion
| ID | Requirement | P |
|---|---|---|
| FR-01 | Analyst can add/remove companies (ticker or CIK) to a watchlist | M |
| FR-02 | System rejects companies outside MVP scope (e.g. financial-sector SIC codes) with a clear reason | M |
| FR-03 | System retrieves available annual financial facts and 10-K filings for a watchlist company | M |
| FR-04 | Analyst can upload a financial statement PDF for a company; files are validated (type, size, parseable) before processing | M |
| FR-05 | Analyst can run an assessment **as of a chosen date**, using only filings filed on or before that date (historical replay) | S |

### Financial data & deterministic analysis
| ID | Requirement | P |
|---|---|---|
| FR-06 | Line items are normalised to a canonical schema with unit handling and alias mapping | M |
| FR-07 | Every normalised value retains its provenance (source, location, original label/value, transformation) | M |
| FR-08 | Accounting sanity checks run and failures are shown, not hidden | M |
| FR-09 | Ratios are computed deterministically with explicit missing / zero-denominator / not-meaningful statuses | M |
| FR-10 | Health flags per dimension include level, trend, reasons and evidence references; thresholds live in configuration, not hard-coded constants | M |
| FR-11 | Change vs. previous assessed period is computed and listed | M |

### ML, NLP, synthesis
| ID | Requirement | P |
|---|---|---|
| FR-12 | ML model returns ~~a probability~~ **a ranking position**, model version and local explanation (top drivers) | M |
| FR-13 | ML output carries applicability warnings when inputs are missing, out of training range, or the company is out of scope | M |
| FR-14 | NLP signals include verbatim evidence that is verifiably present in the source text | M |
| FR-15 | Contradictions between components are detected by explicit rules and listed | M |
| FR-16 | One grounded LLM call produces the structured draft synthesis from supplied evidence only | M |
| FR-17 | Synthesis claims that cite non-existent evidence IDs, or contain numbers not present in the evidence, are detected and flagged/rejected by code | M |

> **FR-12 amended in Phase 19 ([D-033](decision_log.md), [D-056](decision_log.md)).**
> The requirement was written before the model existed and asked for a
> probability. The measured calibration slope is **0.326**, and the training
> base rate is a property of the sampling design rather than of any portfolio,
> so a number in [0, 1] here would be a probability in appearance only —
> the most dangerous shape a risk output can take. `ModelExplanation` carries
> `score_percentile` alongside `score`, a `NOT_CALIBRATED` caveat attaches
> automatically outside [0.8, 1.25], and a `BASE_RATE_NOT_PORTFOLIO` caveat
> fires unconditionally on this corpus. The *explanation* half of FR-12 is met
> exactly as written.

### Review & audit
| ID | Requirement | P |
|---|---|---|
| FR-18 | Analyst can approve, modify or reject a draft; modify/reject require a comment | M |
| FR-19 | Original AI draft is immutable; analyst edits are stored separately | M |
| FR-20 | Credit watch status can only be set by an analyst action | M |
| FR-21 | Each assessment records pipeline, feature-schema, model and prompt versions plus source filing identifiers | M |
| FR-22 | A newer filing creates a new assessment version; earlier assessments and reviews remain accessible | M |

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| **Traceability** | Any displayed number can be traced to its source in ≤ 2 interactions |
| **Reproducibility** | Re-running an assessment with the same inputs and versions reproduces deterministic outputs exactly; LLM outputs are stored rather than regenerated |
| **Point-in-time correctness** | No value filed after the as-of date influences an assessment for that date |
| **Fail-safe behaviour** | Component failures degrade to `insufficient_data` with a reason; they never silently drop a section |
| **Security** | No secrets in the repository; API keys used server-side only; uploaded files validated and never executed; document text treated as untrusted input to the LLM (prompt-injection risk) |
| **Privacy** | MVP uses public SEC data. Uploaded documents and analyst comments are treated as confidential: stored locally, excluded from version control, not sent to third parties except the configured LLM provider |
| **Cost** | At most one LLM synthesis call per assessment, cached by input hash |
| **External access** | SEC fair-access rules respected (declared User-Agent, ≤ 10 requests/second) |
| **Performance** | Interactive at demo scale (tens of companies); no production SLA in MVP |

## 9. Human-in-the-loop boundary

The system **may** automatically: fetch public data, extract, normalise,
validate, compute ratios and flags, run the model, extract signals, detect
contradictions and write a draft.

The system **must never**: set a credit watch status, mark a draft as final,
present a lending action as decided, or change an analyst's recorded review.

Full boundary and review states: [user_workflow.md §5–6](user_workflow.md).

## 10. Success criteria

Criteria are split into **invariants** (must hold; enforced by automated tests)
and **quality metrics** (measured; targets set once a baseline exists — no
performance figure is claimed before it is measured).

### 10.1 Invariants (pass/fail)

| ID | Criterion | Verified by | Phase |
|---|---|---|---|
| SC-01 | 100% of displayed financial values and ratios have resolvable provenance | Automated test over all assessments in the evaluation set | 5–6, 14 |
| SC-02 | Ratio engine matches hand-computed expected values, including all edge-case statuses | Unit tests | 6 |
| SC-03 | 100% of NLP evidence quotes are present verbatim in the cited source text | Automated string-match check | 10 |
| SC-04 | 0 synthesis outputs accepted that cite unknown evidence IDs or state numbers absent from the evidence | Automated grounding validator | 12 |
| SC-05 | No code path sets a credit watch status or final assessment without an analyst action | Tests on the review service | 13 |
| SC-06 | AI drafts are unchanged after any review action | Tests on persistence layer | 13 |
| SC-07 | Historical replay uses no data filed after the as-of date | Point-in-time tests | 5, 8, 11 |

### 10.2 Quality metrics (measured, reported honestly)

> **Two namespaces, deliberately separate.** `QM-nn` below is the
> **pre-registered** list: the metrics this product committed to before any of
> them was measured, so that a later phase cannot quietly redefine what it
> promised to report. Phases also produce their own **phase-local**
> measurements, which are numbered `M-n` (for example `M-2` ratio coverage in
> [ratios.md](ratios.md), `M-3` health-engine coverage in
> [financial_health.md](financial_health.md), `M-4` the multi-filing
> point-in-time path). Those are not listed here because they were not promised
> in advance; they exist because a phase found something worth measuring.
>
> The split was introduced in Phase 10 after the two namespaces collided: the
> phase docs had numbered their own metrics sequentially from `QM-01`, so
> `QM-04` meant "the multi-filing path" in Phase 8 and "NLP precision and
> recall" here — two different metrics, one identifier, in one repository.

| ID | Metric | Target-setting approach | Phase |
|---|---|---|---|
| QM-01 | Field-level extraction accuracy on a golden set of 10-K financial statements (PDF vs. XBRL reference) | Baseline first; initial aspiration ≥ 95% on core fields for text-based PDFs, to be confirmed | 4–5 |
| QM-02 | ML discrimination on an **out-of-time** test set (ROC-AUC, PR-AUC vs. base rate) | Must beat a simple, transparent baseline (e.g. a few classic ratios) — not an arbitrary AUC | 8–9 |
| QM-03 | ML calibration (reliability curve, Brier score) | Reported; recalibrate if materially off | 9 |
| QM-04 | NLP signal precision and recall on a hand-labelled sentence set | Baseline first | 10 |
| QM-05 | Contradiction detection recall on constructed test cases | All constructed cases detected | 11 |
| QM-06 | Synthesis quality: grounding pass rate, uncertainty stated when evidence is missing, consistency across repeated runs | Evaluation suite | 12 (~~17~~) |
| QM-07 | Analyst can answer the five core questions (risk? why? support? conflicts? what to check?) from the company view | Scripted walkthrough (no access to real analysts — see A-01) | 14 (~~18~~ merged) |

> **Where each stands, as of Phase 19.** QM-01 **97.2%** ([canonical_schema.md §12](canonical_schema.md)).
> QM-02 **0.817 [0.778, 0.851]** eligibility-matched, beating every heuristic
> baseline ([D-054](decision_log.md)) — the "must beat a transparent baseline"
> bar is met, and the population must be named. QM-03 reported and **not**
> recalibrated, deliberately ([D-033](decision_log.md)). QM-04 precision
> **73.4%**, recall **38.1% relative to the sweep's reach** ([D-055](decision_log.md)).
> QM-05 met by construction: seven contradiction rules, each unit-tested.
> QM-06 grounding pass rate measured by fault injection — **0.000 false
> positives, 100% detection** — with the *live* half at n=12 and one debt
> unpaid. QM-07 exercised by headless render of every page against the real
> store, not by a real analyst ([A-01](assumptions.md)). Phase columns for 17
> and 18 are struck: [D-045](decision_log.md) reframed 17 and merged 18 into
> 14. Full register: [measured_results.md](measured_results.md).

## 11. Major risks

Full register: [risks.md](risks.md). The most consequential for product design:

1. **Training data does not match the product** (geography, company type,
   variables, label meaning) — see [data_feasibility.md](data_feasibility.md).
2. **Point-in-time leakage** — using restated or later-filed values when
   training or replaying history.
3. **Label meaning** — public labels are usually *bankruptcy filing*, a rare and
   late event, not the earlier deterioration a monitor aims to catch.
4. **Automation bias** — analysts rubber-stamping fluent AI drafts.
5. **Ungrounded LLM claims / prompt injection** via filing text.

## 12. Open questions

| # | Question | Needed by |
|---|---|---|
| Q1 | Which training dataset and target definition? (candidates and decision gate in [data_feasibility.md](data_feasibility.md)) | Phase 3 |
| ~~Q2~~ | ~~Approve proposed decisions D-004 – D-011?~~ Resolved 2026-09-13: all accepted | — |
| Q3 | ~~LLM provider and budget~~ | **Resolved (Phase 12), then extended.** The provider is confined to `synthesis/client.py` behind a protocol ([D-043](decision_log.md)); one call per assessment, no retries, ~$0.040 per assessment estimated at list price ([D-042](decision_log.md)). ~~Claude Opus 5 via the Anthropic SDK~~ — **[D-044](decision_log.md) added a second client** when a Gemini credential arrived, and moved the prompt out of one vendor's envelope so a stored draft's fingerprint is provider-independent. The `llm` extra carries **both** SDKs; the only live run to date is `gemini-3.6-flash`, and `AnthropicSynthesisClient` has never made a call ([measurement_debts.md §5](measurement_debts.md)). The test suite runs without either |
| Q4 | ~~UI framework (Streamlit vs. API + web frontend)~~ | **Closed (Phase 14).** Streamlit confirmed, not merely retained: [D-052](decision_log.md) built the design system as theme configuration rather than CSS and navigation as links rather than page switching. The revisit [D-012](decision_log.md) scheduled happened and found no requirement Streamlit failed to meet. The seam for a different renderer is the `workspace` package, which imports no UI framework |
| Q5 | Which industries to support after MVP, and what benchmark data exists for industry-aware thresholds | **Still open.** Phase 9 measured industry separability at 0.87–0.95, and [D-054](decision_log.md) named industry matching as the next step and did not take it. [R-10](risks.md) stands |
