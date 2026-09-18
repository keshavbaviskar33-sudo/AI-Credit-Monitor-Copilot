# Model Evaluation, Explainability & Trustworthiness — Phase 9

| | |
|---|---|
| **Status** | Complete — findings are substantially negative, and they are the deliverable |
| **Date** | 2026-09-18 |
| **Decisions** | [D-029](decision_log.md) explanation schema · [D-030](decision_log.md) attribution method · [D-031](decision_log.md) dimension grouping · [D-032](decision_log.md) point-in-time universe · [D-033](decision_log.md) ranking not probability |
| **Code** | `src/credit_risk_copilot/explain/` |
| **Scripts** | `phase9_pit_universe.py` → `phase9_pit_corpus.py` → `phase9_pit_panel.py`; `phase9_explain.py`, `phase9_diagnostics.py`, `phase9_stability.py` |
| **Related** | [predictive_model.md](predictive_model.md) · [architecture_audit.md](architecture_audit.md) · [financial_health.md](financial_health.md) |

> **The headline, stated before anything else.** Asked to predict properties of
> its own sampling design instead of bankruptcy, the same model and the same
> features score **as well or better on every one of them**. Phase 8's pooled
> ROC-AUC of 0.803 (logistic) and 0.887 (gradient boosting) must not be quoted
> as bankruptcy-prediction performance.

---

## 1. Executive summary

Phase 9 set out to explain the Phase 8 model and ended up establishing, with
measurements rather than caveats, that a large part of what it had learned was
the shape of the sample. Seven findings, in order of how much they change what
the project may claim.

**1. Every sampling-design property is at least as predictable as the label.**
Substituting a property of the corpus for the bankruptcy target, keeping
everything else identical:

| What the model is asked to predict | Logistic | Gradient boosting |
|---|---:|---:|
| **Bankruptcy within 365 days** (the actual task) | **0.803** | **0.887** |
| Which cohort the company was sampled from | 0.817 | 0.930 |
| Whether the company is data-rich (`quality` family withheld) | 0.952 | 0.946 |
| Whether it is an energy company (SIC 13) | 0.866 | 0.947 |
| Whether it is large (`scale` family withheld) | 0.821 | 0.872 |

**2. The survivorship gap is enormous — and fixing it changes nothing.** Of the
16,008 companies that filed an annual report 2009–2020, only **3,625 (22.6%)**
appear in SEC's current ticker file, the frame Phase 8 sampled from. The
point-in-time cohort was built and the panel rebuilt on it. Performance moved
by less than its confidence interval (logistic 0.803 → 0.797) and cohort
separability **rose** (0.792 → 0.843).

**The diagnosis was wrong, and the corrected one is more useful.** BRD records
only large public bankruptcies, so the event cohort is large by construction —
median log-assets 21.24 against 19.94 for the survivor comparison cohort and
**18.56** for the point-in-time one. Sampling from the real population widened
the gap from 3.7× to 14.5×. **The confound is eligibility, not survival.** A
size-matched variant narrows separability (0.843 → 0.819) without closing the
gap. §13 has the full result; the next step is an *eligibility-matched* negative
universe, which is a narrower problem than the one Phase 8 handed forward.

**3. The primary model draws 44% of its attribution from missingness, and
missingness is not a distress signal here.** Missing-feature count correlates
−0.385 with company size, −0.471 with history depth, −0.223 with year — and
**−0.066 with the label**. Events have *fewer* missing features (8.8) than
non-events (11.8). Withholding the indicators costs only 0.021 ROC-AUC.

**4. Explanations are stable; the two models' explanations disagree.** Grouped
attribution holds its ordering across macro eras (Spearman 0.83–0.97) and
across 60 company-level bootstrap refits (top-group agreement 98.3%). But the
logistic and boosting models rank the financial dimensions **negatively
correlated** with each other (Spearman −0.33): they are not explaining the same
phenomenon.

**5. SHAP is unnecessary for the model that ships.** For the logistic pipeline
the exact decomposition `coefficient × scaled value` reconstructs the model's
own log-odds to **3.6e-15**. SHAP is retained only for the tree challenger,
where no closed form exists ([D-030](decision_log.md)).

**6. Explaining individual predictions found a real Phase 5 defect.** The
highest-ranked observation in the entire panel is a **false positive caused by
a revenue-resolution error**, traced through the provenance chain to an XBRL
tag-priority problem affecting 17 companies (§9).

