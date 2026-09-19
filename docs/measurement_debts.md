# Measurement Debts — Phase 17

| | |
|---|---|
| **Status** | Complete — four of the five debts paid, the fifth blocked on a credential and reported as unpaid |
| **Date** | 2026-09-19 |
| **Decisions** | [D-053](decision_log.md) health re-run, and two stated biases were wrong · [D-054](decision_log.md) eligibility-matched negative universe · [D-055](decision_log.md) recall relative to the sweep |
| **Code** | `modeling/dataset.py` (`analyse_company_filings`), `modeling/model.py` (`align_columns`) |
| **Scripts** | `phase17_health_rerun.py` · `phase17_eligibility_matched.py` · `phase17_recall.py` · `phase17_assumptions.py` |
| **Requirements** | QM-04 (recall) · A-09, A-11, A-13, A-14 |
| **Related** | [combined_assessment.md](combined_assessment.md) · [model_evaluation_explainability.md](model_evaluation_explainability.md) · [nlp_risk_signals.md](nlp_risk_signals.md) · [assumptions.md](assumptions.md) |

> **This phase exists because [D-045](decision_log.md) refused to spend three
> phases on work the project had not asked for.** "Consolidate the evaluation
> suites" was replaced by the five measurements earlier phases had deferred
> *and named*. Four are now paid. Two of them corrected claims this project had
> already published, and one produced the first bankruptcy figure here that is
> not beaten by a model of its own sampling design.

---

## 1. What was owed

[D-045](decision_log.md) listed five debts. Each had been named by the phase
that deferred it, which is why they were worth a phase: a limitation somebody
wrote down is a limitation somebody could still measure.

