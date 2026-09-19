# AI Credit Risk Monitor Copilot

A human-in-the-loop credit monitoring copilot for credit analysts. When US
public companies in an analyst's portfolio publish new annual filings, it
prepares an evidence-backed **draft** reassessment: deterministic financial
analysis, an explainable ML distress estimate, qualitative risk signals from
filing text, and explicit contradictions and open questions. The analyst then
approves, modifies or rejects the draft and records their own judgement.

> ⚠️ **Analytical aid only.** Outputs are drafts for a qualified analyst. This
> project does not make credit decisions, is not a credit rating, and is not
> investment advice.

## Status

**Phase 14 of 20 — The analyst workspace (complete).** Two phases remain — a
measurement-debt pass and documentation ([D-045](docs/decision_log.md) merged
or cut the other four). See [roadmap.md](docs/roadmap.md) for the full phase
table.

```
uv sync --extra dev --extra pdf --extra ml --extra ui
uv run python scripts/build_workspace_db.py    # 202 assessments, 163 companies
uv run streamlit run app.py
```

The pipeline runs end to end, from SEC filings to a point-in-time risk estimate:

```
SEC companyfacts (XBRL, as filed)  ──┐
                                     ├─→ canonical facts ─→ ratios ─→ health signals
10-K HTML / uploaded PDF ─→ evidence ┘      (Phase 5)      (Phase 6)     (Phase 7)
                                                                              │
                        point-in-time features ─→ 365-day bankruptcy hazard ──┘
                                     (Phase 8)      explained per prediction (Phase 9)

10-K narrative sections ─→ risk signals with verbatim evidence (Phase 10)
                                                                              │
              all four layers ─→ one citable assessment, as of a chosen date ─┘
                                 agreements, contradictions, no score (Phase 11)
                                                    │
                          one grounded LLM call ─→ draft note, every claim
                          checked against its evidence by code (Phase 12)
```

- **Phase 3** — training dataset selected and audited at full scale: a
  self-built SEC XBRL + bankruptcy-records join ([D-013](docs/decision_log.md)),
  178 usable positive events, ~7,973-company candidate negative universe
  ([data_dictionary.md](docs/data_dictionary.md)).
- **Phase 4** — 10-K HTML and PDF extraction into located text, tables and item
  sections ([extraction.md](docs/extraction.md)), analyst upload validation
  (FR-04), and a 12-filing golden set with XBRL reference values
  ([golden_set.md](docs/golden_set.md)).
- **Phase 5** — canonical financial schema with provenance
  ([canonical_schema.md](docs/canonical_schema.md)): 26 concepts, per-concept
  tag policies and derivation rules. **QM-01: 97.2% value/period accuracy.**
- **Phase 6** — 13-ratio deterministic engine ([ratios.md](docs/ratios.md))
  with a four-state result model and structured warnings.
- **Phase 7** — trend, dimension and early-warning analysis
  ([financial_health.md](docs/financial_health.md)): 5 dimensions, 9 signal
  codes, no composite score, and (from Phase 8) an explicit analysis window.
- **Phase 8** — a leakage-checked point-in-time panel and a baseline
  predictive layer ([predictive_model.md](docs/predictive_model.md)):
  discrete-time bankruptcy hazard, walk-forward out-of-time evaluation,
  heuristic baselines and a feature-family ablation.
- **Phase 9** — explainability and trustworthiness
  ([model_evaluation_explainability.md](docs/model_evaluation_explainability.md)):
  a model-agnostic explanation layer that traces every contribution back to a
  filing, plus the diagnostics that establish **how much of the model's
  apparent performance is sampling design rather than credit risk** — enough
  that the pooled metrics are not quotable as bankruptcy prediction.
- **Phase 10** — narrative risk signals with verbatim evidence
  ([nlp_risk_signals.md](docs/nlp_risk_signals.md)): 12 disclosure codes gated
  on whether the filer is **stating** a condition or merely listing it as a
  risk. Ungated, covenant language appears in 59% of the filings of companies
  that did not fail and 60% of those that did — a lift of 1.02, no information
  at all. Gated, it separates the cohorts 22% to 9%. **SC-03 holds on 2,355
  quotes**, and every signal traces to one editable pattern.
- **Phase 11** — the four layers combined into one addressable assessment
  ([combined_assessment.md](docs/combined_assessment.md)): content-hashed
  evidence IDs, seven contradiction rules and four corroboration rules, and an
  as-of gate that enforces historical replay instead of documenting it. **The
  headline result is negative:** at a matched alert budget, agreement between
  all three layers is exactly as precise as the model's own top-k
  (+0.000 [−0.082, +0.098]), so combining does not improve the ranking. What it
  does deliver is what the synthesis and review phases need — 0 unresolved
  citations, 0 quote mismatches, 202/202 point-in-time refusals — plus one
  finding no single layer can produce: a filing that both **asserts and denies**
  the same condition is 2.04× more likely to precede a bankruptcy.
