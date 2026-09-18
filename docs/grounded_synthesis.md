# Grounded Synthesis — Phase 12

| | |
|---|---|
| **Status** | Complete — the validator is measured on 176 assessments by fault injection, and on **12 live drafts** from a real model (§8). The live sample is small and says so |
| **Date** | 2026-09-19 |
| **Decisions** | [D-040](decision_log.md) the verdict is the deliverable · [D-041](decision_log.md) precision comes from the claim · [D-042](decision_log.md) one call, no repair loop · [D-043](decision_log.md) the provider lives behind one seam · [D-044](decision_log.md) a second provider, and the prompt leaves the envelope |
| **Code** | `src/credit_risk_copilot/synthesis/` |
| **Scripts** | `phase12_grounding.py` (offline, measured) · `phase12_synthesize.py` (live, needs a key) |
| **Requirements** | FR-16 (one grounded call) · FR-17 (citations and numbers checked by code) · cost NFR (one call per assessment) · [A-16](assumptions.md) |
| **Related** | [combined_assessment.md](combined_assessment.md) (the input) · [nlp_risk_signals.md](nlp_risk_signals.md) (SC-03) · [predictive_model.md](predictive_model.md) |

> **The draft is not the deliverable; the verdict on the draft is.** An LLM
> writes the sentences and is not trusted to have written true ones. The
> validator is the largest module in the package, imports no provider SDK, and
> is measured against drafts that were broken on purpose — because a validator
> checked only against output a model happened to produce has not been checked.
>
> It then caught a real one. On 12 live drafts, a current model silently
> dropped a word from inside a quotation it was told to copy verbatim (§8.2).

---

## 1. What this phase is actually for

Phases 5–11 produce a citable evidence register. Phase 12 turns it into prose
an analyst can read in thirty seconds. That is the easy half, and it is the
half that can silently destroy everything underneath it: an LLM that
paraphrases a verbatim quote, rounds a percentile into a different number, or
writes "a 72% probability of default" has undone Phase 10's SC-03, Phase 9's
provenance chain and [D-010](decision_log.md) in one sentence.

So the phase is built the other way round. The call is four lines. The
*checking* is the phase.

```text
  Assessment (Phase 11)
      |  prompt.py     deterministic evidence pack, schema-constrained response
      v
  ONE Messages API call ─────────────────────────────────────────┐
      |                                                           |
      v                                                   client.py is the
  DraftSynthesis  (headline + typed claims, each citing IDs)   only module
      |                                                    that imports a
      |  validator.py   8 checks, no model, no network       provider SDK
      v
  ValidationReport   accepted / rejected, with every finding named
```

## 2. The draft is a list of claims, not a paragraph

A paragraph cannot be validated. "Leverage deteriorated sharply while the filer
affirmed covenant compliance, and the model ranks the company in the top 2%"
holds three assertions resting on different evidence; a citation attached to
the paragraph attaches to none of them in particular.

So the unit is a `Claim`: one assertion, its own `evidence_ids`, checked on its
own. Four kinds, and the kind is required rather than inferred:

| Kind | Role | May cite nothing? |
|---|---|---|
| `finding` | an observation drawn from the layers | no |
| `disagreement` | a Phase 11 contradiction, restated and **not** resolved | no |
| `limitation` | something the assessment could not establish | no |
| `check` | a next action for the analyst | yes |

The kinds exist because two of the checks are about *completeness*, and code
can only ask "did the draft attempt a disagreement claim?" if attempting one is
a typed thing rather than a stylistic one.

## 3. The eight checks (FR-17)

| Check | Catches | Verdict |
|---|---|---|
| citations resolve | an invented evidence ID | reject |
| every non-`check` claim cites something | an assertion with no source | reject |
| numbers are grounded in the **cited** evidence | a fabricated figure | reject |
| …or grounded elsewhere in the assessment | a real figure on the wrong claim | **flag** |
| quotes are verbatim | words put in the filer's mouth | reject |
| no forbidden conclusion | the output shape [D-010](decision_log.md) forbids | reject |
| contradictions are described | the failure [D-038](decision_log.md) names | reject |
| layer absences are described | silence rendered as calm | reject |

