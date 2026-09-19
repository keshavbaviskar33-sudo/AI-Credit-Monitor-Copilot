# Narrative Risk Signals — Phase 10

| | |
|---|---|
| **Status** | Complete — measured on 238 filings linked to the Phase 8 bankruptcy outcome |
| **Date** | 2026-09-19 |
| **Decisions** | [D-035](decision_log.md) assertion gating |
| **Code** | `src/credit_risk_copilot/nlp/` |
| **Scripts** | `phase10_corpus.py` → `phase10_evaluate.py` |
| **Requirements** | FR-14 (verbatim evidence) · SC-03 (quotes verbatim) · QM-04 (precision/recall) · [A-10](assumptions.md), [A-15](assumptions.md) |
| **Related** | [extraction.md](extraction.md) (section detection) · [financial_health.md](financial_health.md) · [predictive_model.md](predictive_model.md) |

> **What this layer is not.** It reports what a filing **says**, not what is
> true. "The filer states substantial doubt about its ability to continue as a
> going concern" is a fact about the document; whether the company survives is
> not something any text layer can know. Every signal therefore ships with the
> sentence it came from, and the analyst reads the sentence
> ([D-003](decision_log.md)).

---

## 1. The problem this layer actually has

The obvious implementation is a phrase matcher over Item 1A (Risk Factors) and
Item 7 (MD&A). It does not work, and not because the phrases are hard to
choose.

Item 1A's statutory purpose is to enumerate everything that could go wrong. So
**every** 10-K discusses default, covenant breach, liquidity exhaustion and
bankruptcy — in the conditional. Apple's risk factors discuss default.
Coca-Cola's discuss liquidity. A matcher that reports these fires on every
filing ever written, and a signal that fires on everything carries no
information.

What separates a filing that is *in* distress is the **mood** of the sentence:

| | |
|---|---|
| "There exists substantial doubt whether we will be able to continue as a going concern." | **asserted** |
| "If we are unable to refinance, we may be unable to continue as a going concern." | **hypothetical** |
| "See Note 1 for discussion of the Company's ability to continue as a going concern." | **cross reference** |
| "No event of default has occurred under the Credit Facility." | **negated** |

All four contain the trigger phrase. Only the first is evidence.
[D-035](decision_log.md) is the decision to gate on this, and §5 measures what
the gate is worth.

## 2. What is produced

```text
  10-K HTML
      |  Phase 4 section detection (extraction/sections.py)
      v
  Item 1A . Item 3 . Item 7          -- located, or reported as missing
      |  segment.py        sentences as spans, never as copied strings
      v
  sentences
      |  normalize.py      lower-cased, punctuation folded, SAME LENGTH
      |  catalog.py        12 signal codes, ~50 patterns
      |  assertion.py      asserted / hypothetical / cross-reference / negated
      v
  NarrativeRiskSignal
      +-- code, label, specificity
      +-- assertion
      +-- pattern_id            -- which single line fired
      +-- EvidenceQuote
            +-- text            -- verbatim, SC-03
            +-- char_start/end  -- slices back out of the document
            +-- trigger offsets -- for highlighting
            +-- accession, form, filed
```

Every offset indexes the original document, which is the property SC-03 rests
on. `normalize.match_view` is length-preserving by construction — one character
in, one character out — so a pattern can be written in plain lower-case ASCII
and still yield an offset into text full of typographic quotes and em dashes.
That constraint is enforced by a test rather than a comment, because a single
one-to-many mapping added later (a ligature, an ellipsis) would silently shift
every quote after it in the document.

## 3. The signal catalog

Twelve codes. Each is a condition a filer is **required** to disclose, so its
wording is reasonably stable across companies — that is the selection rule, and
it is why sentiment ("challenging environment") and guidance are excluded.
They vary with the drafting lawyer, not with the credit.