**7. The misses are not a data problem.** Of 93 events outside the top decile,
**83 had complete data**. Better extraction would not have caught them.

**Is the predictive layer a trustworthy foundation for Phase 10+?** The
*explanation layer* is — tested, traced to filings, and stable. The *model's
pooled metrics* are not, and three separate sampling constructions failed to
make them so. The **within-event-cohort** figures (logistic 0.733, boosting
0.787) remain the only defensible performance claim the project can make.
§14 lists what has to change, in order.

## 2. What was analysed

The Phase 8 artifacts, unchanged: the primary `logistic_scale+levels+ratios+trends+signals+quality`
(97 columns: 57 features + 40 missingness indicators) and the
`gradient_boosting_all` challenger, both re-fitted per walk-forward fold so
every attribution comes from a model that never saw the row it explains.

No Phase 8 code was modified. Phase 9 adds `explain/` and six scripts.

## 3. The explanation layer

```text
        Model (logistic | boosting | future)
                    |
            Attributor  (adapters.py)
      exact linear contributions | TreeSHAP
                    |
        ModelExplanation  (schema.py)
     contributions · dimensions · caveats
                    |
          groups.py -> financial dimension
                    |
       EvidenceLink -> CanonicalFact -> accession -> filing date
```

Three design commitments, each with an ADR:

- **The schema is the project's, not a library's** ([D-029](decision_log.md)).
  Nothing outside `explain/` imports `shap`.
- **The method is chosen per model family on merit** ([D-030](decision_log.md)).
  Exact contributions for the linear model; TreeSHAP only where there is no
  closed form.
- **Dimensions lead, features follow** ([D-031](decision_log.md)). Correlated
  financial features make individual rankings arbitrary; groups are stable.

**Caveats are structured data.** Eight codes, attached automatically — including
model-level facts (`NOT_CALIBRATED`, `COHORT_CONFOUNDED`) that would otherwise
live in a document separated from the number they qualify.

## 4. Global drivers

Share of total absolute attribution, out-of-fold, by financial dimension:

| Group | Logistic | Gradient boosting |
|---|---:|---:|
| **missingness** | **0.444** | 0.000 |
| profitability | 0.130 | **0.254** |
| cross-cutting (trend aggregates) | 0.143 | 0.027 |
| leverage | 0.113 | 0.185 |
| liquidity | 0.068 | 0.116 |
| cash flow | 0.036 | 0.097 |
| data quality | 0.036 | 0.008 |
| **size** | 0.016 | **0.192** |
| coverage | 0.015 | 0.122 |

The boosting model has no missingness row because it consumes `NaN` natively —
no indicator columns exist. Its single largest feature is `log_total_assets`
at **17.4%** of all attribution, five times the next.

**Rank correlation between the two models' dimension shares: −0.33.** They are
anti-correlated. Any statement of the form "the model says leverage matters"
has to name which model.

### Economic sanity of the top drivers

The logistic model's leading *financial* contributors carry the signs an
analyst would expect, which is genuine evidence the layer is not merely
fitting noise:

| Feature | Mean signed contribution | Economically sensible? |
|---|---:|---|
| `max_deterioration_persistence` | +0.154 | Yes — sustained deterioration raises risk |
| `n_deteriorating_ratios` | +0.139 | Yes — breadth of deterioration raises risk |
| `signal_leverage_deterioration` | +0.085 | Yes |
| `signal_negative_equity` | +0.058 | Yes |
| `ratio_roe` | −0.191 | Yes — higher returns lower risk |
| `revenue_to_assets` | −0.267 | Yes — more productive assets lower risk |

The boosting model's `log_total_assets` at −0.052 (bigger ⇒ safer) is also
defensible *in isolation* — size genuinely predicts survival. It is the
**magnitude** that is not defensible: a size feature dominating every financial
ratio, in a model whose cohort-separability score is 0.93, is the confound's
signature rather than an economic finding.

## 5. Missingness

The single largest attribution group for the primary model, so the question is
whether it is signal or artefact. It is substantially artefact.

**What missingness tracks** (Spearman, n=3,856):

| Against | ρ |
|---|---:|
| History depth (`periods_available`) | **−0.471** |
| Company size (`log_total_assets`) | **−0.385** |
| Prediction year | −0.223 |
| **The label** | **−0.066** |