**Why a mis-cited number is flagged, not rejected.** Both are wrong; they are
not the same wrong. A fabricated figure means the model invented a measurement
and the draft is unusable. A mis-cited one means a *true* figure is attached to
a claim citing different evidence — a reviewer repoints it in a second.
Collapsing them would force a regeneration for the cheaper error and teach a
reader to ignore the category.

## 4. Deciding whether a number is "present in the evidence"

This is the part that looks like set membership and is not. The evidence holds
`97.8312`; a competent draft writes "the 97.8th percentile". Exact matching
rejects every correct draft. Loose matching accepts a fabrication that happens
to land nearby.

**The precision comes from the claim, not from a tolerance constant**
([D-041](decision_log.md)). A number written to one decimal is checked to one
decimal: the admissible gap is half a unit in the last place *the writer chose
to state*. `97.8` matches `97.8312`; `97.9` does not. No epsilon appears
anywhere in the module.

Three supporting rules, each of which exists because a real draft needs it:

- **A literal can mean more than one thing, so every reading is tried.** `22%`
  is `22.0` against a percentile field and `0.22` against a rate; `$199.5
  million` is `199,500,000` in a raw field and `199.5` in one already
  denominated in millions. Readings are offered, never values invented.
- **An unsigned literal carries its sign in the verb.** "fell 0.31" restates a
  stored `-0.31` correctly. This is the module's one deliberate permissiveness
  and it is stated as such: it also grounds "the change was 0.31" against
  `-0.31`. The magnitude still has to be real.
- **Anything the evidence literally writes is quotable.** `FY2014`, an
  accession, "3 of 4 ratios" — facts the summaries state as text and no float
  records. Checked as strings, so the numeric rule never has to loosen.

## 5. The measurement: breaking drafts on purpose

A live model gives you whatever it produced that day. If it behaves, you learn
nothing about what the validator catches. So the measurement is **fault
injection** over the 202 Phase 11 assessments.

A *reference draft* is built for each — grounded by construction, and
deliberately doing the things that break a naive validator: rounding a stored
percentile to one decimal, quoting a **clause** rather than the whole stored
sentence, naming a fiscal period that exists only as text inside a summary.
**176 of 202** assessments yield one (26 have no deteriorating dimension or no
ranking position, and are skipped rather than padded).

### 5.1 False positives — the number that has to be zero

> **0 of 176 reference drafts rejected. False-positive rate 0.000.**

This is the harder half. A validator that rejects good drafts is not strict, it
is broken, and it gets switched off in week one.

**It was not zero on the first run, and the defect is worth recording.** One
draft was rejected for *21st Century Oncology Holdings, Inc.* — the `21` in the
company's own **name** parsed as an unsupported numeric assertion. Identity
(name, CIK, as-of date, fiscal period) is not measurement, and naming it is
never a quantitative claim; it now grounds every claim in the draft. Pinned as
`tests/test_synthesis_validator.py::test_a_digit_in_the_company_name_is_not_a_numeric_claim`,
which also asserts a genuinely absent number in the same sentence is still
caught — the fix widened what counts as identity, not what counts as grounded.

### 5.2 Detection, per injected fault

| Fault | Applicable | Detected | Verdict correct |
|---|---:|---:|---:|
| `fabricated_citation` | 176 | **100%** | 100% |
| `dropped_citation` | 176 | **100%** | 100% |
| `reworded_quote` | 123 | **100%** | 100% |
| `probability_claim` | 176 | **100%** | 100% |
| `omitted_contradiction` | 128 | **100%** | 100% |
| `miscited_number` | 176 | **100%** (as a flag, by design) | 100% |
| `fabricated_number` | 176 | 99.4% as a rejection, **100% detected** | 99.4% |

`reworded_quote` is inapplicable to 53 drafts with no quotable narrative
signal, and `omitted_contradiction` to 48 assessments with no contradictions.
Both are reported rather than excluded from the denominator silently.

