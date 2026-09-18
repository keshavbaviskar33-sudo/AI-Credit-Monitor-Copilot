"""Phase 8 step 2: the point-in-time modelling panel.

Turns the corpus from `phase8_build_corpus.py` into leakage-checked
observations: one row per company per annual filing, features from everything
SEC had published on that filing's receipt date, label from BRD's forward
window.

## The two parameters that are measured, not chosen

**Label completeness.** BRD's last release is December 2022, but case entry
lags the petition, so the final release years are thin.
`labels.measure_label_completeness` compares each year's case count against a
normal-conditions reference median and walks back to the last year that does
not look truncated. On this data that is 2020, not 2022 -- so rows whose
forward window reaches past 2020-12-31 are censored rather than scored as
survivals.

**Horizon.** A company stops filing once it fails, so the horizon has to be
long enough to reach the petition from the last 10-K.
`labels.measure_filing_to_event_gap` measures that distance directly. The
primary horizon is 365 days; a 730-day variant is built alongside it as a
robustness check, because the gap distribution shows a 365-day window cannot
reach every event.

    uv run python scripts/phase8_build_dataset.py
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import HorizonPolicy
from credit_risk_copilot.modeling.dataset import (
    as_rows,
    build_company_observations,
    censoring_reasons,
    outcome_counts,
    relabel,
)
from credit_risk_copilot.modeling.labels import (
    EventTable,
    load_event_table,
    measure_filing_to_event_gap,
    measure_label_completeness,
)
from credit_risk_copilot.sec_edgar import SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed/phase8")
CORPUS_MANIFEST = OUT_DIR / "corpus_manifest.json"
BRD_CASES = RAW_DIR / "brd" / "cases.csv"

#: The prediction window, in days. 365 because the product re-assesses a
#: company when it files its next annual report (D-001, D-007), so a
#: one-year-ahead hazard is the question an analyst is actually asking, and
#: consecutive observations then tile the timeline without overlapping --
#: which is what makes the panel a clean discrete-time hazard rather than a
#: set of correlated classification targets. The measured cost is stated
#: rather than hidden: the filing-to-event gap distribution shows a 365-day
#: window cannot reach roughly a fifth of events, whose last annual filing
#: predates the petition by more than a year.
PRIMARY_HORIZON_DAYS = 365

#: Built alongside the primary panel purely as a robustness check on that
#: cost. Longer windows capture nearly every event but make consecutive rows
#: overlap, so one event labels two rows.
ROBUSTNESS_HORIZON_DAYS = 730


def _company_facts(cik: int) -> dict[str, Any] | None:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    if not path.exists():
        return None
    facts: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return facts


def _build(
    companies: list[dict[str, Any]],
    events: EventTable,
    client: SecEdgarClient,
    horizon: HorizonPolicy,
    label: str,
) -> tuple[list[Any], list[Any]]:
    observations: list[Any] = []
    skipped: list[Any] = []
    for index, record in enumerate(companies, start=1):
        cik = int(record["cik"])
        company_facts = _company_facts(cik)
        if company_facts is None:
            continue
        try:
            filings = client.annual_filings(cik)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CIK%010d: filing index unavailable (%s)", cik, exc)
            continue
        company_observations, company_skipped = build_company_observations(
            company_facts=company_facts,
            filings=filings,
            cik=cik,
            company=str(record.get("company") or f"CIK{cik}"),
            events=events,
            horizon=horizon,
        )
        observations.extend(company_observations)
        skipped.extend(company_skipped)
        if index % 50 == 0:
            logger.info(
                "[%s] %d/%d companies -> %d observations",
                label,
                index,
                len(companies),
                len(observations),
            )
    return observations, skipped


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not CORPUS_MANIFEST.exists():
        raise FileNotFoundError(
            f"{CORPUS_MANIFEST} is missing. Run scripts/phase8_build_corpus.py first."
        )
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    companies = manifest["companies"]
    logger.info("Corpus: %d companies", len(companies))

    events = load_event_table(BRD_CASES)
    completeness = measure_label_completeness(events)
    logger.info(
        "Label completeness: last event %s, reference median %.1f cases/yr, last complete year "
        "%d -> label_complete_through %s",
        completeness.last_event_date,
        completeness.reference_median,
        completeness.last_complete_year,
        completeness.label_complete_through,
    )

    client = SecEdgarClient()

    last_filing_before_event: dict[int, date] = {}
    for record in companies:
        cik = int(record["cik"])
        cases = events.cases(cik)
        if not cases:
            continue
        try:
            refs = client.annual_filings(cik)
        except Exception:  # noqa: BLE001
            continue
        prior = [r for r in refs if date.fromisoformat(r.filed) < cases[0].filed]
        if prior:
            last_filing_before_event[cik] = date.fromisoformat(prior[-1].filed)
    gap = measure_filing_to_event_gap(events, last_filing_before_event)
    logger.info("Filing-to-event gap: %s", json.dumps(gap, indent=2))

    summaries: dict[str, Any] = {
        "corpus_companies": len(companies),
        "label_completeness": completeness.model_dump(mode="json"),
        "filing_to_event_gap_days": gap,
        "panels": {},
    }

    primary_horizon = HorizonPolicy(
        horizon_days=PRIMARY_HORIZON_DAYS,
        label_complete_through=completeness.label_complete_through,
    )
    # Features depend only on the information cutoff, so the panel is built
    # once and relabelled for the robustness horizon rather than rebuilt --
    # re-resolving every filing twice would double the slowest step for a
    # result that is identical column for column except the outcome.
    built, skipped = _build(companies, events, client, primary_horizon, "primary")

    for name, horizon_days in (
        ("primary", PRIMARY_HORIZON_DAYS),
        ("robustness", ROBUSTNESS_HORIZON_DAYS),
    ):
        horizon = HorizonPolicy(
            horizon_days=horizon_days,
            label_complete_through=completeness.label_complete_through,
        )
        observations = (
            built if horizon_days == PRIMARY_HORIZON_DAYS else list(relabel(built, events, horizon))
        )
        usable = [obs for obs in observations if obs.outcome.is_usable]

        frame = pd.DataFrame(as_rows(observations))
        frame.to_csv(OUT_DIR / f"observations_{name}.csv", index=False)

        counts = outcome_counts(observations)
        summaries["panels"][name] = {
            "horizon": horizon.describe(),
            "observations_built": len(observations),
            "usable_rows": len(usable),
            "outcome_counts": counts,
            "censoring_reasons": censoring_reasons(observations),
            "event_rate": (round(counts["positive"] / len(usable), 5) if usable else None),
            "companies_with_rows": int(frame["cik"].nunique()) if not frame.empty else 0,
            "companies_with_events": (
                int(frame.loc[frame["label"] == 1, "cik"].nunique()) if not frame.empty else 0
            ),
            "prediction_date_range": (
                [frame["prediction_date"].min(), frame["prediction_date"].max()]
                if not frame.empty
                else None
            ),
            "skipped_observations": len(skipped),
            "skip_reasons": _counts(skipped),
        }
        logger.info(
            "[%s] %d observations, %d usable (%d positive / %d negative), %d censored",
            name,
            len(observations),
            len(usable),
            counts["positive"],
            counts["negative"],
            counts["censored"],
        )

    (OUT_DIR / "dataset_summary.json").write_text(
        json.dumps(summaries, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Dataset summary: %s", json.dumps(summaries["panels"], indent=2, default=str))


def _counts(skipped: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in skipped:
        counts[entry.reason_code] = counts.get(entry.reason_code, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    main()
