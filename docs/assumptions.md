# Assumptions — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | Draft v0.1 — Phase 1 |
| **Date** | 2026-09-13 |
| **Related** | [risks.md](risks.md) · [data_feasibility.md](data_feasibility.md) · [decision_log.md](decision_log.md) |

Every assumption here is something the design depends on but has **not yet been
proven**. Each has a validation plan. When one is validated or disproven, update
its status and, if it changes the design, add a decision-log entry.

**Confidence:** High = well-documented or verified at source · Medium = plausible, partly supported · Low = uncertain; could change the design.
**Status:** Open · Validated · Invalidated.

## Users & workflow

| ID | Assumption | Why it matters | Confidence | Validation (how / when) | Status |
|---|---|---|---|---|---|
| A-01 | The analyst workflow and pain points in the PRD reflect real credit-monitoring practice | Drives the whole product design | Medium | No access to practising analysts. Cross-check against public credit-analysis material; state as a limitation. Revisit if analyst feedback becomes available. | Open |
| A-02 | Analysts value *change since last period* and *contradictions* more than a single risk score | Shapes watchlist ordering and UI priorities | Medium | Scripted walkthrough (Phase 14); literature on early-warning systems | Open |
| A-03 | Annual (10-K) monitoring is useful enough for an MVP even though real monitoring is often quarterly | Justifies deferring 10-Q | Medium | Documented as a limitation; revisit after Phase 11 | Open |

## Data

| ID | Assumption | Why it matters | Confidence | Validation (how / when) | Status |
|---|---|---|---|---|---|
| A-04 | SEC XBRL APIs are free, need no API key, and allow ≤ 10 requests/second with a declared User-Agent | Core data source for MVP | High — verified against SEC developer documentation, 2026-09-13 | Confirm in Phase 3 with a real request | Open |
| A-05 | XBRL `companyfacts` provides, per fact, the accession number, form type and filing date needed for point-in-time selection | Point-in-time correctness (SC-07) depends on it | High (not yet confirmed against a live response) | Inspect a live response in Phase 3 | Open |
| A-06 | Core line items (revenue, current assets/liabilities, total assets, debt, equity, operating cash flow, interest expense) can be mapped from US-GAAP XBRL concepts for most in-scope companies | Ratio coverage | **Medium→Low-Medium (Phase 4)→Medium-High (Phase 5 audit)** | Per-concept coverage over the golden set ([data_dictionary.md §6.1](data_dictionary.md)); QM-01 after tag policies and derivation ([canonical_schema.md §12](canonical_schema.md)) | **Validated for the golden set, not with a single-tag lookup.** Revenue, net income, operating cash flow, total assets and total liabilities resolve for every presented period; `total_debt` 86%, `interest_expense` 92%. Validated on 12 filings only — confirm on a larger sample before relying on it for the full universe |
| A-07 | Text-based PDFs of 10-K financial statements can be obtained or generated for a golden evaluation set | Needed to measure extraction accuracy against XBRL | **High — confirmed Phase 4** | Golden set assembled by rendering filing HTML to PDF ([D-014](decision_log.md), [golden_set.md](golden_set.md)) | **Confirmed, with a caveat:** generated PDFs are cleaner than real-world uploads, so QM-01's PDF figure is an upper bound |
| A-08 | A US corporate dataset with a distress label exists that is usable for a public portfolio project | The ML layer depends on it | Medium — candidates found, licence/feature details unverified | Phase 3 decision gate ([data_feasibility.md](data_feasibility.md)) | Open |
| A-09 | Features available in the training data can be reproduced from SEC XBRL data with equivalent definitions | Avoids training/serving skew | **Low** — likely the hardest assumption | Feature-by-feature mapping in Phase 3; quantify mismatch | Open |
| A-10 | MD&A and Risk Factors sections can be located in 10-K HTML reliably enough for NLP | NLP input quality | Medium→**Medium-High** — mechanism built and correct on the golden set, but not yet measured at scale | Section detection built in Phase 4 ([extraction.md §4](extraction.md)); accuracy on a labelled sample still due in Phase 10 | Open — a section that cannot be located is reported, never approximated, so the failure mode is safe |

## ML

| ID | Assumption | Why it matters | Confidence | Validation (how / when) | Status |
|---|---|---|---|---|---|
| A-11 | Bankruptcy filing (or the best available label) is a reasonable proxy for "credit distress" for a monitoring aid | Defines what the model estimate means | Medium — bankruptcy is rare and late; earlier deterioration is not labelled | Document label semantics in Phase 3; state limits in model card | Open |
| A-12 | Logistic regression on financial ratios gives a useful, explainable baseline | Justifies starting simple | High (well-established in the literature) | Compare to transparent ratio baseline, Phase 8–9 | Open |
| A-13 | Enough positive events exist for a meaningful **out-of-time** test | Otherwise metrics are too noisy to trust | Medium | Count events per year in Phase 3; report confidence intervals | Open |
| A-14 | The training base rate differs from any real portfolio's, so raw probabilities need careful framing | Prevents misleading "74% risk" displays | High | Calibration analysis and explicit labelling, Phase 9 | Open |

## NLP & LLM

| ID | Assumption | Why it matters | Confidence | Validation (how / when) | Status |
|---|---|---|---|---|---|
| A-15 | Rules plus classical NLP give acceptable precision for key signals before any LLM extraction is needed | Keeps NLP cheap, deterministic and testable | Medium | Precision/recall on labelled sentences, Phase 10 | Open |
| A-16 | A single structured LLM call can produce a grounded synthesis when given evidence with IDs | Keeps the synthesis layer simple | Medium | Grounding validator + evaluation suite, Phase 12 | Open |
| A-17 | Management language is often optimistic, so optimistic tone is weak evidence against deteriorating numbers | Contradiction rules must not treat tone as equal to financial data | Medium | Contradiction test cases, Phase 11 | Open |

## Technical & legal

| ID | Assumption | Why it matters | Confidence | Validation (how / when) | Status |
|---|---|---|---|---|---|
| A-18 | A modular Python monolith with SQLite is sufficient for MVP scale | Avoids unnecessary infrastructure | High | Revisit only if a concrete requirement appears | Open |
| A-19 | Python 3.12 is the right runtime (3.14 is also installed, but some ML/PDF libraries may lag) | Environment stability | Medium — not yet checked | Verify library compatibility in Phase 2 | Open |
| A-20 | SEC filings are public and may be used for this project, subject to fair-access rules | Legal basis for the data | High | Keep attribution; respect access policy | Open |
| A-21 | Third-party dataset licences permit use in a public portfolio repository | Could block a dataset | **Low** — not yet checked for the US candidates | Review each licence before download, Phase 3 | Open |