Mean missing features: **8.8 for events, 11.8 for non-events** — events have
*better* data. By size tercile: 15.3 (small), 10.7 (mid), 8.1 (large). By year:
18.2 (2009) falling to 9.0 (2019).

So the indicators encode *who the company is and when it filed*, not *how it is
doing*. That is precisely the cohort confound entering through a second door.

**The ablation:**

| | ROC-AUC | PR-AUC | Calibration slope | Recall @10% |
|---|---:|---:|---:|---:|
| With missingness indicators (97 cols) | 0.803 | 0.177 | 0.326 | 0.415 |
| Without (57 cols) | 0.783 | 0.165 | 0.299 | 0.409 |

**44% of the attribution buys 0.021 of AUC.** The model leans on missingness
far more than it gains from it.

## 6. Cohort confounding

§1's table is the core result. Two clarifications that matter for reading it
honestly:

- The **size** and **data-rich** probes withhold the feature family that
  defines their target (`scale`, `quality` respectively). Without that
  correction the probe is circular — asking a model to identify large companies
  while handing it `log_total_assets` is not a finding. The reported 0.82/0.87
  and 0.95/0.95 are what the *rest* of the financial picture recovers.
- The **cohort** and **energy** probes need no correction: neither target is a
  feature.

An era probe was attempted and dropped: walk-forward tests one year per fold,
so an era label is constant within every fold and there is nothing to score.
Temporal behaviour is measured by era-wise attribution instead (§8).

## 7. Point-in-time negative universe

Phase 8 named this the largest remaining limitation and assumed it was a large
data-acquisition project. It is not: EDGAR publishes a quarterly
`full-index/YYYY/QTRn/form.idx` listing every filing received, which is the
authoritative point-in-time record and includes companies that no longer exist.
48 requests, streamed and discarded, a few hundred KB kept.

**The survivorship gap, measured:**

| Year | Annual filers | Still in today's ticker file | Survivorship |
|---|---:|---:|---:|
| 2009 | 9,650 | 2,223 | **23.0%** |
| 2012 | 8,212 | 2,443 | 29.8% |
| 2015 | 7,744 | 2,796 | 36.1% |
| 2018 | 6,856 | 3,170 | 46.2% |
| 2020 | 6,574 | 3,463 | 52.7% |
| **All 2009–2020** | **16,008** | **3,625** | **22.6%** |

Phase 8's comparison cohort was sampled from that 22.6%.

### 7.1 The controlled re-measurement

**Results in §13.** The short version: it did not work, and why it did not is
the more valuable finding.

Two panels differing in exactly one respect: the same 264 event companies, and
426 comparison companies drawn either from today's ticker file (Phase 8) or
from the point-in-time filer universe (Phase 9). Comparison-cohort **size** is
matched so the base rate is not itself a confound.

**What this fixes and what it does not.** It removes survivorship selection. It
*worsens* label noise, in a direction worth stating: BRD records only large
public bankruptcies, so a small filer that failed quietly enters the
point-in-time cohort labelled `0`. The two panels therefore bracket the truth
rather than one of them being correct:

    survivor comparison      ->  optimistic bound (no hidden failures among the negatives)
    point-in-time comparison ->  pessimistic bound (some real failures labelled 0)

## 8. Stability of explanations

**Temporal** — share of attribution by era, primary model:

| Group | 2013–14 | 2015–16 | 2017–19 |
|---|---:|---:|---:|
| missingness | 0.434 | 0.386 | 0.483 |
| cross-cutting | 0.131 | 0.162 | 0.138 |
| leverage | 0.148 | 0.115 | 0.095 |
| profitability | 0.106 | 0.159 | 0.125 |

Spearman between eras: **0.83–0.97**. The primary model's explanation is
stable over time.

The challenger's is not: Spearman 0.69–0.98, with `profitability` falling
0.441 → 0.247 → 0.173 while `size` rises 0.111 → 0.175 → 0.240. Its reliance on
the size proxy *grows* across the panel.

**Under resampling** — 60 refits on company-level bootstrap resamples of the
final fold's training data: **top-group agreement 98.3%**, median rank
correlation with the baseline ordering **0.983**. Individual shares move
(profitability spans 0.11–0.32 at the 5th–95th percentile) but the ordering
does not. This is the measured justification for [D-031](decision_log.md):
group-level explanations are stable where feature-level ones would not be.

## 9. Data quality found by explaining predictions

