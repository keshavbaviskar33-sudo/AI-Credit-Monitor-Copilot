# Predictive Credit-Risk Model — Phase 8

| | |
|---|---|
| **Status** | Complete — measured, with the limitations stated; several quantified further in Phase 9 |
| **Date** | 2026-09-17 |
| **Decisions** | [D-024](decision_log.md) window · [D-025](decision_log.md) target · [D-026](decision_log.md) point-in-time contract · [D-027](decision_log.md) validation · [D-028](decision_log.md) model family |
| **Code** | `src/credit_risk_copilot/modeling/` |
| **Scripts** | `phase8_build_corpus.py` → `phase8_build_dataset.py` → `phase8_train_evaluate.py` |
| **Related** | [architecture_audit.md](architecture_audit.md) · [financial_health.md](financial_health.md) · [ratios.md](ratios.md) · [canonical_schema.md](canonical_schema.md) |

> **What this model is not.** Following [D-010](decision_log.md), its output is
> *an estimated likelihood that a company resembling those in the training
> population files a US bankruptcy petition within the next 365 days*. It is
> not a probability of default, not a rating, and not a decision. The analyst
> decides ([D-003](decision_log.md)).

---

## 1. The prediction problem

    Given everything SEC had published about company C on the day it filed
    its annual report, what is the probability that C files a bankruptcy
    petition within the next 365 days?

Stacked across companies and filings, this is a **discrete-time hazard model**
in person-period form: each row is one at-risk interval, censored intervals
are excluded rather than scored, and the conditional hazard is estimated by a
binary classifier over the intervals. That is the standard multi-period
bankruptcy specification rather than the single-snapshot discriminant form,
and it was chosen because it is what the data actually is — see
[D-025](decision_log.md) for the alternatives considered and rejected.

## 2. The point-in-time contract

Every row is a claim that can be checked:

```text
                    prediction date T
                    = information cutoff
                            |
   filings received <= T ───┤
   earliest-filed value ────┤
   per (concept, period)    |
                            v
                        FEATURES
                            |
                       (T, T + 365d]
                            |
                            v
                        OUTCOME
```

Three enforcement layers, deliberately redundant ([D-026](decision_log.md)):

| Layer | Where | What it stops |
|---|---|---|
| Filter before resolution | `history.resolve_company_history(filed_on_or_before=T)` | A later filing influencing a conflict, a derivation or a period set. Filtering *after* resolution is not enough: a `total_liabilities` derived at a fixpoint that consumed a 2024 filing is contaminated even if the surviving fact points at a 2019 accession. |
| As-filed selection | `CompanyFinancials.as_of(T)` | A later restatement overwriting what was known at the time. |
| Post-hoc assertion | `Observation.assert_no_future_information` | Everything the first two missed. Raises `LeakageError` on every emitted row that fails. |

The first two are claims about how the builder was written. The third is a
check on the object that was built, and it is what makes the guarantee
testable — `tests/test_modeling_contract.py` and
`tests/test_modeling_dataset.py` deliberately construct violating rows and
assert the refusal.

## 3. The outcome

**Source.** Florida-UCLA-LoPucki Bankruptcy Research Database
([D-013](decision_log.md)): 1,218 cases, 1980-04-07 to 2022-12-11, 939 distinct
CIKs, 1,190 Chapter 11 and 25 Chapter 7.

**Nothing else is treated as ground truth.** Phase 7 deterioration signals,
ratio thresholds and any model output are features or comparators — never
outcomes.

**Two parameters were measured rather than assumed:**

*Label completeness stops at 2020-12-31, not at BRD's release date.* Case entry
lags the petition, so the final release years are thin:

| Year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cases | 26 | 17 | 25 | 43 | 30 | 16 | 25 | 56 | **8** | **6** |

`labels.measure_label_completeness` compares each year against the 2011–2019
median (25) and walks back to the last year clearing half of it. Rows whose
forward window ends after 2020-12-31 are **censored**.

*The horizon follows the filing-to-event gap.* A company stops filing once it
fails, so the horizon has to reach the petition from the last 10-K. Measured
over the corpus's 261 event companies with a prior annual filing: median 244
days, p75 344, p90 397. A 365-day window reaches **80.5%** of events, 547 days
96.9%, 730 days 98.9%.

