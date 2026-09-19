# Engineering Setup — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | Phase 2 |
| **Date** | 2026-09-14 |
| **Related** | [decision_log.md](decision_log.md) D-012 · [roadmap.md](roadmap.md) |

## 1. Python 3.12 library compatibility check

Before pinning the environment to Python 3.12, the ML and PDF libraries the
roadmap expects to need (Phases 4-5, 8-9) were installed into a scratch
Python 3.12.10 virtual environment and imported, to confirm prebuilt wheels
exist and nothing requires a compiler on this machine.

| Library | Version resolved | Used for | Result |
|---|---|---|---|
| pandas | 3.0.5 | Tabular financial data | ✅ wheel, imports |
| numpy | 2.5.3 | Numeric core | ✅ wheel, imports |
| scikit-learn | 1.9.1 | Phase 8 baseline model | ✅ wheel, imports |
| shap | 0.52.0 | Phase 9 explainability | ✅ wheel, imports |
| pdfplumber | 0.11.10 | Phase 4 PDF text/table extraction | ✅ wheel, imports |
| pymupdf | 1.28.2 | Phase 4 PDF extraction (alternative engine) | ✅ wheel, imports (`fitz` import alias is deprecated; use `import pymupdf`) |
| lxml | 6.1.3 | HTML/XML parsing | ✅ wheel, imports |
| streamlit | 1.63.0 | Proposed UI (D-012) | ✅ wheel, imports |
| sqlalchemy | 2.0.52 | Phase 13/15 persistence | ✅ wheel, imports |
| pydantic / pydantic-settings | 2.13.5 / 2.15.0 | Config | ✅ wheel, imports |

All 64 resolved packages installed from prebuilt wheels with no source
builds. **Conclusion: Python 3.12 is confirmed compatible with every library
currently anticipated through ~~Phase 15~~ the end of the project.** This was a
point-in-time check when written, with the instruction to re-run it
(`uv sync --all-extras` in a scratch venv) if a phase needed a library not
listed here.

> **Held, and it is worth saying so (Phase 19).** All twenty phases ran on this
> runtime. Two libraries were added after this check — `shap` in Phase 9 and
> `google-genai` in Phase 12 — and neither needed a different Python.
> [A-19](assumptions.md) is closed on that basis.

## 2. Toolchain

- **Python version:** 3.12, pinned via `.python-version` and
  `requires-python = "==3.12.*"` in `pyproject.toml`.
- **Dependency management:** [uv](https://docs.astral.sh/uv/). `pyproject.toml`
  declares runtime dependencies plus optional-dependency groups (`ml`, `pdf`,
  `ui`, `db`, `dev`) matching the roadmap phase that first needs them, so each
  phase installs only what it needs: `uv sync --extra ml --extra dev`, etc.
  `uv.lock` pins exact resolved versions for reproducibility.
- **Config:** `pydantic-settings`, reading from environment variables and
  `.env` (`src/credit_risk_copilot/config.py`). `.env.example` documents every
  setting; `.env` itself is gitignored.
- **Logging:** stdlib `logging`, configured once via
  `credit_risk_copilot.logging_config.configure_logging()`. Level and format
  (`text` or single-line `json`) are controlled by `LOG_LEVEL` / `LOG_FORMAT`.
- **Tests:** `pytest` with `pytest-cov`, configured in `pyproject.toml`
  (`testpaths = ["tests"]`).
- **Lint / format / types:** `ruff` (lint + format) and `mypy` (type
  checking), both configured in `pyproject.toml`.

## 3. Common commands

```
uv sync --extra dev --extra pdf  # base + dev tools + extraction (Phase 4 onward)
uv sync --all-extras             # everything, for local development
uv run pytest                    # tests + coverage
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy src                  # type check
```

The `pdf` extra (`lxml`, `pdfplumber`, `pymupdf`) is required from Phase 4: the
extraction package and its tests import it. `uv sync --extra dev` alone will
leave those tests failing on import.

The `ml` extra (`scikit-learn`, `shap`) is required from Phase 8, for the same
reason: `credit_risk_copilot.modeling` and its tests import it.

Data-building scripts, all cache-first and safe to rerun:

```
uv run python scripts/phase3_data_audit.py        # BRD <-> SEC linkage audit (Phase 3)
uv run python scripts/build_golden_set.py         # golden evaluation set (Phase 4)
uv run python scripts/table_extraction_spike.py   # R-19 library measurement (Phase 4)
uv run python scripts/evaluate_multi_filing.py    # M-4 multi-filing path (Phase 8)
uv run python scripts/validate_multi_filing.py    # M-4 validation: signals, restatements, vintages
uv run python scripts/phase8_build_corpus.py      # modelling corpus (Phase 8)
uv run python scripts/phase8_build_dataset.py     # point-in-time panel (Phase 8)
uv run python scripts/phase8_train_evaluate.py    # baselines, ablation, artifact (Phase 8)
uv run python scripts/phase9_pit_universe.py      # point-in-time filer universe (Phase 9)
uv run python scripts/phase9_pit_corpus.py       # point-in-time comparison cohort
uv run python scripts/phase9_pit_panel.py        # survivor vs point-in-time re-measurement
uv run python scripts/phase9_size_matched.py     # eligibility/size-matched cohort test
uv run python scripts/phase9_explain.py          # global drivers, era stability, local examples
uv run python scripts/phase9_diagnostics.py      # missingness, confound probes, errors
uv run python scripts/phase9_stability.py        # attribution stability, ranking analysis
```

> `build_golden_set.py` takes roughly ten minutes per filing on a first run,
> dominated by HTML→PDF rendering. Everything it downloads and renders is
> cached under `data/`, so reruns are fast and cost no SEC requests.

> The Phase 8 scripts run in the order listed. `phase8_build_corpus.py` makes a
> few thousand rate-limited SEC requests and writes ~1.4 GB of `companyfacts`;
> `phase8_build_dataset.py` then runs entirely offline but takes roughly an
> hour, because the point-in-time rule requires re-resolving each company's
> visible history at every filing date rather than resolving it once
> ([D-026](decision_log.md)).

> The Phase 9 scripts have the same shape. `phase9_pit_universe.py` streams 48
> quarterly EDGAR indexes (~50 MB each) and keeps only the annual-filing rows;
> `phase9_pit_corpus.py` then screens and fetches a second cohort (~1.7 GB);
> `phase9_pit_panel.py` rebuilds the panel and takes about an hour for the same
> reason `phase8_build_dataset.py` does. The three analysis scripts
> (`phase9_explain.py`, `phase9_diagnostics.py`, `phase9_stability.py`) run
> offline from the Phase 8 panel in a few minutes each.

## 4. Continuous integration

`.github/workflows/checks.yml` runs the four commands above — pytest, `ruff
check`, `ruff format --check` and `mypy` — on every push to `main` and every
pull request. It deliberately does **not** run the golden-corpus evaluations
(QM-01 to M-4): `data/` is gitignored, runs to gigabytes, and is rebuilt by
scripts that make thousands of rate-limited SEC requests. Those stay local,
reproducible-on-demand measurements; CI's job is to keep the code that
produces them honest.

## 5. Line endings

`.gitattributes` normalizes all text files to LF in the repository
(`* text=auto eol=lf`), overriding any contributor's local `core.autocrlf`.
This is what stops Git's "LF will be replaced by CRLF" warnings on Windows
checkouts. Windows batch/PowerShell scripts are the explicit exception
(`eol=crlf`), since `cmd.exe` requires CRLF line endings to run them.
