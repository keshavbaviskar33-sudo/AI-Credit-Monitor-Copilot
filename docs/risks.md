# Risk Register — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | Draft v0.1 — Phase 1 |
| **Date** | 2026-09-13 |
| **Related** | [assumptions.md](assumptions.md) · [data_feasibility.md](data_feasibility.md) |

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
| R-07 | **Ungrounded LLM output** — invented numbers, sources or causes | H | M | Evidence IDs; structured output; code-based validation of citations and numbers (SC-04); fall back to `insufficient_data` | 12, 17 |
| R-08 | **Prompt injection via documents** — filing or uploaded text containing instructions to the LLM | M | L–M | Treat document text as data; delimit evidence; no tools/actions available to the LLM; output schema validation | 10, 12 |
| R-09 | **Extraction errors propagate silently** — wrong unit (thousands vs. millions), sign or column | H | M | Phase 4 built the "never silent" half: every block/table/section carries a resolvable location, and anything not extracted becomes an explicit `ExtractionError` (a page with no text, a section that cannot be located) rather than an omission ([extraction.md](extraction.md)); golden set with XBRL reference values assembled ([golden_set.md](golden_set.md)). Still Phase 5: unit detection, accounting sanity checks, and the QM-01 accuracy number itself | 4, 5 |
| R-10 | **Universal thresholds misapplied across industries** | M | H | Thresholds in configuration; industry exclusions in MVP; flags framed relative to the company's own trend first | 7 |

## Other risks

| ID | Risk | Impact | Likelihood | Mitigation | Owner phase |
|---|---|---|---|---|---|
| R-11 | XBRL concept inconsistency (company extensions, changing tags) leaves fields missing | M→**H** | H | **Now quantified, not hypothetical (Phase 4):** over the 12-filing golden set, `Liabilities` is present for 6/12, `LongTermDebt` 7/12, `Revenues` 9/12 and the assumed `SalesRevenueNet` **0/12** — deprecated by the ASC 606 tags ([data_dictionary.md §6.1](data_dictionary.md)). Mitigation for Phase 5 is therefore mandatory, not optional: fallback chains per concept, explicit derivation rules for subtotals, derived values marked as derived in provenance, and coverage reported per field | 5 |
| R-12 | Dataset licence blocks public use | M | M | Check licence before download; prefer openly licensed or self-built data | 3 |
| R-13 | Demo companies leak into training data, producing a misleading demo | M | M | Hold out demo companies / periods explicitly | 3, 8 |
| R-14 | SEC access blocked for exceeding fair-access rules | L | L | Declared User-Agent; rate limiting; local caching; nightly bulk files for large pulls | 3, 16 |
| R-15 | LLM cost or provider changes | L | M | One call per assessment; cache by input hash; provider behind an interface | 12 |
| R-16 | Sensitive uploaded documents or analyst comments committed or leaked | H | L | `.gitignore` for data/uploads; local storage; secrets via environment variables | 2, 15 |
| R-17 | Outputs mistaken for a credit decision or rating | H | L–M | Persistent disclaimer; "AI draft" labelling; analyst-only watch status | 12–14 |
| R-18 | Scope creep across 20 phases for a single developer | M | H | Phase gates; scope changes via decision log; MVP non-goals | All |
| R-19 | Library capabilities assumed but not verified (e.g. PDF table extraction quality) | M | M | ✅ **Spike done (Phase 4)** — `scripts/table_extraction_spike.py` measured pdfplumber vs pymupdf on the golden set by reference-value recall, not table count; pdfplumber chosen ([D-015](decision_log.md), [golden_set.md](golden_set.md)). Residual: **both** libraries fail on borderless tables, which real uploaded statements often use | 2, 4 |
| R-20 | No real analyst feedback, so UX assumptions stay unvalidated | M | H | Scripted walkthroughs; state limitation clearly | 14, 18 |