365 days was chosen anyway, for three reasons: consecutive annual filings are
~12 months apart, so a 365-day window makes observations *tile* the timeline
without overlapping (one interval, one outcome, uncorrelated labels); it is the
product's own re-assessment cadence ([D-001](decision_log.md)); and it
preserves prediction dates through 2020-01-01 where 730 days would stop at
2019-01-01. A 730-day panel is built alongside as a robustness check.

**A censoring rule that had to be corrected.** The first implementation labelled
a row `1` whenever BRD recorded an event inside its window, even past the
completeness cutoff — reasoning that an observed event is positive evidence
regardless. That is selection on the outcome: past the cutoff the source still
records catalogued events but cannot confirm non-events. Measured, it produced
three folds (2020, 2021, 2022) whose **every row was an event**. The rule is
now: an unobservable window is censored, whatever is recorded in it.

## 4. The dataset

**Corpus** (`phase8_build_corpus.py`, seed `20260917`):

| | Drawn | Financial sector | No SIC | Too few filings | **Kept** |
|---|---:|---:|---:|---:|---:|
| Event cohort | 303 | 31 | 0 | 8 | **264** |
| Comparison cohort | 900 | 178 | 117 | 179 | **426** |

The [D-006](decision_log.md) SIC exclusion (6000–6999) is applied to **both**
cohorts. Applying it only to the comparison sample would have taught the model
that "is a bank" predicts bankruptcy — financial-sector failures are heavily
represented in the 2008–2010 cases.

**Panel** (`phase8_build_dataset.py`):

| | Primary (365d) | Robustness (730d) |
|---|---:|---:|
| Observations built | 7,272 | 7,272 |
| Usable rows | **3,856** | 3,374 |
| Positives | **183** | 334 |
| Negatives | 3,673 | 3,040 |
| Censored | 3,416 | 3,898 |
| Event rate | **4.75%** | 9.90% |
| Companies with rows / with events | 674 / 134 | 674 / 166 |

Of the censored rows, 3,287 have an unobservable horizon (prediction date after
2020-01-01) and 129 sit inside an active proceeding. A further 3,932 filings
produced no observation at all: 3,885 because the accession carries no XBRL
facts (pre-phase-in filings, which `submissions` still lists) and 47 because
fewer than two fiscal periods were visible at the cutoff.

The 730-day panel's higher positive count is **not** more events — it is the
same events labelling two consecutive rows each, which is precisely why the
365-day horizon is the primary one.

## 5. Features

57 features in six families, all computed from Phase 5/6/7 outputs. Nothing
here re-derives a ratio or re-reads XBRL: if a number is not already available
from an earlier phase, it is not a feature.

| Family | n | What it carries |
|---|---:|---|
| `scale` | 2 | `log_total_assets`, `log_revenue` |
| `levels` | 6 | Balance-sheet and earnings composition normalised by assets — working capital, cash, EBIT, turnover, free cash flow, cash-to-debt |
| `ratios` | 13 | The Phase 6 catalog as calculated |
| `trends` | 17 | Phase 7 `percent_change` per ratio, plus deterioration/improvement counts, max persistence, unusual-movement count |
| `signals` | 14 | One indicator per Phase 7 signal code, plus per-dimension deterioration |
| `quality` | 5 | Ratio and fact coverage, periods available, derived-input share, conflicting-ratio count |

**Provenance (§14).** `FEATURE_SPECS` records each feature's family, kind and
`source_id`, and `ObservationKey.contributing_accessions` records every
accession whose facts reached the row:

```text
feature → spec.source_id → ratio / canonical concept
        → CanonicalFact.provenance → accession → filing date
```

**Missing is never zero.** A feature that cannot be computed stays `None`
through to `design_matrix`, which emits `np.nan` and a companion
`<name>__missing` indicator for the linear models; the gradient-boosting model
consumes the `NaN` directly. Collapsing "we could not compute leverage" into
"leverage is 0" would make a company with unreadable filings look
debt-free — the exact failure an early-warning system cannot afford.

**Pathological values are kept.** Negative equity, negative margins and
near-zero denominators are genuine distress, and Phase 6's status/warning
semantics already separate them from data errors ([D-019](decision_log.md),
[D-021](decision_log.md)). Nothing is winsorised or dropped for looking
extreme.

## 6. Evaluation design

