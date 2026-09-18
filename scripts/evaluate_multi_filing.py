"""M-4: the multi-filing, point-in-time path measured on the real corpus.

The Phase 1-7 architecture audit found that `CompanyFinancials.as_of()` --
the multi-filing path the monitoring product (D-001) and the as-filed rule
(D-008) both depend on -- was implemented and unit-tested but never exercised
against real data. Every published QM number came from a single accession.
This script is the measurement that closes that gap, and it is also Phase 8's
prerequisite B.

It reports three things:

1. **Filing resolution.** How many of each company's annual filings resolve,
   and precisely why the rest do not (`financials.history` diagnostics).
2. **Coverage, single-filing vs multi-filing.** Ratio slots calculated, trend
   conclusiveness and dimension coverage, computed both ways on the same
   companies so the comparison is like-for-like.
3. **Restatements.** Every (concept, period) where a later filing disagreed
   with an earlier one, classified by *cause* using the provenance the
   canonical facts already carry -- not counted and left as a number.

    uv run python scripts/evaluate_multi_filing.py
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.financials.company import Restatement
from credit_risk_copilot.financials.history import resolve_company_history
from credit_risk_copilot.financials.models import CanonicalFact
from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.health import analyze_financial_health
from credit_risk_copilot.health.models import DimensionStatus, TrendDirection
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.ratios import RATIO_DEFINITIONS, ratios_for_filing
from credit_risk_copilot.ratios.engine import ratios_from_facts
from credit_risk_copilot.ratios.models import RatioStatus
from credit_risk_copilot.sec_edgar import SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
GOLDEN_DIR = Path("data/processed/golden_set")
MANIFEST = GOLDEN_DIR / "manifest.json"
OUT_DIR = Path("data/processed/phase8")

CONCLUSIVE = {
    TrendDirection.INCREASING.value,
    TrendDirection.DECREASING.value,
    TrendDirection.STABLE.value,
}

#: Below this relative difference a "restatement" is a rounding or
#: presentation artefact, not a changed number. Matches the 0.1% synonym
#: tolerance `resolver._values_agree` already uses, so the two modules draw
#: the same line.
IMMATERIAL_RELATIVE_DIFFERENCE = 0.001


def _company_facts(cik: int) -> dict[str, Any]:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    facts: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return facts


def _classify_restatement(entry: Restatement) -> dict[str, Any]:
    """Why did two filings report the same (concept, period) differently?

    The taxonomy is driven by what the canonical facts already record, so
    every classification is checkable rather than asserted:

    - `immaterial` -- the values agree within rounding.
    - `amendment` -- the later filing is a 10-K/A, i.e. a correction to the
      original rather than a fresh annual report.
    - `origin_change` -- one side was REPORTED and the other DERIVED. The
      filer did not necessarily change anything; a later filing simply tagged
      a concept the earlier one made us derive (or stopped tagging it).
    - `tag_change` -- both REPORTED, but from different XBRL tags. The filer
      re-presented the line under a different concept, which is a real
      reporting change but not necessarily a restated *number*.
    - `same_tag_restatement` -- same tag, materially different value. This is
      a genuine restatement by the filer, and the only category that means
      what "restatement" ordinarily means.
    """
    original, restated = entry.original, entry.restated[0]
    original_value = original.value or 0.0
    restated_value = restated.value or 0.0
    denominator = max(abs(original_value), abs(restated_value), 1.0)
    relative = abs(restated_value - original_value) / denominator

    def tag_of(fact: CanonicalFact) -> str | None:
        return fact.provenance[0].concept if fact.provenance else None

    def form_of(fact: CanonicalFact) -> str:
        return (fact.provenance[0].form or "") if fact.provenance else ""

    if relative <= IMMATERIAL_RELATIVE_DIFFERENCE:
        category = "immaterial"
    elif form_of(restated).endswith("/A") or form_of(original).endswith("/A"):
        category = "amendment"
    elif original.origin is not restated.origin:
        category = "origin_change"
    elif tag_of(original) != tag_of(restated):
        category = "tag_change"
    else:
        category = "same_tag_restatement"

    return {
        "concept": entry.concept,
        "period_label": entry.period_label,
        "category": category,
        "original_value": original.value,
        "restated_value": restated.value,
        "relative_difference": relative,
        "original_origin": original.origin.value,
        "restated_origin": restated.origin.value,
        "original_tag": tag_of(original),
        "restated_tag": tag_of(restated),
        "original_accession": original.provenance[0].accession if original.provenance else None,
        "restated_accession": restated.provenance[0].accession if restated.provenance else None,
        "n_restatements": len(entry.restated),
    }


def _coverage(ratio_history: dict[str, tuple[Any, ...]]) -> tuple[int, int]:
    slots = calculated = 0
    for results in ratio_history.values():
        for result in results:
            slots += 1
            if result.status is RatioStatus.CALCULATED:
                calculated += 1
    return slots, calculated


def _trend_stats(report: Any) -> tuple[int, int, int]:
    total = conclusive = insufficient_dims = 0
    for dimension in report.dimensions.values():
        if dimension.status is DimensionStatus.INSUFFICIENT_DATA:
            insufficient_dims += 1
        for trend in dimension.ratio_trends:
            total += 1
            if trend.direction.value in CONCLUSIVE:
                conclusive += 1
    return total, conclusive, insufficient_dims


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        raise FileNotFoundError(f"{MANIFEST} is missing. Run scripts/build_golden_set.py first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    client = SecEdgarClient()

    rows: list[dict[str, Any]] = []
    skip_rows: list[dict[str, Any]] = []
    restatement_rows: list[dict[str, Any]] = []

    for entry in manifest["entries"]:
        cik, company = entry["cik"], entry["company"]
        cutoff = date.fromisoformat(entry["filed"])
        company_facts = _company_facts(cik)

        single = resolve_filing(
            company_facts,
            cik=cik,
            company=company,
            accession=entry["accession"],
            form=entry["form"],
            filed=entry["filed"],
            period_end=entry["period"],
        )
        single_history = ratios_for_filing(single)
        single_report = analyze_financial_health(company, single_history)
        single_slots, single_calculated = _coverage(single_history)
        single_total, single_conclusive, single_insufficient = _trend_stats(single_report)

        history = resolve_company_history(
            company_facts,
            client.annual_filings(cik),
            cik=cik,
            company=company,
            filed_on_or_before=entry["filed"],
        )
        facts = history.financials.as_of(cutoff)
        periods = sorted({period for _, period in facts})
        multi_history = ratios_from_facts(facts, periods)
        multi_report = analyze_financial_health(company, multi_history)
        multi_slots, multi_calculated = _coverage(multi_history)
        multi_total, multi_conclusive, multi_insufficient = _trend_stats(multi_report)

        for skipped in history.skipped:
            skip_rows.append({"company": company, "cik": cik, **skipped.model_dump(mode="json")})

        restatements = history.financials.restatements()
        for restatement in restatements:
            restatement_rows.append(
                {"company": company, "cik": cik, **_classify_restatement(restatement)}
            )

        rows.append(
            {
                "company": company,
                "cik": cik,
                "cutoff": entry["filed"],
                "filings_resolved": history.resolved_count,
                "filings_skipped": history.skipped_count,
                "single_periods": len(single.period_labels),
                "multi_periods": len(periods),
                "single_ratio_slots": single_slots,
                "single_ratio_calculated": single_calculated,
                "multi_ratio_slots": multi_slots,
                "multi_ratio_calculated": multi_calculated,
                "single_trend_conclusive": single_conclusive,
                "single_trend_slots": single_total,
                "multi_trend_conclusive": multi_conclusive,
                "multi_trend_slots": multi_total,
                "single_insufficient_dimensions": single_insufficient,
                "multi_insufficient_dimensions": multi_insufficient,
                "single_signals": len(single_report.signals),
                "multi_signals": len(multi_report.signals),
                "restatements": len(restatements),
            }
        )
        logger.info(
            "%s: %d filings resolved (%d skipped), periods %d -> %d, ratio coverage "
            "%d/%d -> %d/%d, restatements %d",
            company,
            history.resolved_count,
            history.skipped_count,
            len(single.period_labels),
            len(periods),
            single_calculated,
            single_slots,
            multi_calculated,
            multi_slots,
            len(restatements),
        )

    frame = pd.DataFrame(rows)
    frame.to_csv(OUT_DIR / "qm04_multi_filing.csv", index=False)
    pd.DataFrame(skip_rows).to_csv(OUT_DIR / "qm04_skipped_filings.csv", index=False)
    restatement_frame = pd.DataFrame(restatement_rows)
    restatement_frame.to_csv(OUT_DIR / "qm04_restatements.csv", index=False)

    category_counts = (
        Counter(restatement_frame["category"]) if not restatement_frame.empty else Counter()
    )
    skip_counts = Counter(pd.DataFrame(skip_rows)["reason_code"]) if skip_rows else Counter()

    summary = {
        "companies": len(rows),
        "analysis_window": single_report.analysis_window,
        "filings_resolved": int(frame["filings_resolved"].sum()),
        "filings_skipped": int(frame["filings_skipped"].sum()),
        "skip_reasons": dict(sorted(skip_counts.items())),
        "single_filing": {
            "ratio_slots": int(frame["single_ratio_slots"].sum()),
            "ratio_calculated": int(frame["single_ratio_calculated"].sum()),
            "ratio_calculated_rate": round(
                frame["single_ratio_calculated"].sum() / frame["single_ratio_slots"].sum(), 4
            ),
            "trend_conclusive": int(frame["single_trend_conclusive"].sum()),
            "trend_slots": int(frame["single_trend_slots"].sum()),
            "conclusive_direction_rate": round(
                frame["single_trend_conclusive"].sum() / frame["single_trend_slots"].sum(), 4
            ),
            "insufficient_dimensions": int(frame["single_insufficient_dimensions"].sum()),
            "signals": int(frame["single_signals"].sum()),
        },
        "multi_filing": {
            "ratio_slots": int(frame["multi_ratio_slots"].sum()),
            "ratio_calculated": int(frame["multi_ratio_calculated"].sum()),
            "ratio_calculated_rate": round(
                frame["multi_ratio_calculated"].sum() / frame["multi_ratio_slots"].sum(), 4
            ),
            "trend_conclusive": int(frame["multi_trend_conclusive"].sum()),
            "trend_slots": int(frame["multi_trend_slots"].sum()),
            "conclusive_direction_rate": round(
                frame["multi_trend_conclusive"].sum() / frame["multi_trend_slots"].sum(), 4
            ),
            "insufficient_dimensions": int(frame["multi_insufficient_dimensions"].sum()),
            "signals": int(frame["multi_signals"].sum()),
        },
        "restatements": {
            "total": len(restatement_rows),
            "by_category": dict(sorted(category_counts.items())),
        },
    }
    (OUT_DIR / "qm04_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("M-4 summary: %s", json.dumps(summary, indent=2, default=str))
    logger.info("Ratio catalog size: %d", len(RATIO_DEFINITIONS))


if __name__ == "__main__":
    main()
