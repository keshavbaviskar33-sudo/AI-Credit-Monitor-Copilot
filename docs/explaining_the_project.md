# Explaining the project

| | |
|---|---|
| **Status** | Complete as of Phase 19 (2026-09-19) |
| **Purpose** | To be able to say what this is, why it is built this way, and what it has actually proven — without overclaiming |
| **Decisions** | [D-056](decision_log.md) |
| **Related** | [measured_results.md](measured_results.md) is the source for every number below · [architecture.md](architecture.md) · [roadmap.md](roadmap.md) |

> **Rule for this document.** It repeats no figure it cannot point at, and it
> never rounds one favourably. If a question has an uncomfortable answer, the
> uncomfortable answer is written down here, because the alternative is
> improvising it under pressure.

---

## 1. The sixty-second version

> A credit analyst holds exposure to a few hundred companies. Every time one
> files a 10-K, somebody has to answer *did this borrower get riskier?* — and
> today that means re-keying the financials into a spreadsheet, recomputing
> ratios, reading the filing for warning signs, and writing a view.
>
> This builds the draft of that answer. When a new annual filing lands it
> produces four independent reads of the company — deterministic ratios and
> trends from the XBRL facts, a point-in-time bankruptcy-hazard ranking with
> per-prediction attribution, risk disclosures mined from the filing's own text
> with verbatim quotes, and the explicit contradictions between those three —
> then one grounded LLM call writes it up, and **every claim in that write-up
> is checked against its evidence by code before an analyst ever sees it.** The
> analyst approves, modifies or rejects; the draft is immutable and the store
> is append-only.
>
> It deliberately has **no composite risk score**. Where a credit interface
> would put `RISK 72/100`, this puts three independent verdicts and their
> disagreements, because the disagreement is the finding an average would
> destroy — and because I measured whether combining the layers helps, and it
> does not.

If only one sentence is available, use the last paragraph. It is the thing
about the project that is both true and unusual.

## 2. The five-minute version

### What it does, in order

1. **Fetch** — SEC `companyfacts` (XBRL, as filed) and the 10-K HTML. Rate-limited, cached, declared User-Agent.
2. **Canonicalise** — 26 concepts, each with an ordered chain of XBRL tags *and a declared policy for how those tags relate*: synonyms, differently-scoped versions, or additive components. Value accuracy **97.2%** on a golden set with XBRL ground truth.
3. **Compute** — 13 ratios, four explicit statuses, structured warnings. Every ratio is a pure function of one period's own facts.
4. **Trend** — 5 dimensions, 9 signal codes, a stated 5-period analysis window, and no composite. A dimension with ratios moving both ways is `MIXED`, never netted.
5. **Rank** — a 365-day discrete-time bankruptcy hazard over a company × filing panel, evaluated walk-forward out-of-time, with three redundant layers enforcing that no row can see a filing received after its own date.
6. **Explain** — exact additive attribution, grouped by financial dimension rather than by feature, with a chain from contribution → feature → ratio → fact → accession → filing date.
7. **Read the text** — 12 disclosure codes, each match classified for *assertion mood* before it is emitted, with a verbatim quote and character offsets.
8. **Combine** — a content-addressed evidence register, seven contradiction rules and four corroboration rules. Every finding names both sides and adjudicates neither.
9. **Draft** — one LLM call, a typed claim schema, eight grounding checks. A claim citing an evidence ID that does not exist, stating a number absent from the evidence, rewording a quotation, or smuggling in a "probability of default" is caught by code.
10. **Review** — analyst approve/modify/reject with a required comment, stored append-only in SQLite with `BEFORE UPDATE`/`BEFORE DELETE` triggers that abort.
11. **Show** — a Streamlit workspace whose view models import no UI framework, so what the screen is allowed to say is unit-tested without a browser.

### The three things to lead with

**One.** *The hardest problem was not the model, it was proving the model meant
anything.* The pooled ROC-AUC is 0.887. It is not quotable, and the reason is a
diagnostic I had to build: train the same features to predict **which cohort a
row came from** instead of the label. If that probe scores as well as the
label, the model may be reading the sampling design. It did — for three
successive panel constructions. It stopped doing so on the fourth, which was
the one that applied the bankruptcy database's *own* eligibility rule to both
cohorts rather than matching a size distribution. That is where **0.817 [0.778,
0.851] against a probe of 0.817** comes from, and it is the only pooled
bankruptcy figure here that survives its own probe.

**Two.** *A signal that fires on everything carries no information, and I can
prove it with one pair of rows.* Every 10-K ever filed discusses covenant
breach, default and bankruptcy — Item 1A's statutory job is to enumerate
everything that could go wrong. Ungated, covenant language appears in **59%**
of the filings of companies that did not fail and **60%** of those that did.
Lift **1.02**: to two decimal places, nothing. Classify each match for whether
the filer is *asserting* the condition or *listing it as a hypothetical*, and
the same patterns over the same sentences give **22.0% against 9.2%** — lift
**2.40**. The mood of the sentence, not its vocabulary, is the signal.

**Three.** *Three negative results, and they are the most interesting content.*
Combining the layers does not improve the ranking (+0.000 [−0.082, +0.098] at a
matched alert budget). Rebuilding the negative cohort point-in-time changed
nothing and made the confound worse. SHAP is unnecessary for the model that
shipped — the exact linear decomposition reconstructs the model's own output to
3.6e-15. Each of those replaced a guess with a measurement, and two of them
overturned something I had already written down.

## 3. The four questions that are hardest to answer well

### "So how accurate is it?"

The honest answer has a shape, and the shape is the point.