The highest-scoring observation in the whole panel — score exactly 1.0000 —
is **MATERION Corp, FY2013, a non-event**. Its single largest contribution is
`trend_pct_gross_margin` at **+80.4 log-odds**. Following the provenance chain:

```text
+80.4  trend_pct_gross_margin
  -> gross_margin = 33.53          (a 3,353% gross margin — impossible)
  -> gross_profit 187,978,000 / revenue 5,607,000
  -> revenue resolved from the `Revenues` tag  = 5,607,000
     but the filing also reports `SalesRevenueGoodsNet` = 1,166,882,000
  -> accession 0001104657-14-000062, 10-K, received 2014-03-14
```

`1,166,882 − 978,904 = 187,978` confirms `SalesRevenueGoodsNet` is the real
revenue. Phase 5's `revenue` chain prefers `Revenues`, and because that chain is
`PREFERRED_SCOPE` ([D-018](decision_log.md)) the 208× difference is recorded as
an expected scope variation rather than a conflict.

**Prevalence:** 64 rows (0.88%) across **17 companies** carry a definitionally
impossible gross margin (>1), including RingCentral (21.6) and Block (20.3) —
the same `Revenues` pattern. 47 rows show a net margin above 5.

**The consequence for the model:** `trend_pct_*` features are unbounded.
`trend_pct_interest_coverage` spans −1,099 to **+42,475**; `trend_pct_roa`
−11,351 to +24,517. 624 of 7,272 rows (8.6%) contain at least one such value.
A standardised linear model has no defence against them, which is a large part
of why the calibration slope is 0.33.

This is a **Phase 5/6 defect that Phase 9's provenance chain surfaced**, not a
Phase 9 one. It is documented and quantified here rather than patched
mid-phase; §14 carries the recommendation.

## 9a. Why the `signals` family added nothing, and the one exception

Phase 8's ablation measured `signals` at +0.007 ROC-AUC (not significant) on
top of `trends`, and recorded it without explaining it. The natural hypothesis
is redundancy: a Phase 7 signal fires *because* a ratio trend deteriorated, so
once the trend is in the model the indicator restates it. Tested directly — how
well is each signal reconstructed from the 17 trend features alone?

| Signal | Reconstructed from trends (ROC-AUC) |
|---|---:|
| `unusual_movement` | **0.997** |
| `multi_dimension_deterioration` | 0.951 |
| `profitability_deterioration` | 0.884 |
| `margin_compression` | 0.860 |
| `cash_flow_weakening` | 0.859 |
| `leverage_deterioration` | 0.854 |
| `liquidity_deterioration` | 0.845 |
| `interest_coverage_decline` | 0.811 |
| **`negative_equity`** | **0.655** |

Median **0.859**. The hypothesis holds, and this is the answer to §17: the
signal layer is a *coarsening* of information already in the model, so it
cannot add evidence to it.

**This is not a criticism of Phase 7.** A signal is meant to be a legible
summary an analyst can act on, and being reconstructable from its own inputs is
what "summary" means. It says the signals belong in the **explanation** path,
not the feature path — which is exactly where [D-031](decision_log.md) puts
them.

**The exception is worth keeping.** `negative_equity` is the only signal that
trends cannot reproduce (0.655), because it is a statement about a *level*
(equity below zero) rather than a movement. It is also the single largest
false-positive driver (§10). Both facts point the same way: it carries
information the trend features do not, and it needs its own treatment rather
than being pooled with the others.

## 9b. Subgroup behaviour, and what the label source does to it

| Size tercile | Rows | Events | Event rate | ROC-AUC |
|---|---:|---:|---:|---:|
| Small | 1,053 | **8** | — | *not scored* |
| Mid | 1,053 | 102 | 9.7% | 0.779 |
| Large | 1,054 | 47 | 4.5% | 0.811 |

| Industry | Rows | Events | Event rate | ROC-AUC |
|---|---:|---:|---:|---:|
| SIC 13 (oil & gas) | 446 | 67 | 15.0% | 0.748 |
| Every other SIC group | — | <15 | — | *not scored* |

The smallest third of the panel contributes **8 of 157 events**. That is not a
property of small companies; it is BRD's inclusion rule — it records large
public bankruptcies — showing up directly in the label.

That single fact ties the phase's findings together:

```text
BRD covers only large public bankruptcies
        -> small companies almost never carry a positive label
        -> small companies also have the most missing data (15.3 vs 8.1 features)
        -> the model learns "sparse data => safe"
        -> which is backwards for real credit monitoring
```

Measured, that learned association is strong: companies in the most-missing
quartile receive a **median score percentile of 0.35** against 0.60 for the
least-missing, and are flagged at **4.4%** against **13.9%**. The correlation
between missing-feature count and score percentile is **−0.241**.

The model is *correct about this sample* — the most-missing quartile really
does have a 1.8% event rate against 6.5% for the least-missing. It is the
sample that is wrong, and a monitoring product that inherited this behaviour
would systematically under-flag exactly the companies whose disclosure is
deteriorating.

## 10. Error analysis

Flag rule: top decile of the pooled out-of-fold ranking (322 of 3,215 rows).

| | Count |
|---|---:|
| Events in the panel | 159 |
| Flagged | 322 |
| True positives | 66 |
| False positives | 256 |
| False negatives | 93 |

**Taxonomy of the 256 false positives:**

| Category | Count |
|---|---:|
| `flagged_negative_equity` | **149** |
| `flagged_on_financials` | 100 |
| `flagged_small_company` | 5 |
| `flagged_data_sparse` | 2 |

**Taxonomy of the 93 false negatives:**

| Category | Count |
|---|---:|
| `missed_despite_complete_data` | **83** |
| `missed_data_sparse` | 6 |
| `missed_low_fact_coverage` | 4 |

Two things follow. Negative equity is the dominant false-positive driver — the
model heavily flags negative-equity companies and most do not fail within a
year, which is economically understandable and operationally expensive. And
**89% of misses had complete data**: better extraction would not have caught
them, so the gap is signal, not coverage. Consistent with §5, missed events
have *more* missing features (9.6) than caught ones (5.8), which is the
opposite of what a missingness-as-distress story predicts.

## 11. Ranking, not probability

Confirmed and now enforced in the schema ([D-033](decision_log.md)).

Score distribution: p90 = 0.142, p99 = 0.677, max = 1.000, and only **1.8%** of
rows score above 0.5. Calibration slope 0.326.

**Alert-rate table** (pooled out-of-fold, 3,215 rows, 159 events):

| Alert rate | Reviewed | Events caught | Recall | Precision | Rows read per event |
|---:|---:|---:|---:|---:|---:|
| 1% | 32 | 6 | 3.8% | 18.8% | 5.3 |
| 2% | 64 | 18 | 11.3% | 28.1% | 3.6 |
| 5% | 161 | 41 | 25.8% | 25.5% | 3.9 |
| 10% | 322 | 66 | 41.5% | 20.5% | 4.9 |
| 20% | 643 | 100 | 62.9% | 15.5% | 6.4 |

Against a 4.95% base rate, a 2% alert budget is ~5.7× better than random. That
is a real and useful lift — subject to every caveat above about what part of it
is cohort structure.

**Rank churn.** Median year-over-year move in a company's within-year
percentile is 14.2 points; the 90th percentile is 44.3 points, and **30.3% of
companies move more than 25 percentile points from one year to the next**. A
watchlist built on this ranking would reshuffle substantially each year, which
an analyst-facing phase has to design for rather than discover.

**Recalibration was considered and rejected.** The miscalibration is driven by
the unbounded features in §9 and by a base rate that is a property of the
sampling design. Fitting a Platt or isotonic layer would map one arbitrary base
rate onto another and manufacture exactly the false precision
[D-010](decision_log.md) exists to prevent.

## 12. Model comparison

| | Logistic (primary) | Gradient boosting (challenger) |
|---|---|---|
| Pooled ROC-AUC | 0.803 | 0.887 |
| Within-event-cohort ROC-AUC (Phase 8) | 0.733 | 0.787 |
| Cohort-separability AUC | 0.817 | **0.930** |
| Top single feature | `max_deterioration_persistence` (4.6%) | `log_total_assets` (**17.4%**) |
| Size group share | 1.6% | **19.2%** |
| Attribution method | exact, closed form | TreeSHAP |
| Era stability (Spearman) | **0.83–0.97** | 0.69–0.98 |
| Size reliance over time | flat | **rising** (0.11 → 0.24) |
| Calibration slope | 0.326 | 0.808 |

The challenger scores higher on every discrimination metric and is better
calibrated. It is also the model whose advantage is concentrated exactly where
the confound is largest, whose dominant feature is the confound's own marker,
and whose explanation drifts toward that marker over time.

