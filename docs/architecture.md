# Architecture — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | Current as of Phase 19 (2026-09-19). Describes the system as built, not as planned |
| **Verified against** | 758 tests · 94% line coverage · `ruff check` clean · `ruff format --check` clean · `mypy --strict` clean (79 files) |
| **Decisions** | [D-056](decision_log.md) documentation architecture · every boundary below cites the decision that put it there |
| **Related** | [architecture_audit.md](architecture_audit.md) (the Phase 1–7 build-vs-buy audit) · [measured_results.md](measured_results.md) · [roadmap.md](roadmap.md) |

> **This document answers one question: why are the package boundaries where
> they are, and what does each one buy?** Several are load-bearing — removing
> them would not break a test tomorrow, and would cost something specific
> later. Each entry below names that cost. The import graph was re-derived from
> the code for this document rather than taken from the earlier audit.

For the historical build-vs-buy analysis — what was considered and rejected as
a dependency, and why the custom code is custom — see
[architecture_audit.md](architecture_audit.md). That document is a Phase 1–7
artifact and is preserved as one.

---

## 1. The shape of the thing

Eleven packages under `src/credit_risk_copilot/`, one directed acyclic
dependency graph, no cycles. Data flows down; nothing reaches back up.

```text
                    SEC EDGAR  (data.sec.gov · www.sec.gov)
                            │
              sec_edgar.py  │  throttle · User-Agent · on-disk cache
                            │
            ┌───────────────┴────────────────┐
            │                                │
    companyfacts JSON                 10-K primary document (HTML)
    (SEC's own parsed XBRL)                  │
            │                                │
      financials/                      extraction/   (lxml · pdfplumber)
      typed facts · tag policies             │
      derivation · provenance          ExtractedDocument
      as-filed history                 text · tables · item sections · errors
            │                                │
            │   ◄── corroboration only ──────┤   one-directional (D-017):
            │       (reconciliation.py)      │   finding a value raises
            │                                │   confidence; absence changes
            │                                │   nothing
      CanonicalFilingFacts                   │
            │                                │
      ratios/   13 definitions               │
            │   FactGetter protocol          │
            ▼                                │
      health/   trends · 5 dimensions        │
            │   9 signal codes               │
            │   no composite score           │
            ├──────────────┐                 │
            ▼              ▼                 ▼
      modeling/       explain/           nlp/
      point-in-time   attribution        12 disclosure codes
      panel · hazard  per model family   assertion gate
      walk-forward    evidence links     verbatim quotes
            │              │                 │
            └──────────────┴────────┬────────┘
                                    ▼
                            assessment/
                            evidence register · contradictions
                            corroborations · as-of gate
                            (no combined score)
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
              synthesis/                       workspace/
              prompt · validator               view models
              provider behind client.py        no UI framework
                    │                               │
                    ▼                               ▼
              review/  append-only SQLite      app_pages/  Streamlit
              immutable drafts · analyst        renders only
              decisions · derived lifecycle
```

Two things the diagram asserts that are worth stating flatly:

**There is no XBRL parsing in this project.** `financials/xbrl.py` reads SEC's
`companyfacts` JSON, which SEC has already parsed from the instance documents.
The hard problem is not parsing XBRL; it is that filers tag the same economic
quantity with different elements, which is what `concept_map.py` and
`resolver.py` exist for ([D-016](decision_log.md), [D-018](decision_log.md)).

**The document path does not produce numbers.** `extraction/` feeds the
narrative layer and a one-directional corroboration check, and that is all
([D-005](decision_log.md), [D-017](decision_log.md)). Numbers come from XBRL.

## 2. The boundaries, and what each one buys

Each row is a real constraint in the code, not an aspiration. "Verified" means
re-derived from the imports for this document.

