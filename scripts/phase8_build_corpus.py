"""Phase 8 step 1: assemble the modelling corpus (companies, not features).

Two cohorts, both cached to `data/raw/` so every later step runs offline:

- **Event cohort** — every BRD case whose CIK resolved against SEC
  `companyfacts` in the Phase 3 audit (`status == "ok"`). Their companyfacts
  are already cached from Phase 3; this script adds their `submissions`
  indexes, which are what supply each filing's authoritative `reportDate`.
- **Comparison cohort** — a seeded random sample of the candidate negative
  universe (SEC filers with a ticker, minus every CIK that ever appears in
  BRD), filtered by the same scope rules the product applies everywhere else.

## Scope filtering happens before the expensive fetch

`submissions` is a few hundred KB; `companyfacts` averages ~1.6 MB and runs to
4.5 MB for a long-lived filer. So every company is screened on its cheap
`submissions` payload first -- SIC exclusion (D-006) and a minimum 10-K count
-- and only survivors have their facts downloaded. On a 900-company draw that
is the difference between ~1.5 GB and ~4 GB.

## The SIC filter applies to both cohorts

D-006 excludes banks, insurers, broker-dealers, REITs and investment vehicles
because standard corporate ratios are misleading for them. Applying that to the
comparison cohort but not the event cohort would train the model to recognise
"is a bank" as a bankruptcy feature -- financial-sector failures are heavily
represented in 2008-2010 BRD cases.

    uv run python scripts/phase8_build_corpus.py
"""

from __future__ import annotations

import csv
import json
import logging
import random
from pathlib import Path
from typing import Any

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.sec_edgar import ANNUAL_FORMS, SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
LINKAGE_AUDIT = PROCESSED_DIR / "brd_sec_linkage_audit.csv"
BRD_CASES = RAW_DIR / "brd" / "cases.csv"
OUT_DIR = PROCESSED_DIR / "phase8"
MANIFEST = OUT_DIR / "corpus_manifest.json"

#: Deterministic corpus. Changing this re-draws the comparison cohort and
#: invalidates every downstream measurement, so it is a constant, not a flag.
RANDOM_SEED = 20260917

#: How many comparison companies to *draw* before scope filtering. Sized from
#: the statistics, not from ambition: ~180 usable events at roughly 8 usable
#: company-years each gives a few hundred positive rows, and 10-20 negative
#: rows per positive is where added negatives stop buying precision on the
#: minority class. ~900 drawn survives to ~600-700 after SIC and history
#: filtering, which lands in that range.
COMPARISON_DRAW = 900

#: D-006: SIC 6000-6999 is Finance, Insurance and Real Estate -- banks,
#: thrifts, insurers, broker-dealers, REITs, blank-check/shell vehicles
#: (6770) and investment offices all sit inside it.
EXCLUDED_SIC_RANGE = (6000, 6999)

#: A company needs enough annual filings to produce a point-in-time row with
#: any history behind it at all. Two is the floor: one filing to predict from
#: and one earlier one to have a prior period.
MIN_ANNUAL_FILINGS = 2


def _brd_ciks() -> set[int]:
    """Every CIK that appears anywhere in BRD, in either the `CikBefore` or
    `CikEmerging` column. Used to *exclude* from the comparison cohort -- a
    company that went bankrupt outside our audited window is not a clean
    negative, and one that emerged and re-filed is certainly not."""
    ciks: set[int] = set()
    with BRD_CASES.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            for column in ("CikBefore", "CikEmerging"):
                raw = (row.get(column) or "").strip()
                if raw.isdigit() and int(raw) > 0:
                    ciks.add(int(raw))
    return ciks


def _event_ciks() -> set[int]:
    """CIKs from the Phase 3 linkage audit that SEC actually served facts for."""
    with LINKAGE_AUDIT.open(encoding="utf-8", newline="") as handle:
        return {
            int(row["CikBefore"])
            for row in csv.DictReader(handle)
            if row["status"] == "ok" and (row.get("CikBefore") or "").strip().isdigit()
        }


def _ticker_ciks(client: SecEdgarClient) -> list[int]:
    tickers: dict[str, Any] = client.company_tickers()
    return sorted({int(entry["cik_str"]) for entry in tickers.values()})