**The primary stays primary** — but on the evidence above, not by default, and
the gap is explicitly *not* a reason to promote the challenger until §7's
re-measurement says what survives a point-in-time cohort.

## 13. Point-in-time results — a negative result, and what it redirects

The experiment Phase 8 asked for, run exactly as specified: the same 264 event
companies, 426 comparison companies drawn from the point-in-time filer universe
instead of today's ticker file, size-matched to Phase 8's cohort so only the
sampling frame differs. Only **139 of the 426 (33%)** are still listed today,
against 426 of 426 in Phase 8.

**Performance barely moved, and the confound got worse.**

| | Survivor cohort (Phase 8) | Point-in-time cohort (Phase 9) | Δ |
|---|---:|---:|---:|
| `debt_to_assets` baseline | 0.782 | 0.784 | +0.003 |
| Logistic (primary) | 0.803 | 0.797 | −0.006 |
| Gradient boosting | 0.887 | 0.894 | +0.007 |
| **Cohort separability, logistic** | 0.792 | **0.843** | **+0.051** |
| **Cohort separability, boosting** | 0.913 | 0.916 | +0.003 |

Every performance delta is far inside its confidence interval (logistic
0.754–0.838). **The survivorship hypothesis is not supported.**

### 13.1 Why — the confound is eligibility, not survival

One number explains it. BRD records only *large* public bankruptcies, so the
event cohort is large by construction, while a random draw from the real filer
population is dominated by small companies:

| Panel | Event median log-assets | Comparison | Gap |
|---|---:|---:|---|
| Phase 8 survivor cohort | 21.24 | 19.94 | **3.7× larger** |
| Phase 9 point-in-time cohort | 21.24 | 18.56 | **14.5× larger** |

Sampling point-in-time made the mismatch *worse*, because the survivor frame
was already tilted toward larger companies. What the cohort probe detects is
therefore not survivorship but **eligibility**: who could have been a BRD case
at all.

### 13.2 The fix that follows, and how far it gets

`phase9_size_matched.py` keeps every event row and restricts comparison rows to
the event cohort's own 10th–90th percentile size band — a control group the
event cohort could plausibly have been drawn from.

| | Unmatched point-in-time | Size-matched |
|---|---:|---:|
| Rows / events | 3,933 / 183 | 2,363 / 183 |
| Base rate | 4.9% | 8.3% |
| Logistic bankruptcy ROC-AUC | 0.797 | **0.781** |
| Logistic cohort separability | 0.843 | **0.819** |
| **Separability − bankruptcy (logistic)** | +0.047 | **+0.038** |
| Boosting bankruptcy ROC-AUC | 0.894 | **0.843** |
| Boosting cohort separability | 0.916 | **0.878** |
| **Separability − bankruptcy (boosting)** | +0.021 | **+0.035** |
| Logistic PR-AUC ÷ baseline | 3.6× | **3.1×** |

Size matching moves separability down (0.843 → 0.819; 0.916 → 0.878) and moves
bankruptcy AUC down with it. **The gap does not close.** Cohort membership
remains more predictable than the event under every construction tried, and the
model's lift over its own base rate *falls* once like is compared with like
(3.6× → 3.1×).

### 13.3 What this establishes

Three sampling constructions were tested — survivor-frame, point-in-time, and
size-matched point-in-time. The confound survived all three. That is a stronger
and more useful result than the one the plan anticipated:

- **The negative universe cannot be fixed by re-sampling alone.** The event
  cohort is defined by an eligibility rule (BRD's size threshold, plus Phase 3's
  requirement of ≥2 pre-bankruptcy XBRL periods) that no draw from the general
  filer population reproduces.
- **Phase 8's pooled figures remain uninterpretable as bankruptcy-prediction
  performance**, and now demonstrably so rather than as a caveat.
- **The within-event-cohort measurement is still the only defensible one.**
  Phase 8 §7.4: logistic 0.733, boosting 0.787, against a 12.3% base rate, with
  cohort membership constant and therefore carrying no information.

The point-in-time universe itself is not wasted: it is correct, cheap to
rebuild, and a prerequisite for the eligibility-matched design §14 recommends.
It simply is not sufficient on its own.

## 14. Limitations and recommendations

### 14.1 What the model is actually learning

In order of how much of its behaviour each accounts for:

1. **Who is in the sample.** Cohort membership is more predictable than the
   label under every construction tested (§13).
2. **Whether the filing is complete.** 44% of the primary model's attribution,
   tracking size (ρ=−0.39) and history depth (ρ=−0.47) rather than the label
   (ρ=−0.07), and producing the inverted behaviour in §9b.
3. **Company size.** 19.2% of the boosting model's attribution, its top feature
   by 5×, and rising across eras.
4. **Genuine financial deterioration.** Real and measurable — the ablation's
   `ratios` (+0.110) and `trends` (+0.065) are significant, the coefficient
   signs are economically correct, and the within-cohort result (0.733/0.787)
   is well above chance. It is simply not the largest term.

### 14.2 Which features and explanations to trust

| | Assessment |
|---|---|
| **Trustworthy** | `n_deteriorating_ratios`, `max_deterioration_persistence`, `ratio_roe`, `revenue_to_assets`, `signal_negative_equity`, and the ratio/trend families generally — correct signs, significant ablation contribution, stable across eras and bootstraps |
| **Proxy-like — do not present as financial findings** | every `__missing` indicator, `log_total_assets`, `fact_coverage`, `periods_available` |
| **Reliable explanations** | grouped, dimension-level attribution from the logistic model (98.3% top-group agreement, era Spearman 0.83–0.97) |
| **Unreliable explanations** | individual feature rankings among correlated ratios; anything from the boosting model quoted as economics, given its size dependence and drifting era profile (0.69–0.98) |

### 14.3 Which metrics may be quoted

- **Quotable with the population named:** within-event-cohort ROC-AUC
  (0.733 logistic / 0.787 boosting), and alert-rate recall/precision on the
  pooled ranking *provided* the cohort caveat is attached.
- **Not quotable without heavy caveats:** pooled ROC-AUC 0.803 / 0.887. Never
  as "bankruptcy prediction accuracy".
- **Never quotable:** any probability reading of the score. Calibration slope
  0.326 (0.392 on the point-in-time panel).

### 14.4 Model decision

**The logistic model remains primary; the boosting model remains a measured
challenger.** The boosting model wins on every discrimination metric and is
better calibrated (0.78 vs 0.33), and Phase 9 strengthens rather than weakens
the case against promoting it: its advantage concentrates where the confound
is largest, its top feature *is* the confound's marker, and its explanation
drifts toward that marker over time while the logistic model's does not.

Revisit if and only if an eligibility-matched negative universe exists and the
boosting advantage survives it.

### 14.5 Recommendations for Phase 10 and beyond

**Do first, before any further modelling:**

1. **Build an eligibility-matched negative universe.** Sample negatives from
   companies that satisfy BRD's own inclusion conditions at time T — comparable
   total assets, an operating history, consistent filing. The point-in-time
   universe (`pit_filers.csv`) is the frame; the matching is the missing step.
   §13.2 shows partial matching already narrows the gap.
2. **Fix the `revenue` resolution defect** (§9). 17 companies, a 208×
   understatement in the worst case, and it produced the panel's
   highest-scoring row. A `PREFERRED_SCOPE` chain should flag a 200× difference
   between candidates as `CONFLICTING` rather than an expected scope variation.
3. **Bound the `trend_pct_*` features.** Ranges to ±42,000 are mathematically
   correct and economically meaningless, they are much of why calibration
   fails, and a ratio-of-ratios needs either winsorisation or a bounded
   transform.

**Reconsider:**

4. **Whether missingness indicators belong in the model at all.** They cost
   44% of the attribution and return 0.021 AUC, and what they encode is
   inverted relative to real monitoring.
5. **Whether the Phase 7 signal features belong in the feature set.** They are
   86% reconstructable from the trends (§9a) and add nothing measurable. They
   remain valuable in the *explanation* path.

**Do not do yet:**

6. **Recalibration.** Meaningless until 2 and 3 are fixed and the negative
   universe reflects a real population ([D-033](decision_log.md)).
7. **Promoting the boosting model.** §14.4.

### 14.6 What Phase 10 inherits

A working, tested explanation layer (`explain/`, 96–100% covered) that turns
any model's prediction into dimension-level attributions traced to filings and
carries structured caveats; a point-in-time filer universe; and — most usefully
— a precise, evidenced account of which claims this predictive layer can and
cannot support. Phase 10's NLP work is independent of the model and is not
blocked by any of the above.