| Code | What it means |
|---|---|
| `GOING_CONCERN_DOUBT` | Substantial doubt about continuing as a going concern |
| `COVENANT_BREACH` | Stated non-compliance with a debt covenant |
| `COVENANT_WAIVER_OR_AMENDMENT` | A covenant waived, or an agreement amended to cure one |
| `DEBT_DEFAULT_OR_ACCELERATION` | Event of default, acceleration, reclassification to current |
| `DEBT_RESTRUCTURING` | Forbearance, exchange offer, RSA, restructuring advisers engaged |
| `BANKRUPTCY_CONTEMPLATED` | Protection sought, prepared for, or already filed |
| `LIQUIDITY_SHORTFALL` | The filer's *own* resources stated as possibly insufficient |
| `MATERIAL_WEAKNESS` | Material weakness in internal control over financial reporting |
| `DIVIDEND_SUSPENSION` | Dividend suspended, eliminated or cut |
| `DELISTING_NOTICE` | Exchange notice of non-compliance with listing standards |
| `CREDIT_RATING_DOWNGRADE` | A rating agency downgrade |
| `ASSET_IMPAIRMENT` | An impairment recognised |

**Deliberately not in the catalog: a distress-word count.** A "risk vocabulary
density" score over Item 1A is the classic version of this layer and it mostly
measures how long the risk factors are. This project already refuses composite
scores whose inputs cannot be inspected ([D-022](decision_log.md)), and the
same objection applies.

## 4. The corpus

Designing a text layer against six distressed filings and then reporting how
well it separates those same six would measure nothing. So the measurements
below run on a larger corpus that carries the Phase 8 label
(`phase10_corpus.py`, seed `20260917`):

| | Filings |
|---|---:|
| Event (a petition followed within 365 days) | 118 |
| Comparison (no petition in the window) | 120 |
| **Total** (185 companies) | **238** |

Comparison filings are **year-matched** to the event filings — the two cohorts
have identical year profiles across 2011–2019. Without that, any measured
difference would partly be a difference of era: filings got longer and more
heavily lawyered over this period, and attributing that drift to distress would
be the easiest mistake available here.

Each filing is the observation's *own* accession, so the text and the label
describe the same document on the same date, and the point-in-time rule
([D-008](decision_log.md), [D-026](decision_log.md)) survives into this layer.

## 5. What the assertion gate is worth

A keyword matcher and this layer run the same patterns over the same sentences.
The only difference is the gate. Over the 238-filing corpus:

| | Gated (shipped) | Ungated (a keyword matcher) |
|---|---:|---:|
| Matches emitted | 1,395 asserted + 176 negated | + 784 hypothetical |
| Mean signals per filing | 5.9 | 9.9 |
| Mean distinct codes per filing | 1.68 | 2.91 |
| Filings flagged by any signal | 67.6% | 78.6% |

Those aggregates undersell it, because the question is not how many matches
were dropped but whether the survivors separate the two cohorts. Two worked
examples, and they disagree in an informative way:

| | Event filings | Comparison filings | Lift |
|---|---:|---:|---:|
| **`COVENANT_BREACH`, ungated** | 60.2% | 59.2% | **1.02** |
| **`COVENANT_BREACH`, gated** | 22.0% | 9.2% | **2.40** |
| `GOING_CONCERN_DOUBT`, ungated | 25.4% | 5.8% | 4.36 |
| `GOING_CONCERN_DOUBT`, gated | 22.9% | 4.2% | 5.49 |

**Ungated, covenant language appears in 59% of the filings of companies that
did not go bankrupt, and 60% of those that did.** Its lift is **1.02** — not
"weak" but, to two decimal places, *nothing*: a coin that lands the same way
for both cohorts. The gate removes **85%** of the comparison-side filings and
**63%** of the event-side ones — it is selective, not merely strict — and the
lift goes to **2.40**. That pair of
rows is the entire case for [D-035](decision_log.md), and it is the difference
between a signal and a word count.

`GOING_CONCERN_DOUBT` moves far less, and the reason is worth stating: since ASU
2014-15 the going-concern disclosure is *mandatory once its conditions are
met*, so filers do not write it hypothetically. Its wording is already
self-gating. The gate matters exactly where the language is discretionary, and
covenant prose is the most discretionary in the catalog.

## 6. Does any of it track the outcome?

Every signal's rate in the 118 filings that preceded a petition within 365
days, against the 120 year-matched filings that did not. This measurement does
not depend on my own labelling at all, which is why the catalog's `Specificity`
values are set from it.

