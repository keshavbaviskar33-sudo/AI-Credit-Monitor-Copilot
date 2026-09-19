# Measured Results — every number this project can defend

| | |
|---|---|
| **Status** | Complete as of Phase 19 (2026-09-19). One debt is unpaid and is listed as unpaid |
| **Decisions** | [D-056](decision_log.md) |
| **Related** | [explaining_the_project.md](explaining_the_project.md) · [architecture.md](architecture.md) · [roadmap.md](roadmap.md) |

> **Every figure here carries its population and its caveat, because most of
> them are meaningless without one.** This document is a register, not a
> summary: it repeats no number whose source it cannot name, and it includes
> the negative results, which are several of the most interesting entries.
>
> Nothing here is new measurement. Phase 19 measured nothing — it collected
> what the earlier phases measured and checked it against the code.

---

## 1. The rule this project ran on

Every claim is measured or labelled unmeasured. That produced three habits
worth stating before any number, because they are what make the numbers worth
reading:

- **A bias this project can name is not a bias this project has measured.**
  Phase 11 disclosed a shortcut *and stated which way it biased three rules*.
  Phase 17 ran it for real: two of the three directions were wrong
  ([D-053](decision_log.md)). Phase 9 said the confound was survivorship;
  measuring it said eligibility ([D-032](decision_log.md)).
- **A published number may move against the project.** Correcting Phase 11's
  health shortcut made the health layer look *worse*, and one published
  interval moved off zero in the unflattering direction. It is reported.
- **Two of the author's own declarations were overturned by the data** — a
  contradiction rule's resolution hint that was backwards by a factor of ten,
  and two signal-specificity labels set from intuition
  ([D-035](decision_log.md), [D-038](decision_log.md)).

## 2. The three tiers

The predictive layer is the only part of this project where the population
determines whether a figure may be quoted at all. The classification is
[model_evaluation_explainability.md §14.3](model_evaluation_explainability.md)'s
and is reproduced here as the headline.

### Tier 1 — quotable as bankruptcy discrimination

| Figure | Value | Population |
|---|---|---|
| **Logistic hazard model, ROC-AUC** | **0.817 [0.778, 0.851]** | Eligibility-matched point-in-time panel: 1,467 event rows + 932 comparison rows, all meeting BRD's own inclusion rule (≥$100M in 1980 dollars, CPI-adjusted per row-year), base rate 8.1%, walk-forward out-of-time, company-clustered interval |
| Cohort separability on the same panel | **0.817** | The same features predicting *which cohort a row came from* rather than the label |
| The gap between them | **+0.0001** | |

**Why this one is quotable and nothing before it was.** A cohort-separability
probe asks whether the model could be reading the sampling design instead of
credit risk. On every earlier panel the probe *beat* the label. Here it does
not — the model discriminates bankruptcy as well as it discriminates its own
sample construction, which is the condition for calling the figure bankruptcy
discrimination ([D-054](decision_log.md)).

Two caveats that travel with it: **industry is not matched** (separability
0.87–0.95 in Phase 9, named as the next step and not taken), and the panel's
base rate of 8.1% is still **21×** the real-world rate of 0.39%.

### Tier 2 — quotable only with the population named

| Figure | Value | Population and the clause that must travel with it |
|---|---|---|
| Within-event-cohort ROC-AUC | 0.733 logistic / 0.787 boosting | 1,592 rows, 183 events, 246 companies, base rate 12.3%. Cohort membership is constant, so it cannot be read. Answers the narrower question: *among companies BRD recorded, which failed this year?* |
| Recall at a 5% / 10% alert rate | 25.8% / 41.5% logistic | Pooled out-of-fold ranking — **only** with the cohort caveat attached |
| Boosting − logistic, paired | +0.054 [0.016, 0.091] within cohort; +0.044 [0.008, 0.080] size-blind | Paired, company-clustered bootstrap on the difference. The basis for [D-034](decision_log.md)'s primary-model choice, and the *only* model comparison here that is a paired test |
| NLP signal recall | **38.1% [20.8%, 59.1%]** | *Relative to an over-broad keyword sweep's reach* — an upper bound on true recall, never an estimate of it. 8 of 21 true instances. 16 of the 21 are `asset_impairment`, and **six of twelve codes have no true instance in the pool at all**, including two of the three highest-lift ones ([D-055](decision_log.md)) |

### Tier 3 — not quotable