| # | Boundary | Verified state | What it buys | What breaking it would cost |
|---|---|---|---|---|
| B1 | `ratios/` sees Phase 5 only through `financials.models` | Two symbols, one module: `CanonicalFact`, `FactStatus`. Input arrives through a `FactGetter = Callable[[str, str], CanonicalFact \| None]` callable, not a Phase 5 object | The ratio engine is testable against a two-line fake, and **deleting all of `extraction/` and `financials/` would not break it**. Every ratio is a pure function of one period's own facts ([D-020](decision_log.md)) | A ratio suite that can only be exercised by fetching real XBRL. Phase 6's audit stress-tested 13 ratios against distressed filers precisely because the seam made synthetic input cheap |
| B2 | `health/` imports only `ratios.{engine,models,registry}` | Never imports `financials`, `extraction` or `sec_edgar` | Phase 6 states what a ratio *equals*; Phase 7 states whether that is *stronger or weaker*. Keeping `RATIO_DIRECTIONS` in `health/direction.py` rather than in the ratio registry means a direction is a reviewable claim about economics, not a property of arithmetic ([D-022](decision_log.md)) | Direction judgements buried in the ratio catalog, where a wrong one reads as a formula rather than as an opinion. A completeness test already fails if the two catalogs drift |
| B3 | `workspace/` imports **no UI framework** | Confirmed: zero `streamlit` or `altair` imports across `workspace/*.py`. `app_pages/` holds Streamlit and does no derivation | **What the screen is allowed to say is unit-tested without a browser** — 18 view-model tests, one of which fails if a field named `score`, `confidence`, `rating` or `severity` reappears ([D-050](decision_log.md)). Replacing the renderer means rewriting `app_pages/` and keeping everything that decides what is true | The refusal of a composite score would live in a template, where the test that enforces it cannot reach. [D-052](decision_log.md) named this as the seam a React front end would attach to |
| B4 | The model provider lives behind `synthesis/client.py` | `anthropic` and `google.genai` are imported inside constructors, in one module. Nothing else in `synthesis/` imports a provider SDK | **The validator — the phase's actual deliverable — is measured over 176 real assessments with no key, no network, and no dependence on what a model did that day** ([D-043](decision_log.md)). A test suite that needs a paid key is a test suite that stops being run | The grounding measurement would not exist. When a second provider's credential arrived, adding it was one class behind an existing protocol ([D-044](decision_log.md)) |
| B5 | `explain/` defines its own schema; nothing outside it imports `shap` | `shap` appears in `explain/adapters.py` only, imported lazily | Phases 11–14 consume `ModelExplanation` and are insulated from the attribution method *and* the model family. When [D-034](decision_log.md) swapped the primary model from logistic to boosting, the explanation path changed inside one adapter | SHAP would become a load-bearing dependency of the UI, and `Explanation` has no field for an accession number — the half that makes attribution usable in a credit product ([D-029](decision_log.md)) |
| B6 | `assessment/` adjudicates nothing | Seven contradiction rules and four corroboration rules, each naming both sides. `Assessment` has no overall status field | A contradiction an analyst can check, and a measurement that could overturn a rule's own hint — one did, by a factor of ten ([D-038](decision_log.md)) | A composite score. [D-036](decision_log.md) measured that it would not even have paid: three-layer agreement is *exactly* as precise as the model's own top-k |
| B7 | The as-of gate runs over assembled evidence, not at the caller | `AsOfGate.verify` walks every item and asks it for its filing date; undated evidence is refused | A layer that over-fetched is caught by the assessment it produced rather than by its caller's discipline. **202 of 202 assessments refused when dated one day early** ([D-039](decision_log.md)) | A point-in-time guarantee that holds only for callers who remembered. It caught a leak in its own phase's test fixture |
| B8 | Append-only is a database property, not a convention | `BEFORE UPDATE` / `BEFORE DELETE` triggers `RAISE(ABORT)` on every table. No `update` method exists in `review/` | Verifiable by an auditor without reading any Python, and it survives everyone who will ever touch the file. Tests attack the raw connection: **6 of 6 forbidden operations refused** on the full 202-assessment database ([D-046](decision_log.md)) | A store that is append-only until the first hurried afternoon. Supersession being *derived* rather than stored follows directly ([D-047](decision_log.md)) |
| B9 | The point-in-time loop has exactly one implementation | `modeling/dataset.analyse_company_filings` is the only place the leakage contract is enforced; `build_company_observations` is a labelling layer on top | Phase 17 needed real Phase 7 reports for 202 filings and got them from **the same code that built the training panel**, not a lookalike ([D-053](decision_log.md)) | Two copies of the only correctness-critical loop in the project, free to drift. Phase 11 took the shortcut once and it cost a phase to check |

## 3. Where a dependency is allowed to sit

`financials/` imports `extraction.models` in two files — `reconciliation.py` and
`statements.py` — and this is the one place the document path touches the
financial path. It is deliberately one-directional and deliberately weak:
finding an XBRL value also present in the filing's own HTML tables raises
confidence and adds a provenance entry; **not** finding it changes nothing,
because HTML recall on the golden set is measured at 85.1%, not 100%. Treating
absence as a conflict would manufacture distrust the data does not support
([D-017](decision_log.md)).

`truststore` is imported by the library, in `sec_edgar.py` and inside
`GeminiSynthesisClient.__init__`. That is not an environment workaround leaking
into the code: this machine, and any machine behind a TLS-intercepting proxy,
presents certificates trusted by the OS and absent from certifi's bundle, and
without the injection the failure looks like an authentication problem. It is a
core dependency and is commented as such at both sites.

## 4. What is custom, and why