**Walk-forward, out-of-time** ([D-027](decision_log.md)): train on everything
before year *Y*, test on year *Y*, step *Y* forward. Every row after the burn-in
is scored exactly once by a model that never saw it or anything after it, and
the pooled out-of-fold predictions form one evaluation set with the full event
count. `assert_temporal_ordering` verifies this per fold, independently of the
construction.

**Metrics chosen for a review queue, not a leaderboard.** Accuracy is not
reported anywhere — at a ~6% event rate, "no bankruptcy" scores above 93% and
is worthless.

| Metric | Why it is here |
|---|---|
| ROC-AUC | Ranking quality, comparable across base rates |
| PR-AUC | Ranking quality *on the minority class*, quoted against the event rate as its baseline |
| Recall / precision at 1%, 5%, 10% alert rates | "If we review the riskiest 5% of the book, what share of next year's failures is in it?" — the question an analyst can act on |
| Brier, calibration slope | Only computed when the score *is* a probability; a heuristic ranking on a raw ratio gets `None` rather than a rescaled fiction |

**Intervals are company-clustered.** Resampling rows would treat one company's
ten filings as ten independent draws. Model comparisons use a **paired**
bootstrap on the difference, since both models score identical rows.

## 7. Results

**Panel.** 3,856 usable rows from 537 companies, 183 events across 134 companies — a 4.75% event rate. Prediction dates 2009-11-20 to 2020-01-01 (the right edge is label completeness minus the horizon).

**Folds.** Seven walk-forward folds survive the 20-training-event burn-in:

| Test year | Train rows | Train events | Test rows | Test events | Test companies |
|---|---:|---:|---:|---:|---:|
| 2013 | 641 | 24 | 455 | 9 | 381 |
| 2014 | 1,096 | 33 | 444 | 20 | 386 |
| 2015 | 1,540 | 53 | 454 | 29 | 407 |
| 2016 | 1,994 | 82 | 467 | 43 | 399 |
| 2017 | 2,461 | 125 | 453 | 22 | 402 |
| 2018 | 2,914 | 147 | 460 | 11 | 400 |
| 2019 | 3,374 | 158 | 482 | 25 | 410 |

The pooled out-of-fold evaluation set is therefore 3,215 rows and 159 events — every row scored exactly once by a model that never saw it or anything after it.

### 7.1 Model comparison (pooled out-of-fold)

| Model | Features | ROC-AUC | 95% CI | PR-AUC | Recall @5% | Recall @10% | Calib. slope |
|---|---:|---:|---|---:|---:|---:|---:|
| heuristic_leverage | 13 | 0.781 | 0.730–0.827 | 0.177 | 26.4% | 41.5% | n/a |
| heuristic_working_capital | 6 | 0.648 | 0.600–0.699 | 0.074 | 3.8% | 21.4% | n/a |
| heuristic_ebit_to_assets | 6 | 0.707 | 0.653–0.755 | 0.083 | 2.5% | 12.6% | n/a |
| heuristic_phase7_deterioration | 17 | 0.716 | 0.666–0.764 | 0.119 | 15.7% | 28.3% | n/a |
| logistic_scale | 2 | 0.567 | 0.519–0.617 | 0.055 | 1.3% | 6.9% | 0.60 |
| logistic_scale+levels | 8 | 0.629 | 0.579–0.676 | 0.076 | 8.8% | 15.1% | 0.74 |
| logistic_scale+levels+ratios | 21 | 0.739 | 0.693–0.780 | 0.126 | 20.1% | 28.9% | 0.52 |
| logistic_scale+levels+ratios+trends | 38 | 0.804 | 0.762–0.842 | 0.179 | 25.8% | 41.5% | 0.32 |
| logistic_scale+levels+ratios+trends+signals | 52 | 0.802 | 0.762–0.842 | 0.177 | 25.2% | 40.2% | 0.32 |
| **logistic (all families)** | 57 | 0.803 | 0.762–0.842 | 0.177 | 25.8% | 41.5% | 0.33 |
| logistic_all_weak_penalty | 57 | 0.792 | 0.751–0.833 | 0.169 | 23.9% | 39.6% | 0.23 |
| gradient_boosting_all | 57 | 0.887 | 0.856–0.913 | 0.297 | 37.1% | 58.5% | 0.81 |

PR-AUC baseline (the event rate) is 0.050. Brier and calibration are blank for the heuristics because they rank on a raw ratio, which is not a probability — the evaluator reports `None` rather than rescaling a ranking into a fake one.

### 7.2 Incremental value of each feature family

