"""Phase 9 step 2: a comparison cohort sampled point-in-time, not survivor-first.

`phase9_pit_universe.py` measured the gap Phase 8 could only name: of the
16,008 companies that filed an annual report between 2009 and 2020, **3,625
(22.6%) appear in SEC's current ticker file**. Phase 8's comparison cohort was
drawn from that 22.6%. Everything in the pooled evaluation therefore compared
companies that failed against companies selected for having survived a decade.

This script draws the comparison cohort from the real population instead:
companies that had actually filed an annual report in the years the panel
covers, whether or not they still exist. The event cohort is untouched, so the
two panels differ in exactly one respect and the difference is attributable.

## What this fixes, and what it cannot

It removes **survivorship selection**. It does not remove **label noise**, and
it makes that noise worse in a direction worth stating plainly: BRD records
only large public bankruptcies, so a small filer that failed quietly, was
liquidated, or delisted for cause enters this cohort labelled `0`. Phase 8's
survivor cohort had almost no such companies by construction.

That gives a genuine bracket rather than a single number:

    survivor-only comparison  ->  optimistic bound (no failures hidden in the negatives)
    point-in-time comparison  ->  pessimistic bound (some real failures labelled 0)

Both are reported. Neither is the truth on its own, and quoting either alone
would misrepresent what the data supports.

## Screening matches Phase 8 exactly

Same SIC exclusion (D-006), same minimum annual-filing count, same screen-then-
fetch order. Any difference in the result has to come from the sampling frame,
which is the whole point.

    uv run python scripts/phase9_pit_corpus.py
"""

from __future__ import annotations

import csv
import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.sec_edgar import ANNUAL_FORMS, SecEdgarClient

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
OUT_DIR = Path("data/processed/phase9")
PIT_FILERS = OUT_DIR / "pit_filers.csv"
PHASE8_MANIFEST = PHASE8_DIR / "corpus_manifest.json"
BRD_CASES = Path("data/raw/brd/cases.csv")
MANIFEST = OUT_DIR / "pit_corpus_manifest.json"

#: Same seed family as Phase 8, so the two corpora are reproducible together.
RANDOM_SEED = 20260918

#: Drawn before screening. Phase 8 kept 426 of 900 drawn (47%); the
#: point-in-time frame contains more small and short-lived filers, so a larger
#: draw is needed to land a comparison cohort of comparable size.
COMPARISON_DRAW = 1600

#: D-006, unchanged from Phase 8.
EXCLUDED_SIC_RANGE = (6000, 6999)
MIN_ANNUAL_FILINGS = 2

#: A company must have filed an annual report in at least this many distinct
#: years inside the panel's window to enter the frame. One filing yields no
#: prior period and so no observation; this screens that out before spending a
#: request on it, and matches `MIN_ANNUAL_FILINGS` in spirit.
MIN_PIT_YEARS = 2


def _brd_ciks() -> set[int]:
    ciks: set[int] = set()
    with BRD_CASES.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            for column in ("CikBefore", "CikEmerging"):
                raw = (row.get(column) or "").strip()
                if raw.isdigit() and int(raw) > 0:
                    ciks.add(int(raw))
    return ciks


def _pit_frame() -> dict[int, set[int]]:
    """CIK -> the set of years it filed an annual report."""
    years_by_cik: dict[int, set[int]] = defaultdict(set)
    with PIT_FILERS.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            years_by_cik[int(row["cik"])].add(int(row["filed"][:4]))
    return dict(years_by_cik)