- **Phase 12** — one grounded LLM call, and the code that checks it
  ([grounded_synthesis.md](docs/grounded_synthesis.md)). The draft is not the
  deliverable, the **verdict on the draft** is: eight checks catch a fabricated
  evidence ID, a number that appears nowhere in the evidence, a reworded
  quotation, a smuggled probability of default, and a draft that quietly omits
  a disagreement. Measured by breaking 176 real drafts on purpose: **0.000
  false-positive rate and 100% detection across all seven fault classes.** Then
  run against a real model: 12 drafts on `gemini-3.6-flash`, 11 accepted. **The
  one rejection is the point** — the model reproduced 195 characters of a filing
  exactly, then silently dropped the word *our* from inside the quotation, in a
  draft that otherwise reads as clean and well-sourced. Caught mechanically, on
  the first live batch. Twelve drafts is a small sample and is reported as one.
- **Phase 13** — the analyst review layer and the audit store
  ([review_and_persistence.md](docs/review_and_persistence.md)), where "the
  analyst owns every final judgement" stops being a principle and becomes a
  schema. **Append-only is enforced by the database**, not by convention:
  `BEFORE UPDATE`/`BEFORE DELETE` triggers abort on every table, and the tests
  attack the raw connection. Supersession is *derived* — the one lifecycle
  state that looks like it needs a column is the one that proves it cannot
  have one. Verified on the full corpus: 202 assessments, **0 round-trip
  mismatches**, **6 of 6 edit attempts refused**, 39 superseded entries with
  their reviews intact.
- **Phase 14** — the analyst workspace ([workspace_ui.md](docs/workspace_ui.md)).
  **Where a risk score would normally sit, three independent reads sit
  instead** — financial trends, model ranking and the filer's own words, each
  with its method and its evidence, and their disagreements directly beneath.
  The desk groups companies by *named reason* rather than ranking them,
  because an ordering would reintroduce the composite score as a sort key.
  Numbers render monospace, risk is never carried by colour alone, and a
  navigation-level **Method & limits** page lists what the product will *not*
  show and why.

## Environment setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync --extra dev --extra pdf --extra ml   # deps + tests/lint/types + extraction + modelling
cp .env.example .env              # then fill in SEC_USER_AGENT at minimum
uv run pytest
```

See [engineering_setup.md](docs/engineering_setup.md) for the full toolchain,
the Python 3.12 library compatibility check, and all `uv` commands.

## Documentation

| Document | Purpose |
|---|---|
| [Product requirements](docs/product_requirements.md) | Problem, users, inputs/outputs, requirements, success criteria |
| [User workflow](docs/user_workflow.md) | Monitoring cycle, review lifecycle, human-in-the-loop boundary |
| [Scope](docs/scope.md) | MVP, later work, non-goals |
| [Assumptions](docs/assumptions.md) | What the design depends on and how each assumption will be checked |
| [Risks](docs/risks.md) | Risk register with mitigations |
| [Data feasibility](docs/data_feasibility.md) | Candidate training data and the Phase 3 decision gate |
| [Data dictionary](docs/data_dictionary.md) | Training dataset: unit of observation, label, features, provenance |
| [Document extraction](docs/extraction.md) | Extraction design: provenance, the two paths, section detection, limits |
| [Golden set](docs/golden_set.md) | Evaluation corpus, XBRL reference values, and the R-19 library measurement |
| [Canonical schema](docs/canonical_schema.md) | Canonical concepts, tag policies, derivation rules, provenance, QM-01 |
| [Ratios](docs/ratios.md) | Ratio catalog, status model, warnings, M-2 coverage |
| [Financial health](docs/financial_health.md) | Trend method, dimensions, signal catalog, thresholds, M-3 |
| [Predictive model](docs/predictive_model.md) | Target, point-in-time contract, features, evaluation, results, limitations |
| [Model evaluation & explainability](docs/model_evaluation_explainability.md) | Explanation layer, global/local drivers, cohort confounding, missingness, stability, errors |
| [Narrative risk signals](docs/nlp_risk_signals.md) | Signal catalog, the assertion gate, SC-03, QM-04 precision |
| [Combined assessment](docs/combined_assessment.md) | Evidence register, contradiction and corroboration rules, the as-of gate, matched-budget results |
| [Grounded synthesis](docs/grounded_synthesis.md) | Claim schema, the eight grounding checks, fault-injection results, what is not measured |
| [Review & persistence](docs/review_and_persistence.md) | Review schema, append-only guarantees, derived lifecycle state, corpus verification |
| [Analyst workspace](docs/workspace_ui.md) | Information architecture, the three reads, design system, data provenance, limitations |
| [Engineering setup](docs/engineering_setup.md) | Python/library compatibility check, toolchain, commands |
| [Decision log](docs/decision_log.md) | Architectural and product decisions |
| [Architecture audit](docs/architecture_audit.md) | Build-vs-buy / open-source audit of Phases 1–7 and Phase 8 readiness |
| [Roadmap](docs/roadmap.md) | Phase plan and status |

## Core principles

1. The analyst decides; the system drafts.
2. Deterministic code for arithmetic and accounting checks — never an LLM.
3. Every number, flag, signal and conclusion is traceable to evidence.
4. "Insufficient information" beats a confident fabrication.
5. Assessments use only information available as of their date.
6. History is append-only.