| Family added | ΔROC-AUC | 95% CI (paired) | Significant |
|---|---:|---|---|
| `levels` | +0.062 | +0.021 to +0.103 | **yes** |
| `ratios` | +0.110 | +0.073 to +0.148 | **yes** |
| `trends` | +0.065 | +0.024 to +0.105 | **yes** |
| `signals` | -0.001 | -0.017 to +0.013 | no |
| `quality` | +0.001 | -0.002 to +0.003 | no |

### 7.3 Robustness

| Check | Result |
|---|---|
| Held-out companies (never trained on), logistic | ROC-AUC 0.824 on 948 rows / 45 events |
| Held-out companies, gradient boosting | ROC-AUC 0.899 |
| **Cohort separability** (predict cohort, not bankruptcy) | logistic 0.792, gradient boosting 0.913 |
| Drop the strongest year (2013) | ROC-AUC 0.788 |
| Drop the weakest year (2017) | ROC-AUC 0.818 |
| 730-day horizon (separate panel) | ROC-AUC 0.777, 293 events at a 10.7% rate |

**Per-year ROC-AUC (primary model):**

| Year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Events | 9 | 20 | 29 | 43 | 22 | 11 | 25 |
| ROC-AUC | 0.944 | 0.774 | 0.771 | 0.844 | 0.696 | 0.907 | 0.753 |

**Leave-one-sector-out** (SIC major group, most event-heavy first):

| Excluded group | Events removed | ROC-AUC without |
|---|---:|---:|
| 13 | 67 | 0.816 |
| 12 | 9 | 0.797 |
| 73 | 6 | 0.794 |
| 28 | 6 | 0.801 |
| 48 | 5 | 0.801 |

### 7.4 The cohort confound, and what survives it

Restricting both training and testing to the **event cohort only** (1,592 rows, 183 events, 246 companies) makes cohort membership constant, so nothing can be gained by recognising which sample a company came from. What remains is timing: among companies that all eventually filed, can the model tell the year before the petition from the years before that?

| Model | Pooled ROC-AUC | Within-cohort ROC-AUC | Within-cohort PR-AUC |
|---|---:|---:|---:|
| `debt_to_assets` alone | 0.781 | 0.687 | 0.245 |
| Phase 7 deterioration count | 0.716 | 0.651 | 0.206 |
| **logistic (all families)** | 0.803 | 0.733 | 0.273 |
| gradient boosting | 0.887 | 0.787 | 0.343 |

Within-cohort PR-AUC baseline is 0.123.

### 7.5 What the models lean on

Top standardised coefficients (log-odds per standard deviation), primary model:

| Feature | Coefficient |
|---|---:|
| `n_deteriorating_ratios` | +0.602 |
| `signal_leverage_deterioration` | +0.493 |
| `ebit_to_assets__missing` | -0.479 |
| `ratio_ocf_to_revenue__missing` | +0.464 |
| `max_deterioration_persistence` | +0.456 |
| `ratio_current_ratio` | -0.401 |
| `trend_pct_roa__missing` | +0.358 |
| `ratio_gross_margin__missing` | -0.337 |
| `ratio_liabilities_to_assets__missing` | -0.336 |
| `trend_pct_operating_margin__missing` | -0.326 |

Intercept -4.096.

Permutation importance (ROC-AUC lost when the feature is shuffled):

| Primary model | Δ | Gradient boosting | Δ |
|---|---:|---|---:|
| `n_deteriorating_ratios` | 0.048 | `log_total_assets` | 0.100 |
| `signal_leverage_deterioration` | 0.029 | `ratio_liabilities_to_assets` | 0.019 |
| `max_deterioration_persistence` | 0.026 | `ebit_to_assets` | 0.018 |
| `ratio_ocf_to_revenue__missing` | 0.024 | `ratio_debt_to_assets` | 0.007 |
| `ebit_to_assets__missing` | 0.017 | `fcf_to_assets` | 0.005 |
| `trend_pct_roa__missing` | 0.015 | `ratio_interest_coverage` | 0.003 |

**Feature missingness by family** (mean share of rows where the feature is `None`):

| `levels` | `quality` | `ratios` | `scale` | `signals` | `trends` |
|---:|---:|---:|---:|---:|---:|
| 21.0% | 0.1% | 25.3% | 20.0% | 8.0% | 32.6% |

### 7.6 Reading these results

