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
currently anticipated through Phase 15.** This is a point-in-time check —
re-run it (`uv sync --all-extras` in a scratch venv) if a phase turns out to
need a library not listed here.

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
uv sync --extra dev              # base + dev tools
uv sync --all-extras             # everything, for local development
uv run pytest                    # tests + coverage
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy src                  # type check
```

## 4. Line endings

`.gitattributes` normalizes all text files to LF in the repository
(`* text=auto eol=lf`), overriding any contributor's local `core.autocrlf`.
This is what stops Git's "LF will be replaced by CRLF" warnings on Windows
checkouts. Windows batch/PowerShell scripts are the explicit exception
(`eol=crlf`), since `cmd.exe` requires CRLF line endings to run them.