| Signal | Event | Comparison | Lift | Event filings |
|---|---:|---:|---:|---:|
| `DELISTING_NOTICE` | 10.2% | 1.7% | **6.10** | 12 |
| `GOING_CONCERN_DOUBT` | 22.9% | 4.2% | **5.49** | 27 |
| `BANKRUPTCY_CONTEMPLATED` | 3.4% | 0.8% | 4.07 | 4 |
| `DEBT_DEFAULT_OR_ACCELERATION` | 10.2% | 3.3% | **3.05** | 12 |
| `COVENANT_WAIVER_OR_AMENDMENT` | 22.9% | 7.5% | **3.05** | 27 |
| `DIVIDEND_SUSPENSION` | 5.1% | 1.7% | 3.05 | 6 |
| `DEBT_RESTRUCTURING` | 40.7% | 14.2% | **2.87** | 48 |
| `COVENANT_BREACH` | 22.0% | 9.2% | **2.40** | 26 |
| `LIQUIDITY_SHORTFALL` | 5.1% | 2.5% | 2.03 | 6 |
| `CREDIT_RATING_DOWNGRADE` | 11.0% | 5.8% | **1.89** | 13 |
| `ASSET_IMPAIRMENT` | 62.7% | 45.0% | **1.39** | 74 |
| `MATERIAL_WEAKNESS` | 13.6% | 11.7% | **1.16** | 16 |

Bold lifts rest on 10 or more event filings; the rest are shown but are too
thin to carry a `Specificity` assignment on their own.

**Every signal points the right way**, which is the first thing worth saying:
none of the twelve is more common among the companies that survived. But the
spread is the finding.

**Two of my own `Specificity` declarations were wrong, and the catalog has been
corrected to match the measurement.** `MATERIAL_WEAKNESS` was declared `HIGH`
and measures **1.16** — 13.6% against 11.7%, which is close to nothing. That is
not an argument for dropping it: a material weakness is a stated reason to
trust the filing's *numbers* less, and every ratio and model feature downstream
is computed from those numbers. It is an argument that it is not a **credit**
signal, and the catalog now says `LOW`. `COVENANT_BREACH` was declared `HIGH`
and measures 2.40, now `MODERATE`. Only `COVENANT_WAIVER_OR_AMENDMENT` moved
up.

`ASSET_IMPAIRMENT` behaved exactly as predicted when it was put in the catalog
as the worked example of a signal worth reporting and not worth trusting alone:
lift 1.39, present in 45% of healthy filings.

## 7. SC-03 — are the quotes verbatim?

**2,355 quotes checked across 238 filings. 0 failures.**

The check is not a promise, it is `nlp.verify_quotes`: every emitted quote is
sliced back out of the document at the offsets it claims, and compared. The
test suite exercises it in both directions — including a deliberately tampered
quote, because a check that cannot fail proves nothing.

Three design choices make this hold rather than luck:

- `normalize.match_view` is **length-preserving**, so a pattern written in
  lower-case ASCII yields an offset into text full of typographic quotes.
  `"İ".lower()` returns *two* characters, which would shift every subsequent
  quote by one, so the fast path is taken only when it is verified not to have
  resized the string.
- Sentences are returned as **spans, never as strings**.
- An over-long sentence is narrowed to a window around its trigger, which
  cannot make a quote non-verbatim — only less complete.

## 8. A-10 — can the sections be located at scale?

[A-10](assumptions.md) has read "accuracy on a labelled sample still due in
Phase 10" since Phase 4, where section detection was built and verified on 12
filings. Measured now over 238:

| Section | Located | Rate | Median sentences |
|---|---:|---:|---:|
| Item 7 (MD&A) | 199 | **83.6%** | 380 |
| Item 1A (Risk Factors) | 194 | **81.5%** | 296 |
| Item 3 (Legal Proceedings) | 174 | 73.1% | 6 |
| Item 1A **and** Item 7 | 193 | **81.1%** | |

**The golden set's 12/12 did not generalise, and the shortfall is the honest
headline of this section.** Roughly one filing in five yields no MD&A, so any
"no signals found" answer is, for that fifth, really "the section could not be
read". That is precisely why `SectionCoverage` records `located` per section so
a caller can tell the two apart — but it is a real ceiling on recall, and it is
not a Phase 10 defect to fix here: it is Phase 4's heading detection meeting
older and more varied filings than the golden set contained.

A-10 is therefore **partially confirmed**: reliable enough to build on, at a
measured 81%, not the near-certainty a 12-filing sample implied.

## 9. QM-04 — precision and recall

