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

**Phase 1 of 20 — Problem definition & product design (complete).**
No application code yet.

## Documentation

| Document | Purpose |
|---|---|
| [Product requirements](docs/product_requirements.md) | Problem, users, inputs/outputs, requirements, success criteria |
| [User workflow](docs/user_workflow.md) | Monitoring cycle, review lifecycle, human-in-the-loop boundary |
| [Scope](docs/scope.md) | MVP, later work, non-goals |
| [Assumptions](docs/assumptions.md) | What the design depends on and how each assumption will be checked |
| [Risks](docs/risks.md) | Risk register with mitigations |
| [Data feasibility](docs/data_feasibility.md) | Candidate training data and the Phase 3 decision gate |
| [Decision log](docs/decision_log.md) | Architectural and product decisions |
| [Roadmap](docs/roadmap.md) | Phase plan and status |

## Core principles

1. The analyst decides; the system drafts.
2. Deterministic code for arithmetic and accounting checks — never an LLM.
3. Every number, flag, signal and conclusion is traceable to evidence.
4. "Insufficient information" beats a confident fabrication.
5. Assessments use only information available as of their date.
6. History is append-only.
