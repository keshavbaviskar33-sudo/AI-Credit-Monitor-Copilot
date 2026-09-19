# AI Credit Risk Monitor Copilot

A human-in-the-loop credit monitoring copilot. When a US public company in an
analyst's portfolio files a new 10-K, it produces an evidence-backed **draft**
reassessment — deterministic ratios and trends, an explainable bankruptcy-hazard
ranking, risk disclosures mined from the filing's own text, and the explicit
contradictions between those layers — which a human analyst then approves,
modifies or rejects.

It never makes a credit decision, and it deliberately has **no composite risk
score**. Where a credit interface would put `RISK 72/100`, this puts three
independent verdicts and their disagreements — because the disagreement is a
finding an average would destroy, and because combining the layers was measured
and does not improve the ranking.

> ⚠️ **Analytical aid only.** Outputs are drafts for a qualified analyst. This
> is not a credit decision, not a credit rating, and not investment advice.

**Who it is for:** a credit monitoring analyst at a bank, private credit fund or
credit-focused asset manager, doing periodic surveillance of existing borrowers.
Secondary: a risk manager consuming *analyst-approved* assessments, and a model
validator who needs provenance and evaluation evidence.

---

## The pipeline, end to end

```text
SEC companyfacts (XBRL, as filed) ─→ canonical facts ─→ ratios ─→ trends & signals
                                       26 concepts       13         5 dimensions
                                       97.2% accurate    ratios     no composite
                                            │                            │
                                            ├──→ point-in-time panel ─→ 365-day bankruptcy
                                            │    3 leakage layers       hazard, ranked,
                                            │                           explained per row
                                            │                                │
10-K HTML ─→ item sections ─→ 12 disclosure codes, gated on whether the filer   │
                              is ASSERTING a condition or listing it as a risk  │
                              verbatim quotes, character offsets                │
                                            │                                   │
                                            ▼                                   ▼
                          one addressable assessment, as of a chosen date
                          content-hashed evidence · contradictions · no score
                                            │
                          one grounded LLM call ─→ draft note, every claim
                          checked against its evidence by code, before an
                          analyst sees it
                                            │
                          analyst approves / modifies / rejects
                          immutable draft · append-only store · derived lifecycle
```

Each stage is a package under `src/credit_risk_copilot/`, and the boundaries
between them are load-bearing — see [architecture.md](docs/architecture.md).

## Running it