### Precision

**73.4% (47 of 64 hand-labelled signals).** Every label is in
`evaluation/phase10_precision_labels.csv` with the reason for each failure.

A **development sample** of 48 signals was labelled first, against an earlier
version of the catalog, and is kept separately in
`evaluation/phase10_development_labels.csv`. It diagnosed six classes of false
positive, which were fixed. The 73.4% above is measured on a **fresh draw at a
different seed**, so the reported number is not quoted on the sample the
patterns were repaired against.

| Signal | Precision |
|---|---|
| `GOING_CONCERN_DOUBT` | 4/4 |
| `BANKRUPTCY_CONTEMPLATED` | 5/5 |
| `DELISTING_NOTICE` | 4/4 |
| `MATERIAL_WEAKNESS` | 6/7 |
| `DEBT_RESTRUCTURING` | 5/7 |
| `DEBT_DEFAULT_OR_ACCELERATION` | 6/9 |
| `ASSET_IMPAIRMENT` | 3/4 |
| `LIQUIDITY_SHORTFALL` | 3/4 |
| `DIVIDEND_SUSPENSION` | 5/8 |
| `COVENANT_WAIVER_OR_AMENDMENT` | 2/3 |
| `COVENANT_BREACH` | 2/4 |
| `CREDIT_RATING_DOWNGRADE` | 2/5 |

**The three signals with the highest measured lift are also the three that are
never wrong.** `GOING_CONCERN_DOUBT`, `BANKRUPTCY_CONTEMPLATED` and
`DELISTING_NOTICE` are 13/13 on precision and 5.49x, 4.07x and 6.10x on lift.
The convergence is not a coincidence: all three are statutory disclosures with
stable wording, which is the catalog's own selection rule working.

### What the surviving false positives are

The 17 failures are not scattered. They fall into four shapes, and each is one
editable line away from fixed — which is the property a rules layer is *for*:

1. **Contractual prose that survives the gate** (5 of 17). "The breach of any
   covenants will result in an event of default" describes a debt agreement's
   terms, in the indicative, so no mood test can catch it. `excludes_context`
   catches the common shapes and missed these.
2. **A pattern bridging too far** (2). `rt.downgraded` allows ~110 characters
   between "lowered" and "ratings", which let it reach across unrelated prose:
   "*lowered* the per unit cost as fixed lease operating costs were distributed
   over these increased volumes" was reported as a credit-rating downgrade.
3. **Affirmative compliance with an unanticipated subject** (2). The
   compliance-denial cues are anchored on "we" and "the company"; "*The
   Company's interest coverage ratio* ... was in compliance with the covenant"
   is neither, so a statement of compliance was emitted as a breach.
4. **Optionality read as action** (2). "We have the ability to continue to
   suspend dividend payments" is not a statement that a dividend was suspended.

These are recorded rather than quietly fixed, because the precision figure
above describes the shipped catalog and fixing them now would leave it
describing something else.

### Recall

`evaluation/phase10_recall_pool.csv` holds 150 candidates from a deliberately
over-broad keyword sweep (`nlp/recall_sweep.py`) — bare topic words, no gate,
no context, no polarity — each already carrying the catalog's own verdict, so a
labeller decides only whether a sentence is a true instance and the arithmetic
follows.

~~That pool is emitted and not yet labelled, so recall is not reported.~~
**Labelled in Phase 17 ([D-055](decision_log.md)); the pool is
`evaluation/phase10_recall_labels.csv`.**

> **Recall = 8 / 21 = 38.1% [20.8%, 59.1%]**, *relative to the sweep's reach*
> — an upper bound on true recall, never an estimate of it, because a
> disclosure phrased in words neither matcher contains is invisible to both.
> The qualifier travels with the number.

Of 150 candidates: 21 `true_signal`, 89 `boilerplate`, 40 `unrelated`. A
sentence counts as a true instance only when it *asserts* the condition its
code names, about this filer — hypotheticals, definitions, accounting
policies, negations and other companies' distress are excluded, because the
catalog is built to exclude them ([D-035](decision_log.md)) and counting them
would score the layer against a target it was designed not to hit.

