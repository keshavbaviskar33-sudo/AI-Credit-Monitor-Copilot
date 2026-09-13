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

**Phase 3 of 20 — Data acquisition & understanding (in progress).**
Phase 2 (engineering environment) is complete. Phase 3's dataset decision
gate is resolved: training data will be a self-built SEC XBRL + bankruptcy-
records dataset ([D-013](docs/decision_log.md)). Building the linked dataset
itself is next; no product code yet.

## Environment setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync --extra dev       # base dependencies + tests/lint/types
cp .env.example .env      # then fill in SEC_USER_AGENT at minimum
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
