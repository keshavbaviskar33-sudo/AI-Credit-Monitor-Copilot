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
| [D-004](#d-004-ml-model-uses-financial-features-only) | ML model uses financial features only | Proposed | 2026-09-13 |
| [D-005](#d-005-xbrl-as-source-of-record-pdf-extraction-evaluated-against-it) | XBRL as source of record; PDF extraction evaluated against it | Proposed | 2026-09-13 |
| [D-006](#d-006-exclude-financial-sector-companies-from-mvp) | Exclude financial-sector companies from MVP | Proposed | 2026-09-13 |
| [D-007](#d-007-annual-periods-before-quarterly) | Annual periods before quarterly | Proposed | 2026-09-13 |
| [D-008](#d-008-point-in-time-as-filed-data-rule) | Point-in-time (as-filed) data rule | Proposed | 2026-09-13 |
| [D-009](#d-009-roadmap-amendments) | Roadmap amendments | Proposed | 2026-09-13 |
| [D-010](#d-010-ml-output-is-not-called-a-probability-of-default) | ML output is not called a "probability of default" | Proposed | 2026-09-13 |
| [D-011](#d-011-training-data-chosen-through-a-phase-3-decision-gate) | Training data chosen through a Phase 3 decision gate | Proposed | 2026-09-13 |

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
**Status:** Proposed

**Context.** The brief's target architecture diagram routes NLP risk signals into the ML model. A supervised model can only use inputs present in its training data; no available labelled dataset contains NLP signals extracted from the same filings.

**Decision.** The ML credit-risk model uses **financial statement features only**. NLP signals meet the ML output in the combination layer (Phase 11) and synthesis (Phase 12), where agreements and contradictions are made explicit.

**Alternatives.** (a) Build a labelled text+financials training set — large effort, few events. (b) Feed NLP signals at inference without training on them — invalid.

**Consequences.** Simpler, valid model; qualitative evidence remains visible rather than absorbed into an opaque score. A text-aware model remains a possible later extension.

## D-005 XBRL as source of record; PDF extraction evaluated against it
**Status:** Proposed

**Context.** The brief plans PDF extraction → parsing as the route to financial data. For US SEC filers, filings are HTML with machine-readable XBRL financial data; parsing a PDF to recover numbers that already exist in structured form is less reliable. PDF extraction still matters for documents without XBRL (private borrowers, lender presentations, audited statements).

**Decision.** For SEC filers, **XBRL facts are the source of record** for numbers. The PDF extraction pipeline (Phases 4–5) is still built, and its accuracy is **measured against XBRL** on a golden set of filings where both exist. Disagreements between sources are surfaced as validation findings.

**Alternatives.** (a) PDF-only, as in the original plan — weaker accuracy, no ground truth to measure it. (b) XBRL-only — drops document extraction, a real analyst need and a core portfolio component.

**Advantages.** Reliable numbers for the MVP; automatic ground truth for extraction evaluation (QM-01); reconciliation checks as a feature.
**Disadvantages.** Two input paths to maintain; XBRL concept mapping is its own problem (R-11).

## D-006 Exclude financial-sector companies from MVP
**Status:** Proposed

**Decision.** Exclude banks, insurers, broker-dealers, REITs, investment funds and shell companies (by SIC code) in MVP.

**Reason.** Standard corporate ratios (current ratio, debt/equity, interest coverage) are misleading or undefined for these business models, and they need different analysis frameworks.

## D-007 Annual periods before quarterly
**Status:** Proposed

**Decision.** MVP assesses annual (10-K) fiscal years. Quarterly (10-Q) comes later.

**Reason.** 10-Q cash-flow statements are reported year-to-date, and fourth quarters must be derived from annual minus nine-month figures — real complexity that should follow a working annual pipeline. Real monitoring is often quarterly; this is a stated MVP limitation (A-03).

## D-008 Point-in-time (as-filed) data rule
**Status:** Proposed

**Decision.** Any assessment, training example or historical replay "as of" date *T* uses only facts **filed on or before T**, using the values as originally filed for that period unless the analyst explicitly chooses restated values.

**Reason.** Later filings restate and re-present prior-period figures. Using them leaks future information into training and makes historical replays look more prescient than they were (R-03).

**Consequences.** Facts must be stored with filing date and accession number; dedicated tests (SC-07).

## D-009 Roadmap amendments
**Status:** Proposed — see [roadmap.md](roadmap.md)

1. Data feasibility desk research added to Phase 1 (done), so the dataset constrains the schema before Phase 5.
2. Evaluation is built **incrementally in each phase**; Phase 17 consolidates rather than starts evaluation.
3. Core domain models (typed schemas with provenance) are introduced with Phase 5, and **SQLite persistence moves to be delivered with Phase 13** (review requires immutable history); Phase 15 becomes schema hardening and history/versioning queries.
4. Synthesis (Phase 12) must cite evidence IDs, validated by code (SC-04).

## D-010 ML output is not called a "probability of default"
**Status:** Proposed

**Decision.** Present the ML output as an *estimated likelihood of the modelled event (e.g. bankruptcy filing) within the modelled horizon, for companies resembling the training population*, with its applicability warnings. Avoid "PD" and avoid unqualified labels like "74% risk".

**Reason.** Public labels are bankruptcy filings, not defaults; the training base rate differs from any real portfolio (A-14); "PD" has a specific regulatory meaning.

## D-011 Training data chosen through a Phase 3 decision gate
**Status:** Proposed — details in [data_feasibility.md §5](data_feasibility.md)

**Decision.** Do not select the training dataset on unverified details. Phase 3 begins with licence checks, a feasibility spike on a self-built SEC + bankruptcy-records dataset, and an inspection of the public US bankruptcy dataset, followed by a recorded decision.