| Figure | Why not |
|---|---|
| Pooled ROC-AUC 0.803 (logistic) / 0.887 (boosting) | The cohort probe matches or beats the label on this panel. Never "bankruptcy prediction accuracy" |
| **Every gradient-boosting figure, on every panel** | Its separability gap survives eligibility matching completely unchanged (+0.021 → +0.021) while its AUC falls 0.894 → 0.839. This is the primary model, and its pooled numbers are the ones that may not be quoted |
| Any probability reading of any score | Calibration slope 0.326 (0.392 point-in-time). The output is a **position in a ranking** ([D-033](decision_log.md)), enforced by a caveat the schema attaches automatically |

## 3. The negative results

These are deliverables, not omissions. Each one closed a question the project
would otherwise still be guessing at.

| Finding | Measured | Where |
|---|---|---|
| **Combining the layers does not improve the ranking** | At a matched alert budget on 202 labelled filings, three-layer agreement is *exactly* as precise as the model's own top-43: **+0.000 [−0.082, +0.098]**. Two of four agreement rules are measurably worse | [D-036](decision_log.md) |
| **Model-and-health agreement is measurably worse than the model alone** | −0.032 [−0.065, **−0.006**]. The interval stopped touching zero only *after* Phase 17 corrected the health shortcut — the correction made the layer look worse | [D-053](decision_log.md) |
| **The narrative layer costs 20 precision points against the model** | −0.200 [−0.307, −0.082] at a matched budget. The filer's own words are the weaker evidence, which is what [A-17](assumptions.md) assumed and this measured | [combined_assessment.md §6.2](combined_assessment.md) |
| **Rebuilding the negative cohort point-in-time changed nothing** | Logistic 0.803 → 0.797; cohort separability got *worse*, 0.792 → 0.843. Only 22.6% of 2009–2020 annual filers survive into today's ticker file, and that was not the problem | [D-032](decision_log.md) |
| **SHAP is unnecessary for a linear model** | The exact linear decomposition reconstructs the model's own `decision_function` to **3.6e-15**. SHAP computes the same thing with a dependency in the middle. It is used only for the tree model, where no closed form exists | [D-030](decision_log.md) |
| **Phase 7's signals add nothing beyond the trends they summarise** | Ablation: `signals` −0.001 [−0.017, +0.013], `quality` +0.001. `levels` +0.062, `ratios` +0.110, `trends` +0.065 are each significant | [predictive_model.md §7.2](predictive_model.md) |
| **44% of the logistic model's attribution came from missingness** | Tracking size (ρ=−0.39) and history depth (ρ=−0.47), not the label (ρ=−0.07). [D-034](decision_log.md)'s model promotion **removed** this pathology rather than inheriting it — the primary model's share has a median of 0.004 | [D-032](decision_log.md), [D-038](decision_log.md) |
| **Two PDF libraries are indistinguishable on accuracy** | 179/179 reference values each, identical on every cohort. Table counts differ by 2.7× while recovering identical values. pdfplumber chosen on speed (2.4×), not accuracy | [D-015](decision_log.md) |
| **The real-world base rate is 12× to 126× below every training base rate** | 0.39% — 367 BRD petitions over 93,394 SEC annual-filer-years — against design rates of 0.049, 0.081 and 0.496 | [A-14](assumptions.md) |
| **Bankruptcy is a strict subset of credit distress** | Any asserted distress disclosure is followed by a petition only **59 of 92 times (64.1%)**; even going-concern doubt only 27 of 32. Those 33 filings train the model to call genuinely distressed companies safe | [A-11](assumptions.md) |

## 4. The layers, measured

### Extraction and canonicalisation (Phases 4–5)

| Metric | Value | Population |
|---|---|---|
| **QM-01 value/period accuracy** | **97.2%** (247/254) | 12-filing golden set, against XBRL `reference_values.csv`. The 7 misses are a ground-truth definition difference on `LongTermDebt` rows (noncurrent vs. total), **0 wrong values** |
| Mean per-concept completeness | 88.8% | Same corpus. `total_debt` 86%, `interest_expense` 92% |
| Balance-sheet equation checks | **12/12 independent** | 16 circular checks suppressed. The pass count *fell* from 19 after the audit — a more honest number, not a regression |
| Sign-convention violations | **0** | |
| HTML reference-value recall | 85.1% (291/342); **100%** on 2025–26 filings | The primary document path |
| PDF reference-value recall | 66.1% | Generated PDFs, which are cleaner than real uploads — an **upper bound** ([A-07](assumptions.md)) |