Four conclusions, in the order they change what anyone should believe.

**1. The pooled ROC-AUC is inflated by the sampling design, and the amount is
measured.** The cohort-separability probe asks a model to predict *which cohort
a company was drawn from* instead of bankruptcy. The primary model scores 0.792
at that task — essentially its 0.803 bankruptcy score — and gradient boosting
scores 0.913, *higher* than its 0.887 bankruptcy score. The comparison cohort
came from SEC's current ticker file, so it survived to today by construction;
the event cohort was selected on having failed. Much of what looks like risk
discrimination is the model recognising the sample.

Permutation importance corroborates it directly: gradient boosting's single
most important feature is `log_total_assets`, at five times the weight of
anything else. Size does genuinely predict failure, but a gap that large
between a size feature and every financial ratio is the signature of two
differently-sized cohorts, not of a leverage signal.

**2. What survives the confound is real, and it is where the modelling layer
earns its place.** Inside the event cohort — where every company eventually
files, so cohort membership carries no information — the primary model reaches
0.733 and gradient boosting 0.787 against a 12.3% base rate. That is the honest
number for the harder and more product-relevant question: *given a company you
already consider risky, is this the year?*

It also **reverses the baseline comparison**. Pooled, `debt_to_assets` alone
(0.782) is statistically indistinguishable from the 57-feature model (0.803),
which would suggest the ML layer adds nothing. Within the cohort, the baseline
falls to 0.687 while the model holds 0.733 and gradient boosting reaches 0.787.
The pooled view flattered the single ratio because leverage is also a good
cohort marker.

**3. Phases 5, 6 and 7 each contribute measurable predictive information — but
the Phase 7 *signals* do not add anything beyond the trends they summarise.**
The ablation is unambiguous: `levels` +0.062, `ratios` +0.110 and `trends`
+0.065 are each significant on a paired bootstrap; `signals` (-0.001) and
`quality` (+0.001) are not. That is the expected result rather than a
disappointment — a signal code is a coarsening of the trend that raised it, so
once the trend is in the model the indicator is redundant. It remains valuable
as *explanation* for an analyst; it is simply not additional evidence for a
model.

**4. The probabilities are not yet usable as probabilities.** The primary
model's calibration slope is 0.33 — far below 1, the signature of predictions
that are too extreme. Gradient boosting is materially better at 0.81. Until
this is addressed, the output should be consumed as a **ranking**, which is
what the alert-rate metrics measure and what a watchlist needs, and
[D-010](decision_log.md)'s prohibition on quoting it as a probability is doing
real work rather than being merely cautious.

**On the other robustness checks.** Held-out companies score *higher* than the
pooled figure (0.824 logistic, 0.900 gradient boosting), so the models are not
memorising individual companies — consistent with conclusion 1, since
cohort-level characteristics generalise to new companies of the same cohort.
Per-year ROC-AUC ranges 0.696–0.944 across 9–43 events per year; dropping the
best year gives 0.788 and the worst 0.818, so no single year carries the
result. Excluding SIC 13 (oil and gas), which supplies 67 of the 159 pooled
events, *raises* ROC-AUC to 0.816 — the result is not an energy-sector story.
The 730-day panel gives 0.777, close to the primary figure.

**Why the primary model remained the logistic one, and why it no longer does**
([D-028](decision_log.md), §23; **superseded by [D-034](decision_log.md)**).
Phase 8 kept logistic regression primary although gradient boosting scored
higher on every discrimination metric, on four grounds: (a) the gap is largest
precisely where the cohort confound is largest, so boosting is the *less*
trustworthy of the two on this corpus; (b) its dominant feature is company
size, which is the confound's own marker; (c) the logistic model's coefficients
are directly readable and their signs are economically sensible —
`n_deteriorating_ratios` +0.60, `signal_leverage_deterioration` +0.49,
`ratio_current_ratio` -0.40; and (d) with 159 pooled events the simpler model
is the one whose behaviour can be defended line by line. This section also
named the test that would overturn it: "the within-cohort gap (0.787 vs 0.733)
is the strongest argument for revisiting that choice."

