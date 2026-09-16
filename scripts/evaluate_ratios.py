"""Real-corpus evaluation for Phase 6 (§24, §25): does the ratio engine
actually calculate on real filings, and where does it not?

Reuses Phase 5's resolution entirely from cache -- no SEC requests, no
re-extraction (same convention as `evaluate_canonicalization.py`):

    companyfacts (cached) -> resolver.resolve_filing -> CanonicalFilingFacts
                                                        -> ratios.ratios_for_filing
                                                        -> RatioResult per (ratio, period)

Produces a coverage matrix -- calculated/missing/invalid/conflicting per
ratio, across every annual period in the 12-filing golden set -- so the
canonical schema's actual sufficiency for Phase 6 is measured, not assumed.

    uv run python scripts/evaluate_ratios.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.ratios import RATIO_DEFINITIONS, ratios_for_filing
from credit_risk_copilot.ratios.models import RatioStatus

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
GOLDEN_DIR = Path("data/processed/golden_set")
MANIFEST = GOLDEN_DIR / "manifest.json"
OUT_DIR = GOLDEN_DIR


def _company_facts(cik: int) -> dict[str, Any]:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    facts: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return facts


def main() -> None:
    configure_logging()
    if not MANIFEST.exists():
        raise FileNotFoundError(f"{MANIFEST} is missing. Run scripts/build_golden_set.py first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    status_counts: dict[str, dict[str, int]] = {
        d.ratio_id: dict.fromkeys((s.value for s in RatioStatus), 0) for d in RATIO_DEFINITIONS
    }
    warning_counts: dict[str, int] = dict.fromkeys((d.ratio_id for d in RATIO_DEFINITIONS), 0)

    for entry in manifest["entries"]:
        company_facts = _company_facts(entry["cik"])
        filing = resolve_filing(
            company_facts,
            cik=entry["cik"],
            company=entry["company"],
            accession=entry["accession"],
            form=entry["form"],
            filed=entry["filed"],
            period_end=entry["period"],
        )
        history = ratios_for_filing(filing)
        for ratio_id, results in history.items():
            for result in results:
                status_counts[ratio_id][result.status.value] += 1
                if result.warnings:
                    warning_counts[ratio_id] += 1
                rows.append(
                    {
                        "company": entry["company"],
                        "accession": entry["accession"],
                        "ratio_id": ratio_id,
                        "period_label": result.period_label,
                        "value": result.value,
                        "status": result.status.value,
                        "warning_count": len(result.warnings),
                        "reason": result.reason,
                    }
                )

    detail = pd.DataFrame(rows)
    detail.to_csv(OUT_DIR / "qm02_ratio_results.csv", index=False)

    coverage_rows: list[dict[str, Any]] = []
    for definition in RATIO_DEFINITIONS:
        counts = status_counts[definition.ratio_id]
        total = sum(counts.values())
        calculated = counts[RatioStatus.CALCULATED.value]
        coverage_rows.append(
            {
                "ratio_id": definition.ratio_id,
                "category": definition.category,
                "required_inputs": len(definition.inputs),
                "total_periods": total,
                "calculated": calculated,
                "missing_input": counts[RatioStatus.MISSING_INPUT.value],
                "invalid_denominator": counts[RatioStatus.INVALID_DENOMINATOR.value],
                "conflicting_input": counts[RatioStatus.CONFLICTING_INPUT.value],
                "with_warnings": warning_counts[definition.ratio_id],
                "coverage": round(calculated / total, 3) if total else None,
            }
        )
    coverage = pd.DataFrame(coverage_rows)
    coverage.to_csv(OUT_DIR / "qm02_coverage_matrix.csv", index=False)
    logger.info("Ratio coverage matrix:\n%s", coverage.to_string(index=False))

    summary = {
        "filings": len(manifest["entries"]),
        "ratio_period_slots": len(detail),
        "overall_calculated_rate": round(float((detail["status"] == "calculated").mean()), 4)
        if not detail.empty
        else None,
        "slots_with_warnings": int((detail["warning_count"] > 0).sum()) if not detail.empty else 0,
    }
    (OUT_DIR / "qm02_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("QM-02 summary: %s", summary)


if __name__ == "__main__":
    main()
