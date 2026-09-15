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

**Phase 4 of 20 — Document extraction (complete).**
Phase 3 is complete: the training dataset is a self-built SEC XBRL +
bankruptcy-records dataset ([D-013](docs/decision_log.md)), audited at full
scale — 178 usable positive events, ~7,973-company candidate negative universe
([data_dictionary.md](docs/data_dictionary.md)).

Phase 4 adds the first pipeline layer: 10-K HTML and PDF extraction into
located text, tables and item sections ([extraction.md](docs/extraction.md)),
analyst upload validation (FR-04), and a golden evaluation set of filings with
XBRL reference values ([golden_set.md](docs/golden_set.md)) so extraction
accuracy (QM-01) becomes measurable. Turning extracted tables into canonical
line items — and the QM-01 number itself — is Phase 5.

## Environment setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync --extra dev --extra pdf   # dependencies + tests/lint/types + extraction
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
| [Data dictionary](docs/data_dictionary.md) | Chosen training dataset: unit of observation, target, features, provenance |
| [Engineering setup](docs/engineering_setup.md) | Python/library compatibility check, toolchain, commands |
| [Decision log](docs/decision_log.md) | Architectural and product decisions |
| [Roadmap](docs/roadmap.md) | Phase plan and status |

## Core principles

1. The analyst decides; the system drafts.
2. Deterministic code for arithmetic and accounting checks — never an LLM.
3. Every number, flag, signal and conclusion is traceable to evidence.
4. "Insufficient information" beats a confident fabrication.
5. Assessments use only information available as of their date.
6. History is append-only.