def _screen(client: SecEdgarClient, cik: int, cohort: str) -> dict[str, Any] | None:
    """Fetch the cheap `submissions` payload and apply the scope rules.

    Returns the company's screening record, or `None` when the company is out
    of scope or unreachable. Every rejection is logged with its reason so the
    manifest can report the funnel rather than only the survivors.
    """
    try:
        submissions = client.submissions(cik)
    except Exception as exc:  # noqa: BLE001 - one unreachable filer must not stop the build
        logger.warning("CIK%010d: submissions unavailable (%s)", cik, exc)
        return None

    sic_raw = (submissions.get("sic") or "").strip()
    sic = int(sic_raw) if sic_raw.isdigit() else None
    if sic is not None and EXCLUDED_SIC_RANGE[0] <= sic <= EXCLUDED_SIC_RANGE[1]:
        return {"cik": cik, "cohort": cohort, "sic": sic, "excluded": "financial_sector"}
    if sic is None:
        return {"cik": cik, "cohort": cohort, "sic": None, "excluded": "no_sic_code"}

    annual = _count_annual_filings(client, cik)
    if annual < MIN_ANNUAL_FILINGS:
        return {
            "cik": cik,
            "cohort": cohort,
            "sic": sic,
            "annual_filings": annual,
            "excluded": "too_few_annual_filings",
        }

    return {
        "cik": cik,
        "cohort": cohort,
        "company": submissions.get("name", ""),
        "sic": sic,
        "sic_description": submissions.get("sicDescription", ""),
        "fiscal_year_end": submissions.get("fiscalYearEnd", ""),
        "annual_filings": annual,
        "excluded": None,
    }


def _count_annual_filings(client: SecEdgarClient, cik: int) -> int:
    try:
        return sum(1 for ref in client.annual_filings(cik) if ref.form in ANNUAL_FORMS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CIK%010d: filing index unreadable (%s)", cik, exc)
        return 0


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = SecEdgarClient()

    event_ciks = sorted(_event_ciks())
    brd_ciks = _brd_ciks()
    universe = [cik for cik in _ticker_ciks(client) if cik not in brd_ciks]
    logger.info(
        "Universe: %d event CIKs; %d ticker CIKs minus %d ever-BRD -> %d candidate negatives",
        len(event_ciks),
        len(universe) + len(brd_ciks & set(universe)),
        len(brd_ciks),
        len(universe),
    )

    rng = random.Random(RANDOM_SEED)
    comparison_draw = rng.sample(universe, min(COMPARISON_DRAW, len(universe)))

    screened: list[dict[str, Any]] = []
    for index, cik in enumerate(event_ciks, start=1):
        record = _screen(client, cik, "event")
        if record is not None:
            screened.append(record)
        if index % 50 == 0:
            logger.info("Screened %d/%d event companies", index, len(event_ciks))

    for index, cik in enumerate(comparison_draw, start=1):
        record = _screen(client, cik, "comparison")
        if record is not None:
            screened.append(record)
        if index % 100 == 0:
            logger.info("Screened %d/%d comparison companies", index, len(comparison_draw))

    kept = [r for r in screened if r["excluded"] is None]
    logger.info("Screening kept %d of %d companies", len(kept), len(screened))

    for index, record in enumerate(kept, start=1):
        try:
            client.company_facts(record["cik"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("CIK%010d: companyfacts unavailable (%s)", record["cik"], exc)
            record["excluded"] = "no_companyfacts"
        if index % 50 == 0:
            logger.info("Fetched facts for %d/%d companies", index, len(kept))

    final = [r for r in kept if r["excluded"] is None]
    manifest = {
        "generated": "phase8_build_corpus",
        "random_seed": RANDOM_SEED,
        "comparison_draw": COMPARISON_DRAW,
        "excluded_sic_range": list(EXCLUDED_SIC_RANGE),
        "min_annual_filings": MIN_ANNUAL_FILINGS,
        "counts": {
            "event_candidates": len(event_ciks),
            "comparison_candidates_drawn": len(comparison_draw),
            "candidate_negative_universe": len(universe),
            "kept_event": sum(1 for r in final if r["cohort"] == "event"),
            "kept_comparison": sum(1 for r in final if r["cohort"] == "comparison"),
        },
        "exclusions": _exclusion_counts(screened),
        "companies": sorted(final, key=lambda r: r["cik"]),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Corpus manifest: %s", json.dumps(manifest["counts"], indent=2))
    logger.info("Exclusions: %s", json.dumps(manifest["exclusions"], indent=2))


def _exclusion_counts(screened: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for record in screened:
        cohort = counts.setdefault(str(record["cohort"]), {})
        key = str(record["excluded"] or "kept")
        cohort[key] = cohort.get(key, 0) + 1
    return {cohort: dict(sorted(values.items())) for cohort, values in sorted(counts.items())}


if __name__ == "__main__":
    main()
