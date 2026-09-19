"""Phase 17, debt 2: match the negative universe on BRD's eligibility rule.

[D-032](../docs/decision_log.md) ended by naming its own successor. Phase 9
built the point-in-time negative universe Phase 8 had deferred, measured it, and
found it changed nothing -- performance moved less than its confidence interval
and cohort separability *rose*. The cause it identified was not survivorship but
**eligibility**: BRD records only large public bankruptcies, so the event cohort
is large by construction and any comparison cohort drawn from the real filer
population is dominated by companies BRD could never have recorded whatever
happened to them. D-032's closing sentence: the next step is "match the negative
universe on BRD's own eligibility conditions".

**What that rule actually is.** BRD includes a case when the company was
*large* -- total assets of at least **$100 million in 1980 dollars**, and
*public* -- it had filed a 10-K within roughly three years before the petition
([data_feasibility.md §3.3](../docs/data_feasibility.md)).

The second condition is **vacuous on this panel and is not implemented as a
filter**, which is worth stating rather than quietly skipping: every row here
*is* an annual filing, so the counterfactual "had this company filed a petition
on this date, would it have filed a 10-K within the previous three years?" is
true by construction. Only the size condition binds.

**Why this is not Phase 9's size-matching again.** Two differences, and both
matter:

1. **The threshold comes from BRD, not from the event cohort.** Phase 9 kept
   comparison rows inside the event cohort's own 10th-90th percentile band --
   a distribution match, which makes the control group look like the treatment
   group by construction and therefore cannot distinguish "the cohorts differ
   in size" from "the cohorts differ in what made them cohorts".
2. **It is applied symmetrically.** Phase 9 kept every event row. So an event
   row below the band stayed while a comparison row below the band was dropped,
   and the asymmetry that produces the confound survived the correction. Here
   the rule is a *property a row either has or does not have*, so it is applied
   to both cohorts, and an event row that fails it is dropped too. That is what
   "matched on eligibility" has to mean if it is to mean anything.

**The measurement that decides it.** Cohort separability against bankruptcy
ROC-AUC, exactly as D-032 framed it. If the diagnosis is right, the gap between
them should close; if it does not, the confound is not eligibility either, and
that is the result.

    uv run python scripts/phase17_eligibility_matched.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from phase9_size_matched import (  # noqa: E402
    EVENT_SIZE_BAND,
    _load,
    _measure,
)
from phase9_size_matched import (
    OUT_DIR as PHASE9_DIR,
)

from credit_risk_copilot.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

OUT_DIR = Path("data/processed/phase17")

#: BRD's size condition, in its own units: $100M of total assets measured in
#: 1980 dollars (data_feasibility.md §3.3).
BRD_THRESHOLD_1980_USD = 100_000_000.0

#: CPI-U, US city average, annual average, 1982-84 = 100 (BLS series CUUR0000SA0).
#: Hardcoded rather than fetched: it is a dozen published constants that will
#: never change for these years, and a network call here would make a
#: reproducible measurement depend on an outage.
CPI_U: dict[int, float] = {
    1980: 82.408,
    2008: 215.303,
    2009: 214.537,
    2010: 218.056,
    2011: 224.939,
    2012: 229.594,
    2013: 232.957,
    2014: 236.736,
    2015: 237.017,
    2016: 240.007,
    2017: 245.120,
    2018: 251.107,
    2019: 255.657,
    2020: 258.811,
    2021: 270.970,
}


def threshold_for(year: int) -> float:
    """BRD's $100M-in-1980-dollars bar, expressed in `year`'s dollars."""
    known = min(CPI_U, key=lambda y: abs(y - year) if y != 1980 else 10_000)
    if year not in CPI_U:
        logger.warning("No CPI for %d; using %d", year, known)
    return BRD_THRESHOLD_1980_USD * CPI_U[known] / CPI_U[1980]


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    observations, _frame, cohort_of = _load(
        PHASE9_DIR / "observations_pit.csv", PHASE9_DIR / "pit_corpus_manifest.json"
    )
    sizes = np.array([o.features.get("log_total_assets") or np.nan for o in observations])
    is_event = np.array([cohort_of.get(o.key.cik) == "event" for o in observations])
    years = np.array([o.key.prediction_date.year for o in observations])

    thresholds = np.array([np.log(threshold_for(int(y))) for y in years])
    eligible = sizes >= thresholds
    # A row with no resolved total assets cannot be shown to meet the bar, and
    # assuming it does would silently readmit the population the rule exists to
    # exclude. It is dropped and counted.
    unknown_size = np.isnan(sizes)
    eligible = eligible & ~unknown_size

    logger.info(
        "Eligibility bar: $%.0fM (2009) to $%.0fM (2020) of total assets",
        threshold_for(2009) / 1e6,
        threshold_for(2020) / 1e6,
    )
    logger.info(
        "Eligible: %d/%d event rows, %d/%d comparison rows (%d rows have no total assets)",
        int((eligible & is_event).sum()),
        int(is_event.sum()),
        int((eligible & ~is_event).sum()),
        int((~is_event).sum()),
        int(unknown_size.sum()),
    )

    matched = [o for o, keep in zip(observations, eligible, strict=True) if keep]

    # Phase 9's own construction, recomputed here rather than quoted, so all
    # three panels are measured by the same code in the same run.
    low, high = np.nanquantile(sizes[is_event], EVENT_SIZE_BAND)
    size_keep = is_event | ((sizes >= low) & (sizes <= high))
    size_matched = [o for o, keep in zip(observations, size_keep, strict=True) if keep]

    summary: dict[str, Any] = {
        "what_this_measures": (
            "D-032's named next step: restrict the panel to rows that satisfy BRD's own"
            " inclusion rule (>= $100M total assets in 1980 dollars), applied to both cohorts,"
            " and ask whether cohort separability falls towards bankruptcy discrimination."
        ),
        "rule": {
            "brd_threshold_1980_usd": BRD_THRESHOLD_1980_USD,
            "threshold_by_year_usd_millions": {
                str(year): round(threshold_for(year) / 1e6, 1)
                for year in sorted({int(y) for y in years})
            },
            "public_condition": (
                "BRD also requires a 10-K filed within ~3 years before the petition. Every row"
                " in this panel is an annual filing, so the condition is satisfied by"
                " construction and is not implemented as a filter."
            ),
            "rows_dropped_for_unknown_total_assets": int(unknown_size.sum()),
        },
        "retention": {
            "event_rows": {
                "before": int(is_event.sum()),
                "after": int((eligible & is_event).sum()),
            },
            "comparison_rows": {
                "before": int((~is_event).sum()),
                "after": int((eligible & ~is_event).sum()),
            },
            "event_companies_before": len(
                {o.key.cik for o, e in zip(observations, is_event, strict=True) if e}
            ),
            "event_companies_after": len(
                {
                    o.key.cik
                    for o, e, k in zip(observations, is_event, eligible, strict=True)
                    if e and k
                }
            ),
        },
        "size_gap_median_log_assets": {
            "point_in_time": {
                "event": round(float(np.nanmedian(sizes[is_event])), 3),
                "comparison": round(float(np.nanmedian(sizes[~is_event])), 3),
                "gap_multiple": round(
                    float(np.exp(np.nanmedian(sizes[is_event]) - np.nanmedian(sizes[~is_event]))),
                    2,
                ),
            },
            "eligibility_matched": {
                "event": round(float(np.nanmedian(sizes[is_event & eligible])), 3),
                "comparison": round(float(np.nanmedian(sizes[~is_event & eligible])), 3),
                "gap_multiple": round(
                    float(
                        np.exp(
                            np.nanmedian(sizes[is_event & eligible])
                            - np.nanmedian(sizes[~is_event & eligible])
                        )
                    ),
                    2,
                ),
            },
        },
        "unmatched_point_in_time": _measure(observations, cohort_of, "unmatched"),
        "size_matched": _measure(size_matched, cohort_of, "size-matched"),
        "eligibility_matched": _measure(matched, cohort_of, "eligibility-matched"),
    }

    (OUT_DIR / "phase17_eligibility_matched.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Wrote %s", OUT_DIR / "phase17_eligibility_matched.json")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