The [Phase 1–7 audit](architecture_audit.md) examined every layer against
external candidates and recommended **zero replacements**. The summary, still
accurate:

- **Custom because it is the product:** canonical concept resolution
  (`concept_map.py` + `resolver.py`), the provenance/confidence/status model,
  the derivation rules, the ratio catalog and its four-state result model, all
  of `health/`, the contradiction rules, and the grounding validator. Every
  external candidate examined either lacked the as-filed provenance
  [D-008](decision_log.md) depends on, required a commercial data vendor, or
  imposed its own opaque "standardization" in place of the reviewable
  per-concept policies [D-016](decision_log.md)/[D-018](decision_log.md)
  deliberately built.
- **Adapted, not written:** `lxml`, `pdfplumber`, `pymupdf`, `pydantic`,
  `requests`, `scikit-learn`, `shap`, `sqlite3`, `streamlit`. The custom code
  sits *above* these adapters, where domain logic belongs.
- **Deliberately not adopted:** Arelle, `edgartools`, OCR, any financial-ratio
  package, any vector database, MLflow, FastAPI, SQLAlchemy
  ([D-048](decision_log.md) removed the `db` extra Phase 2 had declared before
  the problem existed). Several would be actively harmful to provenance.

## 5. Optional dependencies, and what runs without them

`pyproject.toml` declares four extras. The split is not packaging hygiene — it
is what keeps the test suite runnable.

| Extra | Contents | What stops working without it |
|---|---|---|
| *(core)* | `pandas`, `numpy`, `requests`, `pydantic`, `pydantic-settings`, `python-dotenv`, `truststore` | Nothing; `financials`, `ratios`, `health`, `assessment` and **`review` — the audit store — all run on core plus stdlib `sqlite3`** ([D-048](decision_log.md)) |
| `pdf` | `pdfplumber`, `pymupdf`, `lxml` | Document extraction and the narrative layer's input |
| `ml` | `scikit-learn`, `shap` | Model fitting and the boosting model's attribution |
| `ui` | `streamlit` | `app.py` and `app_pages/`; `workspace/` itself still imports and tests |
| `llm` | `anthropic`, `google-genai` | A live synthesis call. The **validator and its entire measurement do not need it** ([D-043](decision_log.md)) |

`mypy --strict` runs clean with `llm` and pandas stubs absent, because those
two modules are listed in the `[[tool.mypy.overrides]]` block as handled
runtime states rather than type errors ([D-057](decision_log.md)).

## 6. The seams a replacement would go through

Asked "what would it cost to change X", the answer is one of these:

| Change | Seam | Reach |
|---|---|---|
| A different PDF library | `extraction/base.DocumentExtractor` protocol | One module. Measured tie between the two candidates means reversing [D-015](decision_log.md) would also change nothing measurable |
| A different LLM provider | `synthesis/client.SynthesisClient` protocol | One class. Done once already, in Phase 12 |
| A different attribution method | `explain/adapters.Attributor` | Three methods, no schema change |
| A different model family | `modeling/model.build_model_specs` + one `Attributor` | Done once already, in [D-034](decision_log.md) |
| A different renderer (React, Dash) | the `workspace/` package | Rewrite `app_pages/`, keep every view model and its tests |
| A second database backend | `review/ReviewStore` | The SQL carrying the append-only guarantee would have to be ported with it — a cost worth knowing before it is paid |
| A second jurisdiction | `financials/concept_map.py` + the SIC filter | US-GAAP tag chains are the assumption; IFRS/20-F is out of MVP scope ([D-002](decision_log.md)) |

## 7. What the architecture does not provide

Stated here rather than discovered later.

1. **No service layer.** The backend is a Python library. Phase 13 exposes plain
   functions, not endpoints, because building an HTTP client only Streamlit
   would call was rejected in [D-012](decision_log.md).
2. **No concurrency story.** Single analyst, single process, SQLite
   ([A-18](assumptions.md)). The append-only schema would tolerate concurrent
   readers; nothing has measured it.
3. **No migration path, by design.** `SCHEMA_VERSION` is checked on open and a
   mismatch raises rather than migrating. An append-only audit store that
   silently rewrites itself to a new shape is a contradiction; conversion means
   exporting and re-recording ([D-046](decision_log.md)).
4. **No industry awareness.** Thresholds are universal and the financial sector
   is excluded wholesale ([D-006](decision_log.md), [R-10](risks.md)).
   Industry-aware hooks are named and deferred
   ([financial_health.md §9](financial_health.md)).
5. **No quarterly path.** Annual only ([D-007](decision_log.md)); 10-Q
   year-to-date cash flows need their own handling, and
   [A-03](assumptions.md) remains open on what an annual cadence misses.