> For the logistic hazard model, **ROC-AUC 0.817, interval 0.778 to 0.851**, on
> a point-in-time panel restricted to the rows that meet the bankruptcy
> database's own size-eligibility rule — base rate 8.1%, walk-forward
> out-of-time, interval clustered by company. That figure is quotable because
> the cohort probe on the same panel scores 0.817 too: the model is not
> just recognising which sample a company came from.
>
> The **gradient-boosting model scores higher — 0.887 pooled — and I will not
> quote it**, because its probe gap does not close under any construction I
> tried. It is still the primary model, because on a paired within-cohort test
> it genuinely beats the linear one, and because its top drivers there are
> leverage, profitability and liquidity while the *linear* model's are
> data-availability artefacts.

Then the caveat that must not be skipped: **the training base rate is 8.1% and
the real-world rate is 0.39%** — 367 bankruptcies over 93,394 SEC
annual-filer-years. Anyone reading a score as a probability is reading it
wrong, which is why the output is a percentile and why the schema attaches a
`NOT_CALIBRATED` caveat automatically.

**The single easiest thing to state wrongly** is to blur those two models. The
form that is wrong: *"it gets 0.89 and the confound is handled."* The form that
is right: *the confound closes for the logistic model and does not close for
boosting; only the logistic figure is quotable, and boosting is nonetheless
primary on a different and paired test.*

### "Why is there no risk score? Isn't that the product?"

Four independent reasons, and the fourth is the one that closes it.

1. There is nothing honest to build one from: a ranking metric, a
   threshold-driven trend label and a regex hit, averaged into one uninspectable
   digit that would then be the only thing anyone read.
2. The model output is not a probability (calibration slope 0.326), so it
   cannot be a term in an average of anything.
3. A number in a large font with a caveat underneath is read as the number. The
   caveat is the part that gets skipped.
4. **I measured whether a composite would have paid, and it would not.** At a
   matched alert budget, agreement between all three layers is exactly as
   precise as the model's own top-k, and two of four agreement rules are
   measurably *worse*. There was nothing for the weights to buy.

The refusal is enforced rather than intended: a test fails if a field named
`score`, `confidence`, `rating` or `severity` appears on the objects the page
renders. The desk groups companies by **named reason** rather than ranking
them, because an ordering would reintroduce the composite as a sort key — where
it would be even harder to notice.

### "Isn't the LLM the risky part?"

It is, which is why the deliverable of that phase is **the verdict on the
draft, not the draft.** The call is four lines. The validator is the largest
module in the package, imports no provider SDK, and needs no network.

That inversion exists because synthesis is the one place where everything
underneath can be silently undone. A paraphrased quotation destroys the
verbatim guarantee. A percentile rounded into a different number destroys the
provenance chain. "A 72% probability of default" destroys the whole framing.
**None of those failures is visible in the output** — they all read as fluent
prose.

Measured by fault injection over 176 real assessments, because a live model
gives you whatever it produced that day: **0.000 false-positive rate, 100%
detection across seven injected fault classes.** And then it caught a real one
on the first live batch — the model reproduced 195 characters of a filing
exactly and dropped the word *our* from inside the quotation.

The validator's largest hole is stated rather than patched: **it does not check
whether a claim is true given its evidence.** "Leverage is improving" citing a
deteriorating-leverage item passes every check. The only tools for that
judgement are another model or the analyst, and the analyst was assigned it in
the first decision the project made.

### "What would you do differently, or next?"

- **Run the multi-filing path before building on it.** It was implemented,
  unit-tested and exported — and had never been executed against real data. Two
  phases of quality numbers were measurements of the harness. Running it moved
  conclusive trends 40.4% → 91.7% and turned one company's "0 signals" into a
  corrected false negative of 10.
- **Do not state a bias direction without measuring it.** I disclosed a
  shortcut *and asserted which way it biased three rules*. Two of the three
  were wrong, one of them vacuous. A disclosure with an unmeasured direction
  attached is not a smaller claim, it is a different one.
- **Next, in order:** pay the outstanding synthesis debt (a credential, not
  work); match the negative cohort on industry as well as eligibility
  (separability 0.87–0.95 is known and unmatched); draw a recall pool weighted
  towards the high-lift disclosure codes, since six of twelve have no true
  instance in the current one; and hold the demo companies out of training,
  which was proposed in the risk register and never done.

## 4. Things to be careful not to say

| Do not say | Because |
|---|---|
| "It predicts bankruptcy with 89% accuracy" | Accuracy is never reported — at a 5% event rate, "no bankruptcy" scores above 93%. And 0.887 is the unquotable figure |
| "The confound is fixed" | It closes for one model family on one panel, and industry is still unmatched |
| "91.7% recall" or "38% recall" unqualified | The NLP figure is recall *relative to a keyword sweep's reach*, and it is dominated by a single code. The 91.7% is conclusive *trend directions*, a different thing entirely |
| "A 73% chance of distress" | The output is a percentile in a ranking. Calibration slope 0.326 |
| "Validated by analysts" | There was no access to practising analysts. The personas come from public material, and that is a stated limitation |
| "The demo shows out-of-sample performance" | The workspace runs on 163 companies from the labelled corpus. It demonstrates the pipeline, not generalisation |
| "Two providers were compared" | One provider, 12 drafts. The second client has never made a call, and that debt is reported unpaid |

## 5. If someone reads only one thing

Send them [measured_results.md](measured_results.md) §2 — the three tiers of
what may and may not be quoted — and [architecture.md](architecture.md) §2, the
nine boundaries and what each one buys. Those two tables are the project.