The Phase 5 audit is worth one line of its own: it found debt **understated by
39% for Apple and returned as a confident value**, because additive tag
components were being read as alternatives. Value accuracy went 87.0% → 97.2%
and `CONFLICTING` facts 50 → 3 ([D-018](decision_log.md)).

### Ratios and financial health (Phases 6–7)

| Metric | Single filing | Multi-filing, point-in-time |
|---|---:|---:|
| Ratio slots calculated | 362/598 — 60.5% | **1,953/2,405 — 81.2%** |
| Conclusive trend directions | 63/156 — 40.4% | **143/156 — 91.7%** |
| `INSUFFICIENT_DATA` dimensions | 21/60 | **0/60** |
| Signals fired | 37 | 153 |

**The single-filing column is not a worse result, it is a measurement of the
harness.** The multi-filing path existed, was unit-tested, was exported — and
had never been run against real data by any script in the repository. Running
it moved the project's headline quality numbers more than any library change
could, and turned Pfizer's "0 signals" into a corrected **false negative** of
10 real ones. All 56 healthy-cohort signals were then re-read by hand: **3
endpoint artefacts in 90 trend-based signals, no fabrications.**

### The narrative layer (Phase 10)

| Metric | Value | Population |
|---|---|---|
| **SC-03 — quotes verbatim** | **2,355 of 2,355. 0 failures** | 238 filings. Verified by slicing each quote back out of the document at the offsets it claims |
| QM-04 precision | 73.4% | 64 hand-labelled signals — **13/13 on the three highest-lift codes**. Labels committed under `evaluation/` |
| **The assertion gate, `COVENANT_BREACH`** | ungated lift **1.02** → gated **2.40** | Ungated, covenant language appears in 59% of the filings of companies that did **not** fail and 60% of those that did. To two decimal places that is *no information*. The gate removes 85% of comparison-side filings and 63% of event-side ones — selective, not merely strict |
| Highest-lift codes | `DELISTING_NOTICE` 6.10 · `GOING_CONCERN_DOUBT` 5.49 · `DEBT_RESTRUCTURING` 2.87 | 118 pre-petition filings vs 120 year-matched. **All twelve codes point the right way** |
| MD&A located | **83.6%** (Item 1A 81.5%) | Not the 12/12 the golden set implied. One filing in five yields no MD&A, so "no signals" means "not read" for that fifth — and `SectionCoverage` records which ([A-10](assumptions.md)) |

### Combination and grounding (Phases 11–12)

| Metric | Value |
|---|---|
| Unresolved evidence citations | **0**, across 202 assessments |
| Quote mismatches across the layer boundary | **0** |
| Evidence IDs stable on independent re-assembly | **stable**, 25-assessment sample |
| **As-of gate refusals** | **202 of 202** assessments refused when dated one day before their filing date |
| **Grounding validator false-positive rate** | **0 of 176 — 0.000** |
| Fault detection, seven injected classes | **100% detected.** `fabricated_number` 99.4% as a *rejection*, the residual 1/176 downgraded to a flag by colliding with a different real value in the same assessment |
| Precision-rule boundary | Nothing below half a unit in the last stated place is flagged; everything above it is (swept at k = 0.2 … 10.0) |
| The one positive discrimination result | A filing that both **asserts and denies** the same condition is **2.04×** more likely to precede a petition — available from no single layer, and only because the gate kept `NEGATED` rather than dropping it |

**The live LLM run, stated at its real size.** `gemini-3.6-flash`, 120
assessments attempted, **12 drafts returned, 11 accepted (91.7%)**, 108 refused
on free-tier quota. Twelve drafts put a 95% interval of roughly **62%–100%** on
that rate. **It is not a reliability figure and must not be quoted as one.**

**The single rejection is the most useful result in the phase.** Drafting for
GT Advanced Technologies, the model reproduced 195 characters of a filing
exactly and then dropped the word *our* from inside the quotation, in a draft
that otherwise reads as clean and well-sourced:

```text
model:  ...could have a further adverse effect on     share price.
filing: ...could have a further adverse effect on our share price.
```

Caught mechanically, on the first live batch. Prompt caching measured **zero**
on every call, so no saving is claimed.

### Review, persistence and the workspace (Phases 13–14)