Requires Python 3.12. Install with `uv sync --extra dev --extra pdf --extra ml
--extra ui`, then invoke the interpreter directly:

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q      # 758 tests
./.venv/Scripts/python.exe scripts/build_workspace_db.py   # 202 assessments, 163 companies
./.venv/Scripts/python.exe -m streamlit run app.py
```

Copy `.env.example` to `.env` and set `SEC_USER_AGENT` at minimum — SEC's
fair-access rules require a descriptive User-Agent. `LLM_PROVIDER` /
`LLM_API_KEY` are only needed for a live synthesis call; everything else,
**including the grounding validator and its entire measurement**, runs without
them. Full toolchain in [engineering_setup.md](docs/engineering_setup.md).

## What it has actually proven

Every figure below carries the population it was measured on. The full register,
with the caveats that must travel with each number, is
[measured_results.md](docs/measured_results.md).

| | Measured | Population |
|---|---|---|
| **Bankruptcy discrimination** | **ROC-AUC 0.817 [0.778, 0.851]**, against a cohort-separability probe of **0.817** | Logistic hazard model on an eligibility-matched point-in-time panel, base rate 8.1%, walk-forward out-of-time, company-clustered interval. The only pooled figure here that its own confound probe does not beat |
| **Extraction accuracy** | **97.2%** value/period accuracy, 0 wrong values | 12-filing golden set against XBRL ground truth |
| **Verbatim evidence** | **2,355 of 2,355 quotes verbatim**, 0 failures | 238 filings, verified by slicing each quote back out at the offsets it claims |
| **The assertion gate** | lift **1.02 → 2.40** for covenant-breach language | Ungated, the language appears in 59% of the filings of companies that did *not* fail and 60% of those that did — to two decimals, no information |
| **Grounding validator** | **0.000 false-positive rate; 100% detection** across seven injected fault classes | 176 real assessments, measured by fault injection |
| **Point-in-time guarantee** | **202 of 202** assessments refused when dated one day early | The whole assessment corpus |
| **Append-only store** | **6 of 6** forbidden edits refused, attacking the raw connection | The full 202-assessment database |

**And three negative results, which are deliverables rather than omissions:**

- **Combining the layers does not improve the ranking.** At a matched alert
  budget, three-layer agreement is *exactly* as precise as the model's own
  top-k: **+0.000 [−0.082, +0.098]**. Two of four agreement rules are
  measurably worse.
- **Rebuilding the negative cohort point-in-time changed nothing** and made the
  confound worse. Only 22.6% of 2009–2020 annual filers survive into today's
  ticker file — and that was not the problem. The problem was eligibility.
- **SHAP is unnecessary for a linear model.** The exact decomposition
  reconstructs the model's own output to 3.6e-15. It is used only for the tree
  model, where no closed form exists.

One finding no single layer can produce: a filing that both **asserts and
denies** the same condition is **2.04×** more likely to precede a petition.

## Limitations

Stated here, not buried. Fuller list in
[measured_results.md §5](docs/measured_results.md).

1. **Gradient boosting is the primary model and its pooled figures are not
   quotable.** Its confound gap survives eligibility matching completely
   unchanged (+0.021). Only the logistic model's figure above clears its probe.
2. **The training base rate is 12× to 126× the real-world rate** of 0.39%. The
   output is a ranking position, never a probability — calibration slope 0.326,
   and the schema attaches a `NOT_CALIBRATED` caveat automatically.
3. **Bankruptcy is a strict subset of credit distress.** Any asserted distress
   disclosure is followed by a petition only 64.1% of the time, so genuinely
   distressed companies that never file are labelled safe.
4. **The live LLM sample is 12 drafts from one provider**, 11 accepted — a 95%
   interval of roughly 62%–100%. It is not a reliability figure. The second
   provider's client has never made a call; that debt is
   [reported unpaid](docs/measurement_debts.md).
5. **NLP recall is 38.1% *relative to a keyword sweep's reach***, an upper
   bound, and 16 of its 21 true instances are one code. Six of twelve codes
   have no true instance in the pool.
6. **One filing in five yields no MD&A**, so "no signals" means "not read" for
   that fifth. The data records which.
7. **No practising analyst has seen this.** The personas come from public
   material. The demo also runs on companies from the labelled corpus, so it
   demonstrates the pipeline rather than out-of-sample performance.
8. **Annual 10-K only**, US SEC registrants, non-financial operating companies.
   No quarterly path, no industry-aware thresholds, no authentication.

## Documentation

**Start here:** [Explaining the project](docs/explaining_the_project.md) ·
[Measured results](docs/measured_results.md) ·
[Architecture](docs/architecture.md) · [Decision log](docs/decision_log.md)

| Document | Purpose |
|---|---|
| [Roadmap](docs/roadmap.md) | The 20-phase plan, what each phase found, what was merged or cut |
| [Decision log](docs/decision_log.md) | D-001 … D-057. The spine of the project: every decision, its alternatives and its consequences |
| [Product requirements](docs/product_requirements.md) | Problem, users, requirements, success criteria |
| [User workflow](docs/user_workflow.md) | Monitoring cycle, review lifecycle, the human-in-the-loop boundary |
| [Scope](docs/scope.md) · [Assumptions](docs/assumptions.md) · [Risks](docs/risks.md) | MVP boundaries, what the design depends on, the risk register |
| [Data feasibility](docs/data_feasibility.md) · [Data dictionary](docs/data_dictionary.md) | Candidate training data, the Phase 3 decision gate, the chosen dataset |
| [Document extraction](docs/extraction.md) · [Golden set](docs/golden_set.md) | The two document paths, section detection, the evaluation corpus |
| [Canonical schema](docs/canonical_schema.md) | 26 concepts, tag policies, derivation rules, provenance, QM-01 |
| [Ratios](docs/ratios.md) · [Financial health](docs/financial_health.md) | Ratio catalog and status model; trends, dimensions, signals, thresholds |
| [Predictive model](docs/predictive_model.md) | Target, point-in-time contract, features, walk-forward evaluation, limitations |
| [Model evaluation & explainability](docs/model_evaluation_explainability.md) | Attribution, the cohort confound measured three ways, missingness, stability |
| [Narrative risk signals](docs/nlp_risk_signals.md) | Signal catalog, the assertion gate, SC-03, precision and recall |
| [Combined assessment](docs/combined_assessment.md) | Evidence register, contradiction rules, the as-of gate, matched-budget results |
| [Grounded synthesis](docs/grounded_synthesis.md) | Claim schema, eight grounding checks, fault injection, the live run |
| [Review & persistence](docs/review_and_persistence.md) | Review schema, append-only guarantees, derived lifecycle |
| [Analyst workspace](docs/workspace_ui.md) | Information architecture, the three reads, design system |
| [Measurement debts](docs/measurement_debts.md) | Phase 17: four debts paid, two published claims corrected, one unpaid |
| [Architecture audit](docs/architecture_audit.md) | The Phase 1–7 build-vs-buy audit (historical) |
| [Engineering setup](docs/engineering_setup.md) | Toolchain, library compatibility, commands |

## Core principles

1. The analyst decides; the system drafts.
2. Deterministic code for arithmetic and accounting checks — never an LLM.
3. Every number, flag, signal and conclusion is traceable to evidence.
4. "Insufficient information" beats a confident fabrication.
5. Assessments use only information available as of their date.
6. History is append-only.
7. Every claim is measured, or it is labelled unmeasured.

---

Bankruptcy outcome data: **Florida-UCLA-LoPucki Bankruptcy Research Database**.
Financial data: **SEC EDGAR**, used under its fair-access policy.