def _screen(client: SecEdgarClient, cik: int) -> dict[str, Any] | None:
    """Phase 8's screen, verbatim: cheap `submissions` first, facts later."""
    try:
        submissions = client.submissions(cik)
    except Exception as exc:  # noqa: BLE001 - one unreachable filer must not stop the build
        logger.debug("CIK%010d: submissions unavailable (%s)", cik, exc)
        return {"cik": cik, "cohort": "comparison_pit", "excluded": "submissions_unavailable"}

    sic_raw = (submissions.get("sic") or "").strip()
    sic = int(sic_raw) if sic_raw.isdigit() else None
    if sic is None:
        return {"cik": cik, "cohort": "comparison_pit", "sic": None, "excluded": "no_sic_code"}
    if EXCLUDED_SIC_RANGE[0] <= sic <= EXCLUDED_SIC_RANGE[1]:
        return {"cik": cik, "cohort": "comparison_pit", "sic": sic, "excluded": "financial_sector"}

    try:
        annual = sum(1 for ref in client.annual_filings(cik) if ref.form in ANNUAL_FORMS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("CIK%010d: filing index unreadable (%s)", cik, exc)
        annual = 0
    if annual < MIN_ANNUAL_FILINGS:
        return {
            "cik": cik,
            "cohort": "comparison_pit",
            "sic": sic,
            "annual_filings": annual,
            "excluded": "too_few_annual_filings",
        }

    return {
        "cik": cik,
        "cohort": "comparison_pit",
        "company": submissions.get("name", ""),
        "sic": sic,
        "sic_description": submissions.get("sicDescription", ""),
        "fiscal_year_end": submissions.get("fiscalYearEnd", ""),
        "annual_filings": annual,
        "excluded": None,
    }


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = SecEdgarClient()

    phase8 = json.loads(PHASE8_MANIFEST.read_text(encoding="utf-8"))
    event_companies = [r for r in phase8["companies"] if r["cohort"] == "event"]
    phase8_comparison = {int(r["cik"]) for r in phase8["companies"] if r["cohort"] == "comparison"}
    logger.info(
        "Phase 8 corpus: %d event companies (carried over unchanged), %d survivor-sampled "
        "comparison companies (replaced)",
        len(event_companies),
        len(phase8_comparison),
    )

    brd = _brd_ciks()
    frame_years = _pit_frame()
    tickers = client.company_tickers()
    current_ciks = {int(entry["cik_str"]) for entry in tickers.values()}

    # The sampling frame: every company that actually filed annual reports in
    # at least two of the panel's years and never appears in BRD. Membership
    # of today's ticker file is *not* a criterion -- that is the change.
    frame = sorted(
        cik for cik, years in frame_years.items() if len(years) >= MIN_PIT_YEARS and cik not in brd
    )
    logger.info(
        "Point-in-time frame: %d companies (%d in the current ticker file, %d vanished from it)",
        len(frame),
        len(set(frame) & current_ciks),
        len(set(frame) - current_ciks),
    )

    rng = random.Random(RANDOM_SEED)
    drawn = rng.sample(frame, min(COMPARISON_DRAW, len(frame)))

    screened: list[dict[str, Any]] = []
    for index, cik in enumerate(drawn, start=1):
        record = _screen(client, cik)
        if record is not None:
            screened.append(record)
        if index % 100 == 0:
            kept = sum(1 for r in screened if r["excluded"] is None)
            logger.info("Screened %d/%d, kept %d", index, len(drawn), kept)

    kept = [r for r in screened if r["excluded"] is None]
    logger.info("Screening kept %d of %d drawn", len(kept), len(drawn))

    for index, record in enumerate(kept, start=1):
        try:
            client.company_facts(record["cik"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("CIK%010d: companyfacts unavailable (%s)", record["cik"], exc)
            record["excluded"] = "no_companyfacts"
        if index % 50 == 0:
            logger.info("Fetched facts for %d/%d", index, len(kept))

    final_comparison = [r for r in kept if r["excluded"] is None]
    for record in final_comparison:
        record["survived_to_current_ticker_file"] = int(record["cik"]) in current_ciks

    companies = event_companies + final_comparison
    survivors = sum(1 for r in final_comparison if r["survived_to_current_ticker_file"])
    manifest = {
        "generated": "phase9_pit_corpus",
        "random_seed": RANDOM_SEED,
        "comparison_draw": COMPARISON_DRAW,
        "excluded_sic_range": list(EXCLUDED_SIC_RANGE),
        "min_annual_filings": MIN_ANNUAL_FILINGS,
        "min_pit_years": MIN_PIT_YEARS,
        "frame_size": len(frame),
        "counts": {
            "kept_event": len(event_companies),
            "kept_comparison_pit": len(final_comparison),
            "comparison_still_listed_today": survivors,
            "comparison_vanished_from_ticker_file": len(final_comparison) - survivors,
            "phase8_comparison_for_reference": len(phase8_comparison),
            "overlap_with_phase8_comparison": len(
                {int(r["cik"]) for r in final_comparison} & phase8_comparison
            ),
        },
        "exclusions": _exclusion_counts(screened),
        "companies": sorted(companies, key=lambda r: int(r["cik"])),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("PIT corpus counts: %s", json.dumps(manifest["counts"], indent=2))
    logger.info("Exclusions: %s", json.dumps(manifest["exclusions"], indent=2))


def _exclusion_counts(screened: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in screened:
        key = str(record["excluded"] or "kept")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    main()
