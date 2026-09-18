"""M-3 for Phase 7: does the financial-health engine produce meaningful,
non-fabricated trends/signals on the real 12-filing golden set -- and how
often does it (correctly) decline to, given Phase 6's own measured
comparative-year coverage gaps (`ratios.md` §6: 48.2% overall, 35-71% per
ratio)?

Reuses Phase 5/6 entirely from cache -- no SEC requests, no re-extraction,
no re-computation of anything Phase 6 already measured (§37):

    companyfacts (cached) -> resolver.resolve_filing -> CanonicalFilingFacts
                                                        -> ratios.ratios_for_filing
                                                        -> health.analyze_financial_health
                                                        -> FinancialHealthReport per filing

Deliberately does *not* report a single "accuracy" number -- there is no
ground truth for "is this trend correct" the way QM-01 had XBRL reference
values. Instead this measures what the phase brief's own diagnostics ask
for (§37): how much history each ratio actually had to work with, how often
a conclusive direction was reachable at all, and which signals fired.

    uv run python scripts/evaluate_financial_health.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.health import analyze_financial_health
from credit_risk_copilot.health.models import HistoryDepth, TrendDirection
from credit_risk_copilot.health.thresholds import DEFAULT_ANALYSIS_WINDOW
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.ratios import RATIO_DEFINITIONS, ratios_for_filing

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
GOLDEN_DIR = Path("data/processed/golden_set")
MANIFEST = GOLDEN_DIR / "manifest.json"
OUT_DIR = GOLDEN_DIR

#: Passed explicitly rather than left to the engine's default (D-024). A
#: published measurement should state the window it was taken over: the same
#: corpus scored under a different window is a different number, and a QM
#: figure whose window can drift with a library default is not reproducible.
#: This tracks `DEFAULT_ANALYSIS_WINDOW` deliberately, so the headline M-3
#: figure describes the engine's out-of-the-box behaviour.
ANALYSIS_WINDOW = DEFAULT_ANALYSIS_WINDOW


def _company_facts(cik: int) -> dict[str, Any]:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    facts: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return facts


def main() -> None:
    configure_logging()
    if not MANIFEST.exists():
        raise FileNotFoundError(f"{MANIFEST} is missing. Run scripts/build_golden_set.py first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    trend_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    dimension_rows: list[dict[str, Any]] = []

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
        ratio_history = ratios_for_filing(filing)
        health = analyze_financial_health(
            entry["company"], ratio_history, analysis_window=ANALYSIS_WINDOW
        )

        for dimension in health.dimensions.values():
            dimension_rows.append(
                {
                    "company": entry["company"],
                    "dimension": dimension.dimension,
                    "status": dimension.status.value,
                    "ratio_count": len(dimension.ratio_trends),
                    "signal_count": len(dimension.signals),
                }
            )
            for trend in dimension.ratio_trends:
                trend_rows.append(
                    {
                        "company": entry["company"],
                        "ratio_id": trend.ratio_id,
                        "periods_available": trend.periods_available,
                        "history_depth": trend.history_depth.value,
                        "has_gap": trend.has_gap,
                        "direction": trend.direction.value,
                        "economic_direction": trend.economic_direction.value,
                        "data_quality": trend.data_quality.value,
                        "negative_equity": trend.negative_equity,
                        "unusual_movement": trend.unusual_movement,
                    }
                )

        for signal in health.signals:
            signal_rows.append(
                {
                    "company": entry["company"],
                    "code": signal.code.value,
                    "category": signal.category,
                    "ratio_id": signal.ratio_id,
                    "data_quality": signal.trend.data_quality.value if signal.trend else None,
                }
            )

    trends = pd.DataFrame(trend_rows)
    signals = pd.DataFrame(signal_rows)
    dimensions = pd.DataFrame(dimension_rows)
    trends.to_csv(OUT_DIR / "qm03_ratio_trends.csv", index=False)
    signals.to_csv(OUT_DIR / "qm03_signals.csv", index=False)
    dimensions.to_csv(OUT_DIR / "qm03_dimensions.csv", index=False)

    total_trends = len(trends)
    conclusive_directions = {
        TrendDirection.INCREASING.value,
        TrendDirection.DECREASING.value,
        TrendDirection.STABLE.value,
    }
    conclusive = int(trends["direction"].isin(conclusive_directions).sum()) if total_trends else 0
    insufficient = (
        int((trends["direction"] == TrendDirection.INSUFFICIENT_DATA.value).sum())
        if total_trends
        else 0
    )
    discontinuous = (
        int((trends["direction"] == TrendDirection.DISCONTINUOUS_HISTORY.value).sum())
        if total_trends
        else 0
    )
    not_meaningful = (
        int((trends["direction"] == TrendDirection.NOT_MEANINGFUL.value).sum())
        if total_trends
        else 0
    )
    adequate_history = (
        int((trends["history_depth"] == HistoryDepth.ADEQUATE.value).sum()) if total_trends else 0
    )

    direction_counts = trends["direction"].value_counts().to_dict() if not trends.empty else {}
    signal_counts = signals["code"].value_counts().to_dict() if not signals.empty else {}
    dimension_status_counts = (
        dimensions["status"].value_counts().to_dict() if not dimensions.empty else {}
    )

    summary = {
        "filings": len(manifest["entries"]),
        "analysis_window": ANALYSIS_WINDOW,
        "input_path": "single_filing",
        "ratio_trend_slots": total_trends,
        "expected_ratio_trend_slots": len(manifest["entries"]) * len(RATIO_DEFINITIONS),
        "conclusive_direction_rate": round(conclusive / total_trends, 4) if total_trends else None,
        "insufficient_data_count": insufficient,
        "discontinuous_history_count": discontinuous,
        "not_meaningful_count": not_meaningful,
        "adequate_history_rate": round(adequate_history / total_trends, 4)
        if total_trends
        else None,
        "direction_counts": direction_counts,
        "total_signals": len(signals),
        "signal_counts": signal_counts,
        "dimension_status_counts": dimension_status_counts,
    }
    (OUT_DIR / "qm03_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("M-3 summary: %s", json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
