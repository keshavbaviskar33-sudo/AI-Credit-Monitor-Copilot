"""Phase 9 step 1: the point-in-time filer universe.

Phase 8's comparison cohort was drawn from SEC's **current** ticker file
(`company_tickers.json`), so every company in it survived to today by
construction. `predictive_model.md` §8 named that the phase's largest
limitation and measured its consequence: a model can predict cohort membership
at 0.79 (logistic) / 0.91 (gradient boosting) ROC-AUC, at or above its
bankruptcy score. That bounds every pooled figure in Phase 8.

The fix is a negative universe built from **who was actually filing at time
T**, including companies that have since delisted, been acquired, gone private
or simply stopped filing. EDGAR publishes exactly that: a quarterly
`full-index/YYYY/QTRn/form.idx` listing every filing received that quarter,
by form type, with CIK and receipt date. It is the authoritative
point-in-time record and it includes filers that no longer exist.

## Why this is cheap enough to be worth doing

Each index is ~50 MB, but only the annual-report lines are wanted, so the raw
file is streamed and discarded rather than cached: 48 requests, a few minutes,
and a few hundred KB stored. That is a very different cost from the "point-in-
time negative universe is a large data-acquisition project" assumption Phase 8
carried into its limitations section -- which is why this runs first, before
any Phase 9 analysis is allowed to depend on the survivorship-contaminated
cohort.

## What this script does and does not do

It produces the *universe* -- which CIKs filed an annual report in which year
-- plus a direct measurement of the survivorship gap: how much of each year's
real filer population is missing from the current ticker file. Sampling from
it, fetching facts and re-measuring the model is `phase9_pit_corpus.py`.

    uv run python scripts/phase9_pit_universe.py
"""

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any

from credit_risk_copilot.config import get_settings
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.sec_edgar import ANNUAL_FORMS, SecEdgarClient

logger = logging.getLogger(__name__)

OUT_DIR = Path("data/processed/phase9")
PIT_FILERS = OUT_DIR / "pit_filers.csv"
SUMMARY = OUT_DIR / "pit_universe_summary.json"
BRD_CASES = Path("data/raw/brd/cases.csv")
CORPUS_MANIFEST = Path("data/processed/phase8/corpus_manifest.json")

#: Years the Phase 8 panel actually contains prediction dates for
#: (`dataset_summary.json`: 2009-11-20 to 2020-01-01). Fetching beyond this
#: would cost requests for observations that cannot exist.
FIRST_YEAR = 2009
LAST_YEAR = 2020

_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"


#: Retries per quarter. A dropped quarter is not a small loss: Q1 carries
#: roughly three quarters of a year's 10-K filings (most calendar-year filers
#: report in Q1), so silently accepting one timeout would leave that year's
#: universe badly under-counted and its survivorship rate wrong. Observed on
#: the first run: 2019 QTR1 timed out and returned 0 filings.
_MAX_ATTEMPTS = 4


def _annual_filings_in_quarter(
    client: SecEdgarClient, year: int, quarter: int
) -> list[dict[str, Any]]:
    """Every annual-report filing EDGAR received in one quarter.

    `cache_path=None` on purpose: the raw index is ~50 MB and is wanted only
    for the handful of columns below, so it is parsed and dropped rather than
    written to `data/raw/`.

    Raises after `_MAX_ATTEMPTS` rather than returning an empty quarter: an
    incomplete universe would silently corrupt the survivorship measurement
    this whole script exists to produce, so failing loudly is the safe
    behaviour.
    """
    url = _INDEX_URL.format(year=year, quarter=quarter)
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            raw = client._get(url, None)  # noqa: SLF001 - deliberate: no caching wanted
            break
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            logger.warning("%s attempt %d/%d failed (%s)", url, attempt, _MAX_ATTEMPTS, exc)
    else:
        raise RuntimeError(
            f"{url} could not be fetched in {_MAX_ATTEMPTS} attempts; the point-in-time "
            f"universe would be incomplete for {year} QTR{quarter}."
        ) from last_error

    rows: list[dict[str, Any]] = []
    # Fixed-width, latin-1, with a header block terminated by a dashed rule.
    for line in raw.decode("latin-1").splitlines():
        form = line[:12].strip()
        if form not in ANNUAL_FORMS:
            continue
        cik_text = line[74:86].strip()
        filed = line[86:98].strip()
        if not cik_text.isdigit() or not filed:
            continue
        rows.append(
            {
                "cik": int(cik_text),
                "form": form,
                "filed": filed,
                "company": line[12:74].strip(),
            }
        )
    return rows


def _brd_ciks() -> set[int]:
    ciks: set[int] = set()
    with BRD_CASES.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            for column in ("CikBefore", "CikEmerging"):
                raw = (row.get(column) or "").strip()
                if raw.isdigit() and int(raw) > 0:
                    ciks.add(int(raw))
    return ciks


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # The default 10s SEC timeout is sized for JSON API responses; a 50 MB
    # index needs longer, and the first run lost 2019 QTR1 to exactly this.
    # Set through the existing settings mechanism rather than by poking at
    # the client, so the client keeps one source of truth for its config.
    os.environ.setdefault("SEC_REQUEST_TIMEOUT_SECONDS", "120")
    get_settings.cache_clear()
    client = SecEdgarClient()

    filings: list[dict[str, Any]] = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        for quarter in (1, 2, 3, 4):
            quarter_rows = _annual_filings_in_quarter(client, year, quarter)
            filings.extend(quarter_rows)
            logger.info("%d QTR%d: %d annual filings", year, quarter, len(quarter_rows))

    with PIT_FILERS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cik", "form", "filed", "company"])
        writer.writeheader()
        writer.writerows(filings)

    by_year: dict[int, set[int]] = {}
    for row in filings:
        by_year.setdefault(int(row["filed"][:4]), set()).add(int(row["cik"]))

    # The survivorship gap, measured rather than asserted: how much of each
    # year's real filer population is absent from today's ticker file?
    tickers = client.company_tickers()
    current_ciks = {int(entry["cik_str"]) for entry in tickers.values()}
    brd = _brd_ciks()

    corpus_ciks: set[int] = set()
    if CORPUS_MANIFEST.exists():
        manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
        corpus_ciks = {int(record["cik"]) for record in manifest["companies"]}

    per_year: list[dict[str, Any]] = []
    for year in sorted(by_year):
        filers = by_year[year]
        survivors = filers & current_ciks
        per_year.append(
            {
                "year": year,
                "annual_filers": len(filers),
                "still_in_current_ticker_file": len(survivors),
                "survivorship_rate": round(len(survivors) / len(filers), 4),
                "vanished_from_ticker_file": len(filers - current_ciks),
                "ever_brd": len(filers & brd),
            }
        )

    all_filers = set().union(*by_year.values()) if by_year else set()
    summary = {
        "years": [FIRST_YEAR, LAST_YEAR],
        "annual_filings_indexed": len(filings),
        "distinct_filers": len(all_filers),
        "distinct_filers_in_current_ticker_file": len(all_filers & current_ciks),
        "distinct_filers_absent_from_ticker_file": len(all_filers - current_ciks),
        "overall_survivorship_rate": (
            round(len(all_filers & current_ciks) / len(all_filers), 4) if all_filers else None
        ),
        "ever_brd_among_filers": len(all_filers & brd),
        "phase8_corpus_companies": len(corpus_ciks),
        "phase8_corpus_inside_pit_universe": len(corpus_ciks & all_filers),
        "per_year": per_year,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("PIT universe summary:\n%s", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
