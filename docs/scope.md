# Scope — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | v1.0 — written in Phase 1, amended through Phase 19. The MVP in §3 is built; the non-goals in §5 all held |
| **Date** | 2026-09-19 (created 2026-09-13) |
| **Related** | [product_requirements.md](product_requirements.md) · [decision_log.md](decision_log.md) · [roadmap.md](roadmap.md) · [measured_results.md](measured_results.md) |

---

## 1. Scope summary

**MVP:** a single-analyst monitoring copilot for a small watchlist of **US SEC
registrants** (non-financial operating companies), assessing **annual (10-K)**
periods, producing an evidence-backed draft reassessment per company per fiscal
year, and recording the analyst's review.

Scope changes are made through the [decision log](decision_log.md), not silently.

## 2. Company universe (MVP)

| Dimension | In scope | Out of scope (MVP) | Why |
|---|---|---|---|
| Jurisdiction | US SEC registrants filing 10-K | Foreign private issuers (20-F, IFRS); non-US companies | Consistent US GAAP taxonomy and free structured data ([D-002](decision_log.md)) |
| Company type | Non-financial operating companies | Banks, insurers, broker-dealers, REITs, investment funds, shell companies/SPACs | Their balance sheets make standard corporate ratios (current ratio, debt/equity) misleading ([D-006](decision_log.md)) |
| Data availability | Companies with XBRL financial data and ≥ 1 annual period | Companies with no XBRL data | Needed for source of record and extraction evaluation |
| Periods | Annual fiscal years | Quarterly (10-Q), trailing-twelve-month figures | 10-Q cash flows are year-to-date; handled after annual works ([D-007](decision_log.md)) |
| Trend analysis | Requires ≥ 3 consecutive fiscal years | — | Fewer years → `insufficient_data` for trends |

Industry filtering will use SEC SIC codes; the exact excluded code ranges are
defined and tested in Phase 5/7.

## 3. MVP in scope, by layer

| Layer | In MVP | Roadmap phase |
|---|---|---|
| Problem & product design | PRD, workflow, scope, assumptions, risks, data feasibility | 1 |
| Engineering foundation | Repo, environment, config, logging, tests, lint | 2 |
| Data understanding | Training-data selection, audit, data dictionary, target definition | 3 |
| Document extraction | Text-based PDF financial statements: text, tables, page numbers, errors | 4 |
| Structured source data | SEC XBRL facts (as filed) with accession numbers and filing dates | 4–5 |
| Parsing & normalisation | Canonical schema, aliases, units, signs/parentheses, multiple years, validation | 5 |
| Ratio engine | Liquidity, leverage, profitability, coverage, cash-flow ratios with explicit statuses | 6 |
| Financial health | Deterministic flags + trends + reasons; configurable thresholds | 7 |
| ML | Logistic regression baseline, out-of-time evaluation, calibration, ~~SHAP explanations~~ **attribution chosen per model family** ([D-030](decision_log.md): SHAP was measured as *unnecessary* for the linear model, which an exact closed form reconstructs to 3.6e-15, and is used only for the tree model where no closed form exists) | 8–9 |
| NLP | Risk signals from MD&A / Risk Factors with verbatim evidence; rules/classical methods first | 10 |
| Combination | Unified assessment representation; contradiction rules | 11 |
| Synthesis | One grounded LLM call with structured output and code-based grounding validation | 12 |
| Review | Approve / modify / reject; immutable drafts; review history | 13 |
| Persistence | SQLite, append-only assessment and review history | 13 (moved earlier by [D-009](decision_log.md); ~~15~~ merged into 13 by [D-045](decision_log.md)) |
| UI | Watchlist + company view organised around the five analyst questions | 14 |
| Demo | Historical replay ("as of" date) on a small watchlist | 11–14 (should-have) |

## 4. Later (post-MVP candidates)

- Quarterly (10-Q) monitoring and trailing-twelve-month metrics
- Scanned PDF / OCR extraction
- Earnings call transcripts (subject to licensing)
- News, market data, credit-rating inputs via an adapter layer (~~Phase 16~~ — **cut**, [D-045](decision_log.md); reinstate on a real need rather than to complete a table)
- Filing-behaviour signals (late filings, auditor changes, going-concern language)
- Industry-aware benchmarks and thresholds
- Covenant tracking against analyst-entered covenant terms
- Automatic detection of new filings on a schedule
- Multi-user authentication and role-based access
- Private-company (non-SEC) borrowers via uploaded documents only
- Tool-using synthesis agent that can request additional evidence (only if a concrete need is demonstrated)

## 5. Non-goals

These are **explicitly excluded**, not merely deferred:

1. **Automated credit decisions** — no approvals, declines, limit setting, pricing, covenant actions or exits.
2. **Credit ratings** — outputs are not ratings and must not be presented as comparable to agency ratings.
3. **Investment advice or trading signals.**
4. **Consumer / retail credit** — the unit of analysis is a company.
5. **Regulatory compliance claims** — the project may borrow good model-risk practice (documentation, validation, versioning) but claims no regulatory approval or compliance.
6. **LLM-computed financial figures** — all arithmetic is deterministic code.
7. **Autonomous multi-step agents in MVP.**
8. **Production infrastructure in MVP** — no microservices, queues, Kubernetes, vector databases or multi-tenant SaaS.
9. **Real-time monitoring** — the cadence is filing-driven, not intraday.

## 6. MVP demo scale

- Watchlist of roughly 10–25 companies, deliberately including companies that
  later experienced distress, so historical replay can show whether warning
  signs were visible *before* the event using only then-available filings.
- ~~Demo companies are chosen in Phase 3 and must be **excluded from any model
  training data** (or held out by time) so the demo is not a leaked success
  story.~~

> **Not done, and reported rather than quietly dropped (Phase 19).** The
> workspace runs on **163 companies drawn from the labelled Phase 11 corpus**,
> which is built from the same event and comparison cohorts the model trained
> on ([workspace_ui.md §6](workspace_ui.md)). No demo hold-out was ever
> constructed. [R-13](risks.md) named this risk in Phase 1, assigned it to
> Phases 3 and 8, and it was not taken up in either.
>
> **What this does and does not invalidate.** Every model score shown in the
> workspace comes from the walk-forward evaluation, where each row was scored
> by a fold that never saw it or anything after it — so the displayed rankings
> are out-of-fold, not in-sample fits. What is missing is a cohort the
> *sampling design* never touched. So the workspace demonstrates the pipeline
> end to end on real filings; it does not demonstrate generalisation to a
> portfolio drawn differently. Stated wherever the demo is described
> ([measured_results.md §5](measured_results.md)), and the honest fix is a
> held-out watchlist, which is a future phase's work.
