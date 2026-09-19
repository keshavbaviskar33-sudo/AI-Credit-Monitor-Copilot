# Combined Assessment — Phase 11

| | |
|---|---|
| **Status** | Complete — measured on 202 filings carrying the Phase 8 bankruptcy outcome |
| **Date** | 2026-09-19 |
| **Decisions** | [D-036](decision_log.md) evidence package, not a combined score · [D-037](decision_log.md) content-addressed evidence IDs · [D-038](decision_log.md) disagreement is an output · [D-039](decision_log.md) the as-of gate is enforced at the bottom |
| **Code** | `src/credit_risk_copilot/assessment/` |
| **Scripts** | `phase11_assess.py` |
| **Requirements** | FR-15 (contradictions) · FR-11 (change since last period) · FR-05 (historical replay) · FR-21 (pipeline versions) — and the mechanism behind FR-17 |
| **Related** | [financial_health.md](financial_health.md) · [predictive_model.md](predictive_model.md) · [model_evaluation_explainability.md](model_evaluation_explainability.md) · [nlp_risk_signals.md](nlp_risk_signals.md) |

> **The headline is negative, and it is the deliverable.** At a matched alert
> budget, agreement between all three layers is **exactly as precise as the
> predictive model's own top-k** — `+0.000 [−0.082, +0.098]` — and two of the
> four agreement rules are measurably *worse* than the model alone. Combining
> the layers does not improve the ranking. What it does improve is everything
> Phase 12 and Phase 13 actually need: citability, disagreement, and a replay
> guarantee. §6 has the numbers, §7 says what survives them.

---

## 1. What "combine the analytical outputs" was in danger of meaning

Four layers now analyse a company and none of them share a type:

| Layer | Output | Says |
|---|---|---|
| Phase 6/7 | `FinancialHealthReport` | which ratios are moving, and which way |
| Phase 8/9 | `ModelExplanation` | where this filing sits in a monitored ranking, and why |
| Phase 10 | `NarrativeRiskReport` | what the filer states about itself, verbatim |
| Phase 5 | `CanonicalFact` provenance | how much of the above can be trusted |

The obvious build is a weighted combination producing one risk number. This
project has refused that number three times on the same grounds —
[D-010](decision_log.md) (the model output is not a probability of default),
[D-022](decision_log.md) (no composite health score),
[D-033](decision_log.md) (the score is a ranking position) — and a fourth
refusal is warranted for a stronger reason than consistency: a composite here
would average a measured ranking metric, a threshold-driven trend label and a
regex hit into one uninspectable digit, and that digit would be the only thing
anyone read.

So the phase was built around what a combination layer can add that no single
layer can see: **the relationship between them**.
([D-036](decision_log.md).)

## 2. What is produced

```text
  FinancialHealthReport   ModelExplanation   NarrativeRiskReport
          |                      |                   |
          +----------+-----------+---------+---------+
                     |  evidence.py  -- one registrar per layer
                     v
             EvidenceItem[]        EV-HS-1a2b3c4d, EV-NS-..., EV-MD-...
                     |             content-addressed, filing-dated
          +----------+----------+
          |                     |
     asof.py                reads.py     ELEVATED / QUIET / UNKNOWN
     rejects anything            |
     filed after as_of     +-----+-----+
          |                |           |
          v          contradictions  corroboration
                          |           |
                          v           v
                        Assessment  (no score anywhere in it)
```

An `Assessment` carries evidence, contradictions, corroborations, which layers
spoke, why the others did not, and the pipeline versions behind all of it. It
has no overall status field, and `assessment.disagrees` is the only boolean
about the whole thing.

### The evidence register

Median **30 evidence items** per assessment on the measured corpus (max 38).
Each one is addressable, dated, and carries every number it states:

```text
EV-DS-9e21c4aa  liquidity: deteriorating over FY2014 (3 of 4 ratios
                conclusive; deteriorating: current_ratio, quick_ratio)
EV-NS-51b0ff3c  The filer states going-concern doubt (2 occurrence(s) in
                item_7; specificity high)
                quote: "There exists substantial doubt about the Company's
                ability to continue as a going concern."
EV-MS-77ca0e19  gradient_boosting_all scores 0.8123 for FY2014: 97.8th
                percentile of the scored population. The score is a ranking
                position, not a probability of default.
```

`EvidenceItem.numbers` holds the figures as floats, which is what lets Phase 12
check a drafted sentence's digits mechanically instead of by parsing English.

## 3. Why the IDs are content hashes

`evidence_id` is `EV-<kind tag>-<blake2s of the item's content>`; `identity_key`
is the same item's *subject* with no values and no period.

