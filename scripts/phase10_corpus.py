"""Phase 10 step 1: a narrative corpus linked to the bankruptcy outcome.

The golden set (12 filings) is enough to *design* a signal catalog against and
far too small to measure one. This builds a larger corpus where every filing
carries the Phase 8 label, so the question "do these signals actually precede
bankruptcy?" can be answered on out-of-sample filings rather than on the six
distressed filings the patterns were written while looking at.

## What it samples

Rows come from `data/processed/phase8/observations_primary.csv`, which already
carries the point-in-time contract ([D-026](../docs/decision_log.md)) and the
365-day hazard label ([D-025](../docs/decision_log.md)):

- **every** `label == 1` row, capped, because events are the scarce resource;
- a year-matched draw of `label == 0` rows, so the comparison filings come from
  the same filing years as the events. Without matching, the comparison group
  would skew to whichever years have the most filers and any measured
  difference would partly be a difference of era -- filings got longer and
  more heavily lawyered over this period, which is exactly the kind of drift
  that a naive comparison would attribute to distress.

The **filing document** is fetched for each sampled row's own accession, so
the text and the label describe the same filing on the same date. No filing
filed after a row's prediction date is read, which keeps the point-in-time rule
intact for this layer too.

Downloads are cached under `data/raw/filings/` and skipped if present, so
re-running is cheap and a failed run resumes.

    uv run python scripts/phase10_corpus.py --events 120 --comparisons 120
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.sec_edgar import FilingRef, SecEdgarClient

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
OUT_DIR = Path("data/processed/phase10")

#: Fixed so the corpus is reproducible. Same value as Phase 8's, deliberately:
#: these are draws from the same panel and using a different seed would make
#: the two samples look independent when they are not.
RANDOM_SEED = 20260917


def _load_rows() -> pd.DataFrame:
    frame = pd.read_csv(PHASE8_DIR / "observations_primary.csv")
    frame = frame[frame["label"].notna()].copy()
    frame["label"] = frame["label"].astype(int)
    frame["year"] = frame["prediction_date"].str.slice(0, 4).astype(int)
    return frame


def _sample(frame: pd.DataFrame, n_events: int, n_comparisons: int) -> pd.DataFrame:
    """Every event row (capped), plus a year-matched draw of comparison rows."""
    rng = random.Random(RANDOM_SEED)

    events = frame[frame["label"] == 1]
    if len(events) > n_events:
        events = events.sample(n=n_events, random_state=RANDOM_SEED)

    wanted = Counter(events["year"])
    pool: dict[int, list[int]] = defaultdict(list)
    for index, year in frame[frame["label"] == 0]["year"].items():
        pool[int(year)].append(int(index))

    chosen: list[int] = []
    # Proportional to the event years, so the comparison group has the same
    # era profile. Years with too few candidates take what exists and the
    # shortfall is made up from the pooled remainder rather than silently
    # dropped, which would re-introduce the skew this is correcting.
    scale = n_comparisons / max(len(events), 1)
    for year, count in wanted.items():
        candidates = pool.get(year, [])
        rng.shuffle(candidates)
        chosen.extend(candidates[: round(count * scale)])

    if len(chosen) < n_comparisons:
        remainder = [i for indices in pool.values() for i in indices if i not in set(chosen)]
        rng.shuffle(remainder)
        chosen.extend(remainder[: n_comparisons - len(chosen)])

    comparisons = frame.loc[chosen[:n_comparisons]]
    logger.info(
        "sampled %d event rows and %d comparison rows",
        len(events),
        len(comparisons),
    )
    return pd.concat([events, comparisons]).reset_index(drop=True)


def _fetch(client: SecEdgarClient, row: pd.Series) -> dict[str, Any]:
    """Download one row's own filing document, or record why it could not be."""
    cik = int(row["cik"])
    accession = str(row["source_accession"])
    record: dict[str, Any] = {
        "cik": cik,
        "company": row["company"],
        "accession": accession,
        "prediction_date": row["prediction_date"],
        "label": int(row["label"]),
        "cohort": "event" if int(row["label"]) == 1 else "comparison",
        "fiscal_period_label": row["fiscal_period_label"],
        "days_to_event": row.get("days_to_event"),
    }
    try:
        refs = {ref.accession: ref for ref in client.annual_filings(cik)}
    except requests.RequestException as error:
        record["error"] = f"submissions unavailable: {error}"
        return record

    ref: FilingRef | None = refs.get(accession)
    if ref is None:
        record["error"] = "accession not present in the filer's annual-filing index"
        return record

    try:
        content = client.filing_document(ref)
    except requests.RequestException as error:
        record["error"] = f"document unavailable: {error}"
        return record

    record.update(
        {
            "form": ref.form,
            "filed": ref.filed,
            "period": ref.period,
            "primary_document": ref.primary_document,
            "html_path": str(
                Path("data/raw/filings") / ref.accession_compact / ref.primary_document
            ),
            "bytes": len(content),
            "error": None,
        }
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=120)
    parser.add_argument("--comparisons", type=int, default=120)
    args = parser.parse_args()

    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sampled = _sample(_load_rows(), args.events, args.comparisons)
    client = SecEdgarClient()

    records: list[dict[str, Any]] = []
    for position, (_, row) in enumerate(sampled.iterrows(), start=1):
        record = _fetch(client, row)
        records.append(record)
        if position % 20 == 0 or position == len(sampled):
            ok = sum(1 for r in records if not r.get("error"))
            logger.info("fetched %d/%d (%d usable)", position, len(sampled), ok)

    frame = pd.DataFrame(records)
    path = OUT_DIR / "narrative_corpus.csv"
    frame.to_csv(path, index=False)

    usable = frame[frame["error"].isna()]
    summary = {
        "generated": "phase10_corpus",
        "random_seed": RANDOM_SEED,
        "requested": {"events": args.events, "comparisons": args.comparisons},
        "rows": len(frame),
        "usable": len(usable),
        "event_rows": int((usable["label"] == 1).sum()),
        "comparison_rows": int((usable["label"] == 0).sum()),
        "companies": int(usable["cik"].nunique()),
        "megabytes": round(float(usable["bytes"].sum()) / 1e6, 1) if len(usable) else 0.0,
        "errors": frame["error"].dropna().value_counts().to_dict(),
        "year_profile": {
            cohort: frame[frame["cohort"] == cohort]["prediction_date"]
            .str.slice(0, 4)
            .value_counts()
            .sort_index()
            .to_dict()
            for cohort in ("event", "comparison")
        },
    }
    (OUT_DIR / "narrative_corpus_summary.json").write_text(json.dumps(summary, indent=2))
    logger.info("wrote %s (%d usable filings)", path, len(usable))


if __name__ == "__main__":
    main()