**That test was run in Phase 10 and it overturned the choice.** Phase 9 had
already retired ground (c) by giving the boosting model exact TreeSHAP
attribution in the same explanation schema, and (d) is a preference. Of the two
empirical grounds, (a) survives only in direction — boosting's lead narrows
from +0.084 pooled to +0.054 within the event cohort, with the paired,
company-clustered interval still excluding zero — and (b) is **false in the
frame that matters**: removing the `scale` features costs boosting
−0.011 [−0.023, +0.003] within the event cohort, and its leading features there
are `ratio_liabilities_to_assets`, `ebit_to_assets` and `ratio_current_ratio`,
with size fifth and sixth at ~5% each. In that same frame three of the
*logistic* model's top seven features are `__missing` indicators. Gradient
boosting is now the primary model; the logistic model is retained as the
measured comparator, and every "primary model" coefficient quoted in this
document describes it in that role. Full evidence in
[D-034](decision_log.md).

**A caveat on the primary model's own importances.** Four of its top ten
permutation-importance features are `__missing` indicators, and heavy
missingness in the `trends` family (up to 69% for `trend_pct_debt_to_equity`)
means the logistic model is partly learning *which ratios could be computed*.
That is legitimate information available at the cutoff — filings do get harder
to read as companies deteriorate — but it is a data-availability signal rather
than a financial one, and it is a specific thing for Phase 9 to look at.

> The authoritative record is `data/processed/phase8/model_results.csv` and
> `model_summary.json`; every figure above is read from them.

## 8. Limitations

Stated plainly, because several of them bound what any conclusion here can
mean.

1. **Survivorship in the comparison cohort — the largest limitation, and it is
   quantified.** The cohort was drawn from SEC's *current* ticker file, so every
   company in it survived to today by construction; companies that delisted for
   any reason are absent. The `cohort_separability` diagnostic measures the
   consequence: a model can predict **cohort membership** at 0.792 (logistic)
   and 0.913 (gradient boosting) ROC-AUC — at or above their bankruptcy scores.
   The pooled figures in §7.1 should therefore be read as an upper bound, and
   §7.4's within-cohort figures (0.733 / 0.787) as the defensible ones. Fixing
   this needs a point-in-time negative universe — companies that were *filing
   at time T*, whether or not they still exist.

   > **Phase 9 built it and measured the gap this limitation was hiding.** Of
   > the 16,008 companies that filed an annual report between 2009 and 2020,
   > only **3,625 (22.6%)** appear in the current ticker file — so this cohort
   > was drawn from under a quarter of the real population, and from the
   > quarter selected for survival. Phase 9 also found that *every* property of
   > the sampling design is at least as predictable as the label, and that the
   > `trend_pct_*` features feeding this model are unbounded (to ±42,000),
   > which is much of why calibration fails. See
   > [model_evaluation_explainability.md](model_evaluation_explainability.md).
2. **BRD covers only large public filers.** A `0` means "no *large public*
   bankruptcy was recorded", not "nothing bad happened". The label noise is
   confined to the negative class and is not correctable with the sources this
   project has.
3. **A 365-day horizon cannot reach ~20% of events.** Those companies' last
   annual filing predates the petition by more than a year. Their rows are
   correctly labelled `0`; the cost is fewer positives, not wrong ones.
4. **Usable prediction dates end at 2020-01-01.** Label completeness is the
   binding constraint. Nothing here says anything about 2021 onwards.
5. **Events per variable is low.** 159 pooled out-of-fold events against 57
   features is roughly 2.8 events per variable, well under the conventional 10,
   which is why the primary model is heavily regularised (`C=0.1`) and why every
   comparison carries a company-clustered interval. The weak-penalty sensitivity
   (`C=1.0`, 0.793) scores slightly *below* the primary, so the shrinkage is not
   what is holding the linear model back.

6. **Probabilities are not calibrated.** Slope 0.33 for the primary model. Use
   the output as a ranking, not a probability, until Phase 9 addresses this.

7. **Heavy missingness in the trend family.** Up to 69% of rows lack
   `trend_pct_debt_to_equity`, because a trend needs three consecutive
   calculated periods. The logistic model's reliance on `__missing` indicators
   is a direct consequence.
8. **Events cluster in macro cycles and in one sector.** SIC 13 supplies 67 of
   159 pooled events; leave-one-sector-out shows the result survives its
   removal (0.816), so this is a composition note rather than a dependence.
9. **The model has seen no post-2020 regime.** COVID-era and rising-rate-era
   dynamics are outside the training span, and label completeness means they
   cannot be added from this source.