| Metric | Value |
|---|---|
| Assessments / drafts / reviews recorded | **202 / 202 / 68** over 163 companies |
| Round-trip mismatches after close-and-reopen | **0** |
| **Forbidden edits attempted on the full database** | **6 of 6 refused** (`UPDATE` + `DELETE` × 3 tables), attempted against the *raw connection*, not through the module |
| Superseded assessments retaining their review | **14 of 39** — the half of FR-22 that fails silently |
| Store size / watchlist query | 4.46 MB for 202 full evidence registers / 25 ms over 163 companies |
| View-model tests | 18, one of which **fails if a field named `score`, `confidence`, `rating` or `severity` reappears** |

### Engineering

| Metric | Value |
|---|---|
| Tests | **758 passing** |
| Line coverage | **94%** |
| `ruff check` / `ruff format --check` | clean / 176 files |
| `mypy --strict` | **clean, 79 source files** (17 inherited errors cleared in Phase 19 — [D-057](decision_log.md)) |

## 5. What is not measured, and the one debt that is unpaid

> **Unpaid debt: the live synthesis sample is 12 drafts from one provider.**
> `AnthropicSynthesisClient` has never made a call. The measurement owed is
> specifically *does a second model behave the same way against the same
> validator* — and it needs a credential, not work. `LLM_PROVIDER` and
> `LLM_API_KEY` are empty. **To pay it:** set both, then
> `./.venv/Scripts/python.exe scripts/phase12_synthesize.py`. Nothing else is
> missing. Reported unpaid rather than substituted with a number that would
> answer a different question ([measurement_debts.md §5](measurement_debts.md)).

| Not measured | Consequence |
|---|---|
| Whether a second model grounds as well as the first | The debt above |
| True NLP recall | Only recall *relative to a keyword sweep's reach* exists, and it is dominated by one code |
| The catalog's recall on the high-lift disclosures | Six of twelve codes have no true instance in the pool |
| Industry confounding in the eligibility-matched panel | Separability 0.87–0.95 is known; the match is one-dimensional |
| How a restatement propagates into a ratio, a trend and a feature | Fact-level restatement size is measured (median 0.8%, p90 **20.0%**, 23.6% above 5%); propagation is not |
| What an annual cadence misses versus quarterly | [A-03](assumptions.md). `compare()` is unit-tested; no multi-period replay was run over the corpus |
| Whether real analysts would use any of this | [A-01](assumptions.md), [A-02](assumptions.md), [R-20](risks.md). No access to practising analysts. The personas are from public material |
| Whether the demo companies are held out of training | **They are not.** The workspace runs on 163 companies from the labelled corpus. [R-13](risks.md) proposed holding them out and it was never done — so the workspace is a demonstration of the pipeline, not of out-of-sample performance |
| Fidelity of the health encoding on the other ~3,700 panel rows | The Phase 17 re-run covers the 202 filings carrying a narrative layer |

## 6. Per-phase index

Where each figure above comes from, for anyone who wants to check it.

| Phase | Document | Headline |
|---|---|---|
| 3 | [data_dictionary.md](data_dictionary.md), [data_feasibility.md](data_feasibility.md) | 178 usable positive events from 992 CIK-carrying BRD cases |
| 4 | [extraction.md](extraction.md), [golden_set.md](golden_set.md) | HTML 85.1% recall, 100% on modern filings; two PDF libraries tied |
| 5 | [canonical_schema.md](canonical_schema.md) | QM-01 97.2%; the audit found debt understated 39% |
| 6 | [ratios.md](ratios.md) | 13 ratios, four-state result model, no formula errors found |
| 7 | [financial_health.md](financial_health.md) | 91.7% conclusive trends on the multi-filing path |
| 8 | [predictive_model.md](predictive_model.md) | 365-day hazard, walk-forward, 183 events, three leakage layers |
| 9 | [model_evaluation_explainability.md](model_evaluation_explainability.md) | The confound, measured three ways; SHAP unnecessary for the linear model |
| 10 | [nlp_risk_signals.md](nlp_risk_signals.md) | The gate: lift 1.02 → 2.40; SC-03 2,355/2,355 |
| 11 | [combined_assessment.md](combined_assessment.md) | Combining does not improve the ranking |
| 12 | [grounded_synthesis.md](grounded_synthesis.md) | 0.000 false positives, 100% fault detection, one live catch |
| 13 | [review_and_persistence.md](review_and_persistence.md) | 6 of 6 edits refused by the database |
| 14 | [workspace_ui.md](workspace_ui.md) | Three reads where the score would be |
| 17 | [measurement_debts.md](measurement_debts.md) | Four debts paid, two published claims corrected, one unpaid |