The split is load-bearing. Phase 13 stores an AI draft immutably. If an ID were
a position or a counter, re-running the pipeline after a data fix could
silently repoint a stored citation at a different fact: the draft would still
validate and would now be wrong. A content hash cannot do that — change the
cited value, the ID changes, the stored citation fails validation, and the
failure is visible.

The cost is that content hashes are useless for "is this the same signal as
last quarter?", which is exactly FR-11. Hence `identity_key`, and hence the
change report diffs on it. ([D-037](decision_log.md).)

## 4. The contradiction rules (FR-15)

Seven named conditions over cited evidence. No similarity metric, no learned
disagreement detector: a contradiction an analyst cannot check is a second
opaque model sitting on top of the first.

| Code | Fires when |
|---|---|
| `MODEL_ELEVATED_HEALTH_QUIET` | the model ranks high and no dimension is deteriorating |
| `NARRATIVE_SEVERE_MODEL_QUIET` | the filer states a high-specificity condition; the model ranks it in the lower half |
| `NARRATIVE_SEVERE_HEALTH_QUIET` | the same, against the ratio trends |
| `NARRATIVE_SELF_CONTRADICTION` | one filing both asserts and denies the same condition |
| `DIMENSION_DISAGREEMENT` | the model's attribution pushes one way on a dimension, the trends read the other |
| `SCORE_NOT_EVIDENCE_BACKED` | a high rank is mostly attributed to the filing's completeness |
| `ABSENCE_NOT_OBSERVED` | "no narrative concerns" rests on a section that was never located |

**No rule adjudicates.** Each names both sides and stops, because in every one
of these cases the information needed to decide is genuinely absent from the
assessment. `resolution_hint` names the next thing to check, which is an
action, not an answer.

## 5. The corpus

The 238-filing Phase 10 narrative corpus, inner-joined to the Phase 8 panel on
accession. **202 filings survive**, 100 of them followed by a bankruptcy
petition within 365 days; 36 corpus filings never became a usable, scored
observation and are counted rather than imputed. Test years 2013–2019.

> **Base rate 0.495, by construction.** The Phase 10 corpus is deliberately
> year-matched between cohorts. Every precision figure below is a **comparison
> between methods on one corpus** and is not portfolio precision. The cohort
> confound [D-032](decision_log.md) measured is present here too — which is
> precisely why the *differences* are readable while the levels are not: every
> method below faces the same confounded population.

The model layer is run for real — walk-forward out-of-time on the Phase 8
panel, TreeSHAP from each fold's own fitted estimator, percentiles computed
*within the test year* because a monitoring product ranks this quarter against
itself. The health and narrative layers are rebuilt from the committed Phase 8
and Phase 10 outputs. The rebuild is lossy in exactly one way and it is stated
rather than hidden: `features.py` encoded dimension status as
deteriorating / not-deteriorating / `None`-for-insufficient, so `IMPROVING`,
`STABLE` and `MIXED` all return as not-deteriorating. Every cross-layer rule
reads exactly that three-way distinction, so the reconstruction is faithful to
what is being measured; where it is not, it biases contradiction counts **up**
and health-based corroboration counts **down**.

## 6. Does combining carry information the parts do not?

### 6.1 The test

Any conjunction has higher precision and lower recall than its parts, so
reporting that would be reporting arithmetic. The question an analyst faces is:
*given that I can look at k companies this quarter, is my list better built
from agreement between layers than from the model's top k?* So every
combination is compared against the model's own top-k at the same k, with a
company-clustered paired bootstrap (2,000 resamples) on the difference.

### 6.2 The answer: no

| Selector | k | alert rate | precision | model top-k precision | **Δ precision (95% CI)** | overlap with model top-k |
|---|---:|---:|---:|---:|---|---:|
| Model alone (≥90th pct) | 70 | 34.7% | 0.871 | 0.871 | — *(is the baseline)* | 1.00 |
| Narrative alone (high-specificity asserted) | 80 | 39.6% | 0.675 | 0.875 | **−0.200 [−0.307, −0.082]** | 0.51 |
| Health alone (any deteriorating dimension) | 176 | 87.1% | 0.540 | 0.557 | −0.017 [−0.045, 0.000] | 0.91 |
| `ALL_LAYERS_ELEVATED` | 43 | 21.3% | 0.930 | 0.930 | **+0.000 [−0.082, +0.098]** | 0.63 |
| `MODEL_AND_NARRATIVE` | 38 | 18.8% | 0.947 | 0.921 | +0.026 [−0.056, +0.122] | 0.55 |
| `MODEL_AND_HEALTH` | 153 | 75.7% | 0.601 | 0.634 | −0.033 [−0.065, 0.000] | 0.86 |
| `HEALTH_AND_NARRATIVE` | 81 | 40.1% | 0.679 | 0.877 | **−0.198 [−0.306, −0.074]** | 0.58 |