10. **Phase 7's false-positive validation does not carry over.** Its "no false
   positive across 12 reports" covered 37 signals from single-filing input;
   the windowed multi-filing path produces far more. Re-validation is
   outstanding.
11. **XBRL scale errors exist in the source.** Tesla's own FY2016 10-K tagged
   `DebtCurrent` as 1,114,652 where every later filing reports 1,114,652,000 —
   a 1000× filer error that the as-filed rule faithfully preserves. §10
   records what is and is not done about it.

12. **`MULTI_DIMENSION_DETERIORATION` and several signal codes fire rarely**,
    so their indicator features are near-constant and the ablation cannot say
    much about them individually — only that the family as a whole adds nothing
    beyond `trends`.

## 9. Restatements and data quality

`scripts/evaluate_multi_filing.py` also delivers Phase 8's prerequisite B — the
first measurement of the multi-filing point-in-time path on real data. On the
same 12-company golden corpus, it reproduces the published single-filing
figures exactly and shows what the multi-filing path changes:

| | Single filing | Multi-filing (`as_of`) |
|---|---:|---:|
| Filings resolved | 12 | **153** (116 skipped: 112 no XBRL facts, 4 no periods resolved) |
| Ratio slots calculated | 362 / 598 — 60.5% | 1,953 / 2,405 — **81.2%** |
| Conclusive trend directions | 63 / 156 — 40.4% | 143 / 156 — **91.7%** |
| `INSUFFICIENT_DATA` dimensions | 21 / 60 | **0 / 60** |
| Signals fired | 37 | 153 |

The 60.5% and 40.4% figures match M-2 and M-3 exactly, which is what
validates the harness. Note the signal count more than quadruples: Phase 7's
"no false positive across 12 reports" was a claim about 37 signals and is
listed in §8 as outstanding re-validation, not carried forward.


`scripts/evaluate_multi_filing.py` (M-4) classifies every restatement the
multi-filing path surfaces, using the provenance the canonical facts already
carry rather than counting them and stopping:

| Category | What it means |
|---|---|
| `immaterial` | The two values agree within 0.1% — rounding or presentation, matching `resolver._values_agree`'s own tolerance |
| `amendment` | One side comes from a 10-K/A, i.e. a correction to the original filing |
| `origin_change` | One side was `REPORTED` and the other `DERIVED` — the filer started or stopped tagging a concept, not necessarily a changed number |
| `tag_change` | Both reported, from different XBRL tags — a re-presentation |
| `same_tag_restatement` | Same tag, materially different value — a genuine restatement by the filer |

Measured over the 12-company golden corpus (`qm04_restatements.csv`), the 453
differences classify as:

| Category | Count | Share |
|---|---:|---:|
| `same_tag_restatement` | 270 | 60% |
| `immaterial` | 110 | 24% |
| `amendment` | 52 | 11% |
| `tag_change` | 21 | 5% |
| `origin_change` | 0 | 0% |

The genuine restatements are mostly small — median relative difference 1.5%,
75th percentile 5.2%, and only 16% exceed 10% — but the tail is large: the
biggest exceed 100% of the original value (Expand Energy's FY2017 net income
moves from +949M to -505M across filings). The practical consequence for Phase 8 is that
[D-008](decision_log.md)'s as-filed rule does real work: a naively-built
"latest value" dataset would differ from the point-in-time one in hundreds of
places, several by more than 100% of the original value.

> **Phase 9 found a second, distinct data defect in the same area.** Explaining
> the panel's highest-scoring observation traced it to `revenue` resolving from
> the `Revenues` tag (5,607,000) rather than `SalesRevenueGoodsNet`
> (1,166,882,000) for MATERION FY2013 — a 208× understatement that produces a
> gross margin of 33.5. Unlike the Tesla case this is a **resolution** problem
> rather than a filer error, it affects 17 companies, and it is a candidate
> Phase 5 fix rather than something to document and live with. See
> [model_evaluation_explainability.md §9](model_evaluation_explainability.md).

**On the Tesla-style scale error:** it is a genuine defect in the filer's XBRL,
not in this pipeline, and no scale-detection heuristic is added here.
`validation.py`'s existing checks do not catch it (short-term debt is not in
the balance-sheet identity, and $1.1M is not implausible against $22B of
assets). Adding a magnitude-consistency rule is Phase 5 work with its own
false-positive risk, and it is recorded as a recommendation rather than
implemented speculatively mid-phase.