| Code | True instances | Caught | Recall |
|---|---:|---:|---|
| `asset_impairment` | 16 | 6 | 0.375 [0.185, 0.614] |
| `dividend_suspension` | 2 | 0 | 0.000 [0.000, 0.658] |
| `debt_restructuring` | 1 | 0 | 0.000 [0.000, 0.794] |
| `going_concern_doubt` | 1 | 1 | 1.000 [0.207, 1.000] |
| `credit_rating_downgrade` | 1 | 1 | 1.000 [0.207, 1.000] |
| the other six codes | 0 | 0 | — |

**Three things matter more than the headline.**

- **The misses are concentrated and the catalog disagrees with itself.** Two
  sentences reporting an impairment charge's effect on the effective tax rate
  were caught; "*Excluding the $2.1 billion non-cash, pre-tax goodwill
  impairment charge recorded during 2011*, our operating expenses increased…"
  was not. They are recorded rather than repaired, for the same reason the 17
  precision failures above are: fixing first would leave the reported figure
  describing a catalog that was never shipped.
- **The pool re-confirms precision independently: 8 of 8.** It was generated by
  a different matcher, so this is not the precision sample re-scored.
- **The pool is blind where it matters most.** Six of twelve codes have no true
  instance in it, including `bankruptcy_contemplated` and `delisting_notice` —
  two of the three highest-lift codes. So 38.1% is substantially a statement
  about impairment detection wearing the catalog's name, and the fix is a
  larger pool weighted towards the statutory disclosures, which needs the sweep
  re-run rather than a relabelling.

## 10. Limitations

1. ~~**Recall is unmeasured.**~~ **Measured in Phase 17 at 38.1% [20.8%,
   59.1%] relative to the sweep's reach** (§9). The gap that replaces it is
   narrower and sharper: **the pool contains no true instance of six of the
   twelve codes**, including two of the three highest-lift ones, so the
   catalog's recall on the disclosures that carry the signal is still unknown.
   16 of the 21 true instances are `asset_impairment`.

2. **One filing in five yields no MD&A** (§8). For those, "no signals" means
   "not read". `SectionCoverage` makes that distinguishable in the data, but it
   is a ceiling on what this layer can find.

3. **Precision is 73.4% on 64 labelled signals**, an interval this sample size
   cannot narrow much. The per-signal figures rest on 3–9 labels each and
   should be read as direction, not as rates.

4. **The labels are mine.** There is no second annotator and no adjudication,
   so a systematic misreading on my part is invisible. The rule used was *does
   this sentence, as quoted, support this signal code for this filer?* — not
   *is this company in trouble?*. Every label and its reason is committed so
   the judgement can be disputed.

5. **The corpus inherits Phase 8's cohort confound**
   ([D-032](decision_log.md)). Event companies are large public filers by BRD's
   own eligibility rule. Comparison filings are year-matched but **not
   size-matched**, so part of every lift in §6 may be a size or sector effect
   rather than a distress effect. These are ratios of rates inside a biased
   frame; they are not evidence that the same separation would appear in a real
   portfolio.

6. **Six signals rest on fewer than 10 event filings**, so their lifts are
   shown but do not set `Specificity`.

7. **Nothing here reads Item 8's notes.** The going-concern note itself lives
   there, and is caught only because Item 7 cross-references and restates it.
   Whether reading the notes adds signal or merely duplicates it is untested.

8. **English, US GAAP, 10-K only.** The patterns encode US disclosure
   conventions and would need rebuilding for any other regime.

## 11. What Phase 11 receives

`NarrativeRiskReport` per filing, carrying `signals` (each with its code,
assertion, specificity, `pattern_id` and verbatim `EvidenceQuote`) and
`coverage` (which sections were read, and why not, if not).

Three things it should use and one it should not:

- **Use `specificity`**, not signal counts. §6 is the reason: a filing with
  three `ASSET_IMPAIRMENT` signals is not riskier than one with a single
  `GOING_CONCERN_DOUBT`.
- **Use `coverage`** to tell "no signals" from "not read" (§8).
- **Use `assertion`** — `NEGATED` is emitted on purpose. SandRidge's FY2015
  10-K affirms compliance with its note covenants two months before its
  petition while disclosing a covenant violation elsewhere in the same filing;
  a contradiction between an affirmation here and a Phase 6 ratio is exactly
  what Phase 11 exists to surface.
- **Do not sum them into a score.** No composite here, for the same reason as
  [D-022](decision_log.md).