Read in isolation the combinations look excellent — `MODEL_AND_NARRATIVE` fires
on 36 of 100 pre-bankruptcy filings and 2 of 102 comparison filings, a lift of
**18.4**. Read against the model's own list at the same budget, that becomes
`+0.026` with an interval spanning zero: **one filing out of 38.** Every
interval in the table either contains zero or is negative. Nothing here beats
the model alone.

Two results are worth separating from the general negative:

- **`ALL_LAYERS_ELEVATED` picks a genuinely different list of the same
  quality.** Its overlap with the model's top 43 is **0.63**, so roughly a
  third of its selections are companies the model would not have surfaced — and
  its precision is identical to four decimal places. That is not an improvement
  in ranking, but "an independently constructed list of equal quality, each
  entry of which carries three citations" is a different product from "the
  model's top 43", and a human reviewer can act on the second in a way they
  cannot act on a score.
- **The narrative layer is dominated at matched budget.** Phase 10 measured its
  gated signals at lifts of 2.4 to 6.1 and that measurement stands; what is new
  here is that spending an alert budget on it instead of on the model costs
  **20 precision points**. A layer can carry real information and still be the
  wrong thing to rank on.

### 6.3 Where the layers disagree, and whether that is informative

| Contradiction | pre-bankruptcy | comparison | lift |
|---|---:|---:|---:|
| `NARRATIVE_SELF_CONTRADICTION` | 16.0% | 7.8% | **2.04** |
| `ABSENCE_NOT_OBSERVED` | 28.0% | 18.6% | 1.50 |
| `DIMENSION_DISAGREEMENT` | 37.0% | 63.7% | 0.58 |
| `NARRATIVE_SEVERE_MODEL_QUIET` | 1.0% | 10.8% | **0.09** |
| `MODEL_ELEVATED_HEALTH_QUIET` | 0.0% | 0.0% | — |
| `NARRATIVE_SEVERE_HEALTH_QUIET` | 0.0% | 0.0% | — |
| `SCORE_NOT_EVIDENCE_BACKED` | 0.0% | 0.0% | — |

**`NARRATIVE_SELF_CONTRADICTION` is the one thing in this phase that no single
layer produces and that tracks the outcome.** A filing that both asserts and
denies the same condition — the pattern Phase 10 found in SandRidge's FY2015
10-K, which affirms compliance with its note covenants two months before its
petition while disclosing a violation elsewhere in the same document — is
**twice as likely** to precede a bankruptcy. It requires the assertion gate
[D-035](decision_log.md) to exist at all: without the four-way mood
classification, both sentences are just "covenant language".

**Two of my own claims were wrong and are corrected here rather than defended.**

1. `NARRATIVE_SEVERE_MODEL_QUIET`'s first `resolution_hint` told the analyst to
   treat the model as the weaker side, reasoning that the filer's own verbatim
   words outrank a fitted score. Measured, the rule fired on **11 comparison
   filings and 1 pre-bankruptcy filing** — lift 0.09. On this corpus the
   companies it flags overwhelmingly did *not* fail. The hint now states the
   measurement instead of the assumption.
2. `DIMENSION_DISAGREEMENT` fires on half the corpus (102 of 202) and is
   *anti*-correlated with the outcome. Part of that is the reconstruction bias
   in §5, which makes the health side read quiet more often than it should. It
   is retained, reported at this rate, and flagged in §8 as the rule most in
   need of the real Phase 7 reports.

**`MODEL_ELEVATED_HEALTH_QUIET` cannot fire on this corpus and that is a
property of the corpus, not a bug.** 87% of these filings have at least one
deteriorating dimension, so the health layer is almost never quiet. The rule is
written for a normal portfolio and is **untested** here; §8 records that.

### 6.4 `SCORE_NOT_EVIDENCE_BACKED`: the pathology Phase 9 found is gone

Phase 9 measured **44%** of the logistic model's attribution coming from
missingness indicators that tracked size and history depth rather than the
label. That finding is why this rule exists. Measured on the primary model
[D-034](decision_log.md) promoted:

| percentile of filing-artefact attribution share | 50 | 75 | 90 | 95 | 99 | max |
|---|---:|---:|---:|---:|---:|---:|
| `gradient_boosting_all` | 0.004 | 0.009 | 0.016 | 0.019 | 0.029 | 0.071 |

**The gradient-boosting model has no missingness indicators at all** — it
handles absent values natively rather than through `__missing` columns — and
its `data_quality` features barely register. D-034's promotion removed the
pathology rather than inheriting it, which is a consequence of that decision
that D-034 itself did not claim.