| # | Debt | Owed since | Status |
|---|---|---|---|
| 1 | Re-run Phase 7 for real over the Phase 11 corpus | Phase 11 | ✅ Paid — [§2](#2-debt-1--the-health-layer-run-for-real) |
| 2 | Match the negative universe on BRD's *eligibility* conditions | Phase 9 ([D-032](decision_log.md)) | ✅ Paid — [§3](#3-debt-2--the-eligibility-matched-negative-universe) |
| 3 | Take the live synthesis sample past n=12, on a second provider | Phase 12 ([D-044](decision_log.md)) | ⛔ **Not paid** — [§5](#5-debt-3--the-one-that-is-not-paid) |
| 4 | Label Phase 10's recall pool | Phase 10 | ✅ Paid — [§4](#4-debt-4--recall-has-a-number) |
| 5 | Close A-09, A-11, A-13, A-14 | Phase 1 | ✅ Paid — [§6](#6-debt-5--four-assumptions-closed) |

---

## 2. Debt 1 — the health layer, run for real

Phase 11 never ran Phase 7. It rebuilt each health report from the Phase 8
feature encoding of one, and that encoding had already flattened `IMPROVING`,
`STABLE` and `MIXED` into a single not-deteriorating flag. Phase 11 disclosed
this — and then stated, without testing, which way each affected rule was
biased.

**The harness is the reason the answer is readable.** Both arms run in one
process, over one corpus, with the model layer **fitted once and shared**, and
the reconstruction arm imports Phase 11's own `_health_report` unmodified. So
every difference below is caused by the health reports and by nothing else.

### 2.1 The reconstruction was perfectly faithful — to exactly what it claimed

All 202 corpus filings produced a real report; none was dropped.

| Reconstructed → real | Slots |
|---|---:|
| `deteriorating` → `deteriorating` | **522** |
| `insufficient_data` → `insufficient_data` | **122** |
| `stable` → `improving` | 242 |
| `stable` → `mixed` | **96** |
| `stable` → `stable` | 28 |

On the three-way distinction every cross-layer rule reads, the round trip is
**exact — 644 of 644, zero errors**. Every disagreement sits inside the
collapsed class. That is a real vindication of how Phase 11 described its own
shortcut.

### 2.2 Two of the three stated biases were wrong

| Phase 11 said | Measured |
|---|---|
| `MODEL_ELEVATED_HEALTH_QUIET` is an **upper bound** | **Vacuous** — it fires 0 times, in both arms, in both cohorts |
| `DIMENSION_DISAGREEMENT` is biased **upward** | **Backwards** — 102 firings reconstructed, **110** real |
| Health corroboration is a **lower bound** | **True, and it does not help** |

`DIMENSION_DISAGREEMENT` fires whenever a material model driver and the health
layer disagree *in either direction*. Reading `MIXED` as `STABLE` therefore
suppresses some firings and creates others, and on this corpus the second
effect is larger. The direction had been inferred from the shape of the
encoding rather than from running the rule.

The corroboration claim is the one worth dwelling on. Counts rose as predicted
— and the new firings landed almost entirely in the **comparison** cohort, so
every health-based lift *fell*:

| Rule | Lift (reconstructed) | Lift (real) |
|---|---:|---:|
| `MODEL_AND_HEALTH` | 1.538 | **1.444** |
| `HEALTH_AND_NARRATIVE` | 2.158 | **2.078** |

Correcting a bias that was disclosed as working *against* the layer made the
layer look worse.

### 2.3 One published interval moves, and it moves against the layer

| Selector | Δ precision vs model top-k (reconstructed) | Δ precision (real) |
|---|---|---|
| `MODEL_AND_HEALTH` | −0.033 [−0.065, **0.000**] | −0.032 [−0.065, **−0.006**] |
| `HEALTH_AND_NARRATIVE` | −0.198 [−0.306, −0.074] | −0.207 [−0.312, −0.087] |

`MODEL_AND_HEALTH`'s interval no longer touches zero. Spending an alert budget
on model-and-health agreement is now *measurably* worse than spending it on the
model's own top-k — a conclusion the reconstruction could not reach.

**Everything not touching health is identical to four decimals**: all three
single-layer baselines, `ALL_LAYERS_ELEVATED` (0.930, overlap 0.63),
`MODEL_AND_NARRATIVE` (+0.026 [−0.056, +0.122]), `NARRATIVE_SELF_CONTRADICTION`
(2.04×) and `ABSENCE_NOT_OBSERVED` (1.50). That is both the check that the
harness works and the answer to the question the debt was really asking:
**Phase 11's headline does not depend on the shortcut it took.**

---

## 3. Debt 2 — the eligibility-matched negative universe

[D-032](decision_log.md) ended by naming its own successor. It had built the
point-in-time negative universe, found it changed nothing, and diagnosed the
cause as **eligibility rather than survival**: BRD records only large public
bankruptcies, so the event cohort is large by construction.

**The rule, from BRD rather than from the data.** Total assets of at least
**$100M in 1980 dollars**, CPI-adjusted per row-year — $260M in 2009 rising to
$314M in 2020. BRD's other condition (a 10-K within ~3 years before the
petition) is satisfied by construction here, since every row *is* an annual
filing, and is therefore not implemented rather than silently skipped.

**Applied to both cohorts.** Phase 9's size-matching kept every event row and
trimmed only comparisons, which preserves the very asymmetry that is the
confound. Eligibility is a property a row either has or has not, so **125 event
rows were dropped too**.

### 3.1 The size gap closes

| Panel | Event median log-assets | Comparison | Gap |
|---|---:|---:|---:|
| Point-in-time | 21.24 | 18.56 | **14.53×** |
| Eligibility-matched | 21.30 | 21.34 | **0.96×** |

Comparison rows 2,341 → 932; event rows 1,592 → 1,467; 102 rows dropped for
having no resolved total assets, because a row that cannot be *shown* to meet
the bar must not be assumed to.

### 3.2 And so does the confound — for one model family

| Panel / model | Bankruptcy ROC-AUC | Cohort separability | Gap |
|---|---:|---:|---:|
| Point-in-time, logistic | 0.797 [0.754, 0.838] | 0.843 | +0.047 |
| Size-matched, logistic | 0.781 [0.735, 0.825] | 0.819 | +0.038 |
| **Eligibility-matched, logistic** | **0.817 [0.778, 0.851]** | **0.817** | **+0.0001** |
| Point-in-time, boosting | 0.894 [0.864, 0.921] | 0.916 | +0.021 |
| Size-matched, boosting | 0.843 [0.811, 0.873] | 0.878 | +0.035 |
| **Eligibility-matched, boosting** | 0.839 [0.807, 0.867] | 0.860 | +0.021 |

**For the logistic hazard model the confound is gone**, and its discrimination
*rose* while the probe fell. This is the first bankruptcy figure in the project
that a model of the sampling design does not match or beat.

**For boosting the gap does not move** (+0.021 → +0.021) while its AUC drops
0.894 → 0.839 — precisely the pattern [D-028](decision_log.md)(a) predicted and
[D-034](decision_log.md) tested another way.

> **This does not reopen [D-034](decision_log.md).** These are two independent
> walk-forward runs, not a paired company-clustered test of the *difference*.
> D-034's paired within-cohort measurement stays the basis for the
> primary-model choice; a paired re-run on this panel is the obvious next test,
> not a conclusion available today.

### 3.3 A latent bug, found by running something new

Phase 9's cohort probe built its train and test design matrices independently
and padded the test matrix up to the training width. Indicator columns are
derived from whichever rows `design_matrix` is handed, so the two can disagree
in **either** direction — and this panel was the first whose test rows were the
sparser, raising `negative dimensions are not allowed`. The correct pad-or-trim
helper already existed on the real training path; it is now public
(`model.align_columns`), the probe uses it, and four tests cover both
directions. **Phase 9's published numbers are unaffected and were reproduced to
four decimals in the same run.**

---

## 4. Debt 4 — recall has a number

Phase 10 built the recall harness and refused to report a figure, because the
pool was unlabelled. All 150 candidates are now labelled in
`evaluation/phase10_recall_labels.csv`, with a note on every judgement call.

> **Recall = 8 / 21 = 38.1% [20.8%, 59.1%]**, *relative to the sweep's reach*.
> The denominator is the true instances an over-broad keyword matcher found. A
> disclosure phrased in words neither matcher contains is invisible to both, so
> this is an upper bound on true recall and must never be quoted without that
> clause.

Of 150 candidates: 21 `true_signal`, 89 `boilerplate`, 40 `unrelated`.

### 4.1 Three findings that matter more than the headline

**The misses are concentrated, and the catalog disagrees with itself.** 16 of
the 21 true instances are `asset_impairment` (6 caught). Two sentences
reporting an impairment charge's effect on the effective tax rate *were*
caught, while "*Excluding the $2.1 billion non-cash, pre-tax goodwill
impairment charge recorded during 2011*, our operating expenses increased…" was
not. That is one editable line, which is the property a rules layer is for. It
is recorded rather than fixed, for the reason Phase 10 gave about its own
precision failures: repairing first would leave the number describing something
that was never shipped.

**The pool independently confirms precision: 8 of 8.** Every row the catalog
claimed, the labeller agreed with — and this pool came from a *different*
matcher, so it is not the precision sample re-scored.

**The pool cannot speak about the codes that matter.** Six of twelve codes have
zero true instances in it, including `bankruptcy_contemplated` and
`delisting_notice` — two of the three highest-lift codes Phase 10 measured at
13/13 precision.

| Code | True instances | Caught | Recall |
|---|---:|---:|---|
| `asset_impairment` | 16 | 6 | 0.375 [0.185, 0.614] |
| `dividend_suspension` | 2 | 0 | 0.000 [0.000, 0.658] |
| `debt_restructuring` | 1 | 0 | 0.000 [0.000, 0.794] |
| `going_concern_doubt` | 1 | 1 | 1.000 [0.207, 1.000] |
| `credit_rating_downgrade` | 1 | 1 | 1.000 [0.207, 1.000] |
| six other codes | 0 | 0 | — |

So **38.1% is substantially a statement about impairment detection wearing the
catalog's name.** The fix is a larger pool weighted towards the statutory
disclosures, which needs a re-run of the sweep rather than a relabelling.

---

## 5. Debt 3 — the one that is not paid

[D-044](decision_log.md) added a second provider behind the synthesis seam and
observed that a two-model comparison had become a one-command measurement. It
still is. **It was not run, because there is no credential to run it with:**
`LLM_PROVIDER` and `LLM_API_KEY` in `.env` are both empty, and the Gemini key
that arrived mid-Phase-12 is gone.

What that leaves standing, unchanged: the live sample is **12 drafts, 11
accepted (91.7%)**, 95% interval ≈ 62%–100%, on one provider.
[A-16](assumptions.md) stays **partially validated**. The Anthropic client has
still never made a call.

This is reported rather than substituted. Re-running the fault-injection
harness, or the same provider on a new key, would produce a number — and it
would not be the measurement that was owed, which is specifically *does a
second model behave the same way against the same validator*.

**To pay it:** set `LLM_PROVIDER` and `LLM_API_KEY`, then
`uv run python scripts/phase12_synthesize.py`. Nothing else is missing.

---

## 6. Debt 5 — four assumptions closed

These four were singled out by [D-045](decision_log.md) as "the ones that
decide whether the predictive layer means anything". All four had sat at
**Open** since Phase 1 with a validation plan and no measurement.

### A-09 — feature reproducibility → **Superseded, with the residual measured**

A-09 assumed *two* feature definitions — a third-party training set's and SEC
XBRL's — that would have to be made equivalent. [D-013](decision_log.md) chose
a self-built corpus instead, so `modeling/features.py` is the only definition
and runs at both training and inference. **There is no second definition to
skew against**; the assumption's original form is dissolved by a decision, not
by a measurement.

Its residual is real and temporal rather than definitional: the same fiscal
period, resolved from a *later* filing, does not always give the same number.
Phase 8's QM-04 measured exactly this — 453 restatements across 153 filings:

| | Absolute relative difference |
|---|---:|
| Median | 0.8% |
| p75 | 4.8% |
| p90 | **20.0%** |
| Share above 5% | **23.6%** |
| Share above 20% | 10.2% |

[D-008](decision_log.md) and [D-026](decision_log.md) answer this by
construction (as-filed, point-in-time). The table is the size of what that
choice avoids. *Not measured:* propagation from restated facts through to ratio
and feature values.

### A-11 — bankruptcy as a distress proxy → **Validated as a proxy, with a measured miss rate**

The proxy fails in one direction: a company can be in severe distress, disclose
it plainly, and never file. Those filings are labelled 0, so the model is
trained to call them safe. Measured on the 238-filing Phase 10 corpus, using
only **asserted** disclosures:

| Disclosure | Filings | Followed by a petition | **Not followed** |
|---|---:|---:|---:|
| `going_concern_doubt` | 32 | 27 (84.4%) | **5** |
| `delisting_notice` | 14 | 12 (85.7%) | 2 |
| `bankruptcy_contemplated` | 5 | 4 (80.0%) | 1 |
| `debt_default_or_acceleration` | 16 | 12 (75.0%) | 4 |
| `debt_restructuring` | 65 | 48 (73.8%) | 17 |
| `covenant_breach` | 37 | 26 (70.3%) | 11 |
| **Any of the above** | **92** | **59 (64.1%)** | **33** |

Even substantial-doubt language — about the strongest independent distress
marker available here — is followed by a petition only 84% of the time, and a
third of all distress disclosures are not followed at all.

> **The corpus is year-matched at a base rate of 0.496, so these shares are far
> higher than any portfolio's.** That makes the *direction* the finding, not the
> level: bankruptcy-within-365-days is a strict subset of credit distress, and
> the gap is the label's, not the model's.

### A-13 — enough events for an out-of-time test → **Validated pooled, invalidated per fold**

| Panel | Rows | Events | Folds | Events/fold (min) | Median | Folds < 10 events |
|---|---:|---:|---:|---:|---:|---:|
| Phase 8 survivor | 3,856 | 183 | 7 | **9** (2013) | 22 | 1 |
| Phase 9 point-in-time | 3,933 | 183 | 7 | **9** (2013) | 22 | 1 |

Per-fold counts run 9 → 43. A fold with nine events cannot support a per-fold
metric, and none is reported: [D-027](decision_log.md) pools the out-of-fold
scores and intervals are bootstrapped on the pool, company-clustered. Those
intervals are **0.056 to 0.090 wide**, which is the honest expression of the
event count — wide enough that differences below ~0.05 are not readable, which
is exactly why [D-034](decision_log.md) used a *paired* test rather than
comparing two intervals.

### A-14 — base-rate framing → **Validated, decisively**

| Frame | Base rate |
|---|---:|
| Phase 10 narrative corpus (year-matched) | 0.496 |
| Phase 11 assessment corpus | 0.495 |
| Eligibility-matched panel | 0.081 |
| Size-matched panel | 0.083 |
| Point-in-time panel | 0.049 |
| **Real world** — BRD petitions per SEC annual filer, 2009–2020 | **0.0039** |

367 petitions over 93,394 filer-years, both sides restricted to companies that
filed an annual report within three years, which is BRD's own "public"
condition. **The training base rate is 12× to 126× the real-world rate**,
depending on which corpus is quoted.

That is A-14 exactly as written, with numbers. The framing it asked for is
already enforced in the type rather than in prose:
[D-033](decision_log.md) puts `score_percentile` beside `score` and attaches a
`NOT_CALIBRATED` caveat automatically to any model whose calibration slope
falls outside [0.8, 1.25].

*Caveat on the real-world figure:* it is the rate among **all** annual filers.
BRD records only large bankruptcies, so the rate among BRD-*eligible* filers is
higher — by roughly the reciprocal of the eligible share, which §3 measures at
about 40% of comparison rows.

---

## 7. What this phase changed in the codebase

Small, and deliberately so — this was a measurement phase, not a feature phase.

- **`modeling/dataset.py`** — the point-in-time loop is extracted as
  `analyse_company_filings`, returning a `FilingAnalysis` per filing.
  `build_company_observations` becomes a labelling and encoding layer on top.
  Nothing else needed to change for a caller to get a *real* Phase 7 report
  without re-implementing the only place the leakage contract is enforced.
- **`modeling/model.py`** — `_align_columns` becomes public `align_columns`
  (§3.3), with four new tests.
- **`evaluation/phase10_recall_labels.csv`** — 150 hand labels, committed.
- 758 tests pass (up from 754), 94% coverage, `ruff` and `ruff format` clean.

---

## 8. Limitations

1. **Debt 3 is unpaid** (§5). The live synthesis evidence is still 12 drafts
   from one provider, and no amount of the rest of this phase changes that.
2. **The recall pool is blind to the high-lift codes** (§4.1). Six of twelve
   codes have no true instance in it. The headline is dominated by
   `asset_impairment`.
3. **Eligibility matching is one-dimensional.** Industry separability was
   measured at 0.87–0.95 in Phase 9 and is *not* matched here. Adding a second
   matching dimension to a 932-row comparison cohort trades a measured confound
   for an unmeasured sample-size problem, so it is named rather than taken.
4. **Boosting's pooled metrics remain unquotable** as bankruptcy prediction, on
   all three panels. Only the logistic model's eligibility-matched figure
   survives its own cohort probe.
5. **A-09's residual is fact-level only.** How a 20% restatement propagates
   into a ratio, a trend direction and a feature is not measured.
6. **A-11's rates sit on a year-matched corpus.** The direction of the label's
   miss is corpus-independent; the size of it is not.
7. **The health re-run covers the Phase 11 corpus, not the whole panel.** 202
   filings, the ones carrying a narrative layer. The Phase 8 panel's other
   ~3,700 rows still reach the model through the feature encoding, which is
   what they are *for* — but no equivalent fidelity check was run on them.
8. ~~**17 pre-existing `mypy` errors remain** in `synthesis/client.py`,
   `synthesis/prompt.py`, `workspace/build.py`, `assessment/evidence.py` and
   `assessment/models.py` — all in optional-dependency paths, none in code this
   phase touched. Left for Phase 19.~~ **Cleared in Phase 19
   ([D-057](decision_log.md)): `mypy --strict` is clean on 79 source files.**
   Fifteen were genuine typing defects rather than optional-dependency noise —
   including a loop variable reused across two different finding types in
   `prompt.py`, and three uses of `value and str(value)` whose type is the union
   of `str` with every falsy member of the input. Two were uninstalled-library
   noise and joined the `[[tool.mypy.overrides]]` block that already existed for
   that class. No behaviour changed; 758 tests still pass.