**The one imperfect row is a real limitation, not a rounding artefact.** With
~30 evidence items per assessment each carrying numbers, a fabricated figure
can land on a *different* real value in the same assessment — 1 of 176 did —
and is then correctly identified as a number that does not belong to the cited
evidence, but downgraded from a rejection to a flag. The collision rate is
measured rather than assumed negligible.

### 5.3 Where the precision rule actually bites

Perturb a stated number by *k* units in the last place it was written. Under
half a unit is rounding and must pass; over it is a different number and must
fail.

| k | passed | flagged | rejected |
|---:|---:|---:|---:|
| 0.2 | **100%** | — | — |
| 0.4 | **100%** | — | — |
| 0.6 | — | 1.1% | **98.9%** |
| 1.0 | — | 1.1% | **98.9%** |
| 2.0 | — | 0.6% | **99.4%** |
| 10.0 | — | — | **100%** |

The boundary lands exactly where [D-041](decision_log.md) says it should:
nothing below half a unit is detected, everything above it is — with the
residual 1.1% being the same collision effect as §5.2, caught as a flag rather
than missed.

## 6. The prompt

Deterministic by construction: same assessment, same bytes. No timestamp, no
"generated at", evidence ordered by ID (which is content-derived, so the order
is stable in a way "by layer" is not). A non-deterministic prompt cannot be
cached, cannot be diffed when a draft changes, and cannot reproduce a stored
draft — which Phase 13 needs.

The stable instructions sit in `system` behind a cache breakpoint and the
per-company evidence in `messages` after it, which is the order prompt caching
matches on. **Whether that prefix is long enough to cache is not claimed here**
— it depends on the model's minimum cacheable prefix, so the result records
`cache_read_input_tokens` and the live script reports what was actually
measured.

The response is constrained by JSON Schema (`output_config.format`), so the
model cannot return prose or a code fence. There is deliberately **no
best-effort salvage** of malformed output: a partially recovered draft would be
validated, possibly accepted, and stored as though the model had written it.

Every rule the validator enforces is also stated in the system prompt. That is
belt and braces on purpose — an instruction makes a compliant draft likely, a
validator makes a non-compliant one *detected*, and neither substitutes for the
other.

## 7. Cost

| | |
|---|---|
| API calls per assessment | **1** (asserted in `SynthesisResult.api_calls`, and by a test) |
| Mean prompt size | 7,798 characters |
| Estimated input tokens | ~1,950 |
| Estimated cost per assessment | **~$0.040** at Claude Opus 5 list price |

No tokenizer is available in this environment, so the token figure converts
characters at the conventional 4 chars/token and is labelled an estimate
wherever it appears. A live run replaces it with `usage.input_tokens`.

`AnthropicSynthesisClient` sets `max_retries=0`. The SDK's automatic retries
would turn one logical call into several billed ones, and the NFR is one call
per assessment; a rate-limit failure is surfaced to the caller, which can
decide, rather than absorbed where the cost would be invisible.

## 8. The live run

### 8.1 What was actually run

A second provider was added ([D-044](decision_log.md)) when a Gemini key became
available, which is also what forced the prompt out of one vendor's envelope:
`SynthesisRequest` now carries the instructions, the evidence and the output
schema, and each client renders it into its own wire format.

| | |
|---|---|
| Model | `gemini-3.6-flash` |
| Assessments attempted | 120 |
| Drafts returned | **12** |
| Accepted by the validator | **11 — 91.7%** |
| Findings | 1 × `non_verbatim_quote` |
| Tokens | 35,334 in / 9,503 out; **0 cached** |
| Failed calls | 108, all `429 RESOURCE_EXHAUSTED` (free-tier quota) |

**The sample is 12 drafts and nothing here pretends otherwise.** A free-tier
credential is rate-limited per minute and capped per day; the pro-tier models
return a stated quota of zero, so the default model is the most capable one an
ordinary key can reach. An acceptance rate from 12 drafts has a 95% interval
running roughly from 62% to 100% — it establishes that the pipeline works
end to end and that the validator fires on real output, and it does not
establish a reliability figure.