The rule was rewritten during this phase for exactly that reason: its first
version read `ModelExplanation.missingness_share`, which is *structurally* zero
for the shipped model, so it could only ever have fired on the retired
comparator. It now reads the `missingness` and `data_quality` attribution
groups, and is kept as a standing guard at a disclosed threshold of 0.35.

## 7. Integrity: what the phase guarantees

These are the properties Phase 12 and Phase 13 are built on, so each is
asserted over all 202 assessments rather than argued for.

| Property | Result |
|---|---|
| Every evidence ID cited by every finding resolves | **0 unresolved** of all citations |
| Every narrative quote reaching an assessment is still character-for-character what Phase 10 emitted (SC-03 across the boundary) | **0 mismatches** |
| Evidence IDs identical on independent re-assembly of the same inputs | **stable**, 25-assessment sample |
| The as-of gate refuses an assembly dated one day before the filing | **202 of 202 refused** |

The last one is FR-05 demonstrated rather than described. The gate also caught
a leak in this phase's own test fixture before it could reach anything else:
the first draft stamped a 2014 assessment with a 2015 filing date, and
`AsOfGate` rejected it. ([D-039](decision_log.md).)

## 8. Limitations

1. **The measurement corpus is distress-tilted and year-matched.** 87% of its
   filings have a deteriorating dimension and its base rate is 0.495. Three
   rules could not fire on it at all. Rule incidence on a normal portfolio is
   unmeasured.
2. ~~**The health layer is reconstructed, not re-run**~~ — **paid in Phase 17
   ([D-053](decision_log.md)), and two of the three biases declared here were
   wrong.** All 202 filings were re-run for real. The reconstruction was
   **exact** on the distinction it claimed to preserve (`deteriorating` 522/522,
   `insufficient_data` 122/122, zero errors); every disagreement was inside the
   collapsed class, where 242 dimensions were really `IMPROVING` and 96 really
   `MIXED`. But `MODEL_ELEVATED_HEALTH_QUIET` never fires at all, so calling it
   an upper bound was vacuous; `DIMENSION_DISAGREEMENT` was biased **downward**,
   not upward (102 firings reconstructed, 110 real), because the rule is
   symmetric and the collapse both suppresses and creates firings; and health
   corroboration was indeed a lower bound, but the extra firings land in the
   comparison cohort, so every health-based **lift falls** (`MODEL_AND_HEALTH`
   1.538 → 1.444). One number in §6.2 moves and moves against the layer:
   `MODEL_AND_HEALTH` is now −0.032 [−0.065, **−0.006**], an interval that no
   longer touches zero. **Everything not touching health is identical to four
   decimals**, so §6.2's headline does not depend on the shortcut. Full account
   in [measurement_debts.md §2](measurement_debts.md).
3. **The cohort confound is inherited, not solved.** Every precision figure
   sits on the population [D-032](decision_log.md) showed is separable on
   sampling design at least as well as on the label. The *differences* between
   methods are readable; the levels are not.
4. **`FILING_ARTEFACT_SHARE_LIMIT = 0.35` is a disclosed line, not a fitted
   one.** It never fires for the primary model, so the corpus gives no evidence
   about where it should sit.
5. **No rule spans more than two layers except `ALL_LAYERS_ELEVATED`.** Richer
   conditions (a narrative assertion contradicting a *specific* ratio value)
   are possible and were not built, because each one needs its own measurement
   and the four-rule set already answered the phase's question.
6. **Change reporting (FR-11) is tested but not measured.** `compare()` has
   unit coverage; no multi-period replay over the corpus was run, because the
   Phase 8 panel's consecutive filings per company were not assembled into
   assessment sequences here.

## 9. What Phase 12 receives

An `Assessment` per company per as-of date. The four things it should use:

- **Cite `evidence_id`, never restate a fact.** `validate_citations()` is the
  mechanism behind FR-17 and it is already written; Phase 12 supplies the IDs a
  draft claims and gets back the ones that do not exist.
- **Check drafted numbers against `known_numbers()`.** Membership is necessary,
  not sufficient — a number can be real and attached to the wrong claim, which
  is why citations are checked per claim as well.
- **Render `contradictions` and `layers_absent`.** A synthesis that omits a
  disagreement, or that reads a missing layer as a calm one, is the specific
  failure this phase exists to prevent.
- **Do not ask the LLM for a combined score.** There isn't one, on purpose, and
  §6 is the evidence that manufacturing one would not even have paid.

And the thing it should *not* do: treat corroboration as a confidence
percentage. `layers` is a tuple of names. Two-layer agreement is a different
finding from three-layer agreement, not 0.67 of it.