**Prompt caching did not engage.** `cached_content_token_count` was zero on
every call. §6 declined to claim a saving; this is the measurement that would
have supported one, and it does not.

### 8.2 The one rejection, which is the most useful result in the phase

`gemini-3.6-flash`, drafting for GT Advanced Technologies, wrote a quotation
it was told to copy character for character:

```text
model:  ...could have a further adverse effect on     share price.
filing: ...could have a further adverse effect on our share price.
```

It cited the **correct** evidence item, and its quote was an exact prefix of
the stored sentence for 195 characters before dropping the word *our*. Nothing
about the draft looks wrong; it reads as a clean, well-sourced note. This is
precisely the failure [D-040](decision_log.md) argues is invisible without a
mechanical check — Phase 10's SC-03 guarantees the stored quote is verbatim
from the filing, and one word silently removed downstream would have carried a
misquotation into a stored, analyst-facing draft.

The validator caught it, on the first live batch, at n=12.

### 8.3 What is still not measured

1. **A second provider has not been run.** The Anthropic path is written and
   tested but has never made a call — no key. Two models on the same
   assessments, which the provider-neutral prompt now makes directly
   comparable, is the obvious next measurement.
2. **The validator does not check whether a claim is *true* given its
   evidence.** "Leverage is improving" citing a deteriorating-leverage item
   resolves, carries no numbers, quotes nothing, and passes. The only tools for
   that judgement are another model — the ungrounded step this phase exists to
   avoid — or the analyst, who has it by design
   ([D-003](decision_log.md)). This is the single largest hole and it is
   deliberate.
3. **The forbidden-conclusion check is a phrase list.** Five patterns, readable
   line by line, each anchored on the assertion rather than the vocabulary so
   the *required* caveat ("the score is not a probability of default") passes.
   A model determined to smuggle a conclusion past it in other words will
   succeed; the check is a floor, not a ceiling.
4. **Completeness is checked by presence, not by coverage.** A draft describing
   two of three disagreements passes. Demanding all of them would force padding;
   demanding none would let the failure [D-038](decision_log.md) names through.
5. **Reference drafts are not model output.** They stress the rules a real
   draft stresses, but a real model phrases things nobody anticipated — as §8.2
   shows. The fault-injection false-positive rate is a lower bound on what a
   larger live run would show.

### 8.4 A result artifact was destroyed, and the guard that followed

The live run's per-draft artifact **no longer exists**. A follow-up paced run
was pointed at the same output filename; its credential had by then exhausted
the daily quota, so it wrote a file containing zero drafts over the top of the
completed twelve-draft run. The free-tier daily cap prevented regenerating it
the same day.

The figures in §8.1 and the analysis in §8.2 were read out of the artifact
before it was lost and are recorded in
`data/processed/phase12/live_gemini_summary.json`, which states its own
provenance rather than presenting itself as a run output. The individual drafts
are not recoverable.

`scripts/phase12_synthesize.py` now refuses to overwrite an output file that
already contains drafts unless `--force` is passed. A result file that cost
real API calls is not a scratch file, and the script now knows that.

## 9. What Phase 13 receives

A `SynthesisResult` per assessment: the draft, the verdict, every finding, the
model name and the token usage. Three things it should do:

- **Store the draft immutably, verdict included.** FR-19 makes the AI draft
  immutable and analyst edits separate; a draft without its verdict is a draft
  whose reliability the reviewer has to re-derive.
- **Show rejections and flags differently.** A rejected draft should not reach
  an analyst as prose; a flagged one should reach them with the flag attached.
- **Never retry silently.** `synthesize` returns a rejected draft rather than
  regenerating, precisely so the rejection rate stays visible
  ([D-042](decision_log.md)). A reviewer who cannot see how often the model
  failed cannot calibrate how much to trust the drafts that passed — and §8.2
  is what that rate is protecting them from.
