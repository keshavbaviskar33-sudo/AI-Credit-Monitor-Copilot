"""M-4 validation: the three conditions the architecture audit attached to
switching the golden-set evaluation onto the multi-filing path.

`evaluate_multi_filing.py` (M-4) measured *what* the multi-filing path
changes. The audit was explicit that the risk of that change is not to the
code but to the claims, and named three things to check before the new numbers
are trusted ([architecture_audit.md §7, M-4](../docs/architecture_audit.md)):

1. **Re-do the false-positive inspection.** Phase 7's "no false positive across
   12 reports" covered 37 signals from single-filing input. The multi-filing
   path fires far more, and that validation does not transfer.
2. **Triage the restatements.** `qm04_restatements.csv` classifies all 453 by
   cause from canonical-fact provenance. This re-derives a sample straight from
   the raw `companyfacts` JSON, so the classification is checked against the
   source rather than against the thing that produced it.
3. **Confirm pre-phase-in filings degrade gracefully.** A 2009-2011 filing
   often carries a fraction of the tags a modern one does. The question is
   whether such a filing contributes a thin-but-honest period or a
   thin-and-misleading one.

Outputs go to `data/processed/phase8/` as `m4_*.csv` / `m4_validation.json`.

    uv run python scripts/validate_multi_filing.py
"""

from __future__ import annotations

import json
import logging
import random
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import linear_regression, mean
from typing import Any

import pandas as pd

from credit_risk_copilot.financials.history import resolve_company_history
from credit_risk_copilot.health import analyze_financial_health
from credit_risk_copilot.health.models import SignalCode
from credit_risk_copilot.health.thresholds import (
    DEFAULT_ANALYSIS_WINDOW,
    STABLE_MAGNITUDE_THRESHOLD,
)
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.ratios.engine import ratios_from_facts
from credit_risk_copilot.ratios.models import RatioStatus
from credit_risk_copilot.sec_edgar import SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
GOLDEN_DIR = Path("data/processed/golden_set")
MANIFEST = GOLDEN_DIR / "manifest.json"
OUT_DIR = Path("data/processed/phase8")

ANALYSIS_WINDOW = DEFAULT_ANALYSIS_WINDOW

#: How many restatements to re-derive from raw JSON, per category.
RESTATEMENT_SAMPLE_PER_CATEGORY = 8
SAMPLE_SEED = 20260917

#: A trend whose magnitude is within this multiple of the stable/noise floor
#: is flagged for human reading: it cleared the bar, but only just, so it is
#: where a threshold-driven false positive would live if one existed.
MARGINAL_MAGNITUDE_MULTIPLE = 1.5

#: Signals that are statements of fact rather than trend judgements. They
#: cannot be "false positives" in the trend sense -- `NEGATIVE_EQUITY` either
#: appears in the window or it does not -- so they are counted separately
#: rather than inspected as if they involved a threshold.
_FACTUAL_SIGNALS = frozenset({SignalCode.NEGATIVE_EQUITY, SignalCode.UNUSUAL_MOVEMENT})


def _company_facts(cik: int) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json").read_text(encoding="utf-8")
    )
    return payload


def _multi_filing_report(entry: dict[str, Any], client: SecEdgarClient) -> tuple[Any, Any, Any]:
    cik, company = entry["cik"], entry["company"]
    cutoff = date.fromisoformat(entry["filed"])
    company_facts = _company_facts(cik)
    history = resolve_company_history(
        company_facts,
        client.annual_filings(cik),
        cik=cik,
        company=company,
        filed_on_or_before=entry["filed"],
    )
    facts = history.financials.as_of(cutoff)
    periods = sorted({period for _, period in facts})
    ratio_history = ratios_from_facts(facts, periods)
    report = analyze_financial_health(company, ratio_history, analysis_window=ANALYSIS_WINDOW)
    return history, ratio_history, report


# --------------------------------------------------------------------------
# 1. Signal inspection
# --------------------------------------------------------------------------


def _shape_checks(trend: Any) -> tuple[float | None, bool, bool]:
    """Does the window's *shape* agree with its first-to-last comparison?

    `trend.py` decides direction by comparing the window's first and last
    values. That is exact, but it is only one of several things "the ratio is
    deteriorating" could mean, and it is sensitive to where the window happens
    to start. Two cheap independent reads on the same window:

    - a **least-squares slope** over the calculated values, normalised by their
      mean magnitude so it is comparable across ratios. This is the trend
      method `financial_health.md` §9 deferred; used here as a diagnostic, not
      as a change to the engine.
    - whether the **latest value is the window's extreme** in the claimed
      direction. A genuinely deteriorating ratio usually ends at its worst; one
      that ends mid-range is oscillating.

    A disagreement is not proof the signal is wrong -- both readings are
    defensible -- but a signal that clears the magnitude bar only on endpoints,
    with a flat-or-opposite slope and a mid-range final value, is where a
    threshold-driven false positive would live.

    Uses `statistics.linear_regression` from the standard library; no
    dependency is added for this.
    """
    if trend is None or trend.absolute_change is None:
        return None, False, False
    values = [
        r.value for r in trend.results if r.status is RatioStatus.CALCULATED and r.value is not None
    ]
    if len(values) < 3:
        return None, False, False

    slope_raw = linear_regression(range(len(values)), values).slope
    scale = mean(abs(v) for v in values) or 1.0
    slope = slope_raw / scale

    disagrees = (slope > 0) != (trend.absolute_change > 0) and abs(slope) > 1e-9
    latest = values[-1]
    latest_is_extreme = (
        latest == max(values) if trend.absolute_change > 0 else latest == min(values)
    )
    return round(slope, 6), bool(disagrees), bool(latest_is_extreme)


def _signal_rows(entry: dict[str, Any], report: Any) -> list[dict[str, Any]]:
    """Every signal, with the evidence a human needs to judge it.

    The golden set labels each company `distressed` (with a real bankruptcy
    date) or `healthy`, and every distressed filing is that company's last
    annual report before its petition. So a signal on a distressed filing is
    expected; a signal on a healthy one is a **false-positive candidate** and
    has to be read against the actual numbers -- not automatically counted as
    a false positive, because a healthy company can genuinely deteriorate in
    one dimension.
    """
    rows: list[dict[str, Any]] = []
    for signal in report.signals:
        trend = signal.trend
        magnitude = abs(trend.percent_change) if trend and trend.percent_change else None
        slope, slope_disagrees, latest_is_extreme = _shape_checks(trend)
        rows.append(
            {
                "company": entry["company"],
                "cohort": entry["cohort"],
                "bankruptcy_date": entry.get("bankruptcy_date"),
                "code": signal.code.value,
                "category": signal.category,
                "ratio_id": signal.ratio_id,
                "direction": trend.direction.value if trend else None,
                "economic_direction": trend.economic_direction.value if trend else None,
                "absolute_change": trend.absolute_change if trend else None,
                "percent_change": trend.percent_change if trend else None,
                "persistence": trend.persistence if trend else None,
                "periods_available": trend.periods_available if trend else None,
                "data_quality": trend.data_quality.value if trend else None,
                "series": (
                    "; ".join(
                        f"{r.period_label}={r.value:.4g}"
                        for r in trend.results
                        if r.status is RatioStatus.CALCULATED and r.value is not None
                    )
                    if trend
                    else ""
                ),
                "review_candidate": entry["cohort"] == "healthy",
                "marginal_magnitude": bool(
                    magnitude is not None
                    and magnitude < MARGINAL_MAGNITUDE_MULTIPLE * STABLE_MAGNITUDE_THRESHOLD
                ),
                "factual_not_trend": signal.code in _FACTUAL_SIGNALS,
                "normalised_slope": slope,
                "slope_disagrees_with_endpoints": slope_disagrees,
                "latest_is_window_extreme": latest_is_extreme,
                "endpoint_artifact_candidate": bool(
                    signal.code not in _FACTUAL_SIGNALS
                    and (slope_disagrees or not latest_is_extreme)
                    and magnitude is not None
                    and magnitude < 2 * STABLE_MAGNITUDE_THRESHOLD
                ),
                "evidence": signal.evidence.replace("\n", " | "),
            }
        )
    return rows


# --------------------------------------------------------------------------
# 2. Restatement verification against raw companyfacts
# --------------------------------------------------------------------------


def _raw_values(
    company_facts: dict[str, Any], tag: str, period_label: str
) -> dict[str, list[float]]:
    """Every raw `us-gaap:<tag>` USD value for a fiscal year, by accession.

    Reads the source JSON directly rather than any canonical fact, so it is an
    independent check on the classifier rather than a restatement of it.
    """
    year = period_label.removeprefix("FY")
    concept = company_facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not concept:
        return {}
    by_accession: dict[str, list[float]] = {}
    for entry in concept.get("units", {}).get("USD", []):
        end = entry.get("end") or ""
        if not end.startswith(year):
            continue
        accession = entry.get("accn")
        if accession:
            by_accession.setdefault(accession, []).append(float(entry["val"]))
    return by_accession


def _verify_restatement(row: dict[str, Any], company_facts: dict[str, Any]) -> dict[str, Any]:
    """Re-derive one classified restatement from the raw payload.

    Each side is looked up under **its own** tag. That matters for
    `tag_change`, where the filer re-presented the line under a different
    concept: searching the restated accession for the *original* tag would
    correctly find nothing, and a validator that did so would report the check
    as failed. The first version of this function did exactly that and scored
    7 of 8 `tag_change` samples `accession_absent` -- a defect in the
    validator, not in the classifier it was validating.
    """
    original_tag = row.get("original_tag")
    restated_tag = row.get("restated_tag")
    tag = original_tag if isinstance(original_tag, str) else None
    verdict = "unverifiable"
    detail = ""

    if not isinstance(original_tag, str) or not isinstance(restated_tag, str):
        detail = "At least one side is a derived fact with no originating XBRL tag."
    else:
        period = str(row["period_label"])
        original = _raw_values(company_facts, original_tag, period).get(
            str(row["original_accession"]), []
        )
        restated = _raw_values(company_facts, restated_tag, period).get(
            str(row["restated_accession"]), []
        )
        if not original or not restated:
            verdict = "accession_absent"
            detail = (
                f"Not both sides present in the raw payload: {original_tag}@original -> "
                f"{original}, {restated_tag}@restated -> {restated}."
            )
        else:
            matches_recorded = any(
                abs(a - float(row["original_value"])) <= 1.0 for a in original
            ) and any(abs(b - float(row["restated_value"])) <= 1.0 for b in restated)
            differs = any(abs(a - b) > 1.0 for a in original for b in restated)
            tags_differ = original_tag != restated_tag

            if row["category"] == "same_tag_restatement":
                # Claim: one tag, two accessions, materially different values.
                verdict = (
                    "confirmed"
                    if (matches_recorded and differs and not tags_differ)
                    else "not_confirmed"
                )
            elif row["category"] == "tag_change":
                # Claim: the filer moved the line to a different concept.
                verdict = "confirmed" if (matches_recorded and tags_differ) else "not_confirmed"
            else:
                verdict = "confirmed" if matches_recorded else "not_confirmed"
            detail = (
                f"{original_tag}@original -> {original}; {restated_tag}@restated -> {restated}."
            )

    ratio = (
        max(abs(row["original_value"]), abs(row["restated_value"]))
        / max(min(abs(row["original_value"]), abs(row["restated_value"])), 1e-9)
        if row["original_value"] and row["restated_value"]
        else None
    )
    return {
        **{k: row[k] for k in ("company", "concept", "period_label", "category")},
        "original_value": row["original_value"],
        "restated_value": row["restated_value"],
        "tag": tag,
        "verdict": verdict,
        # A near-exact power-of-ten ratio between two values of the same tag is
        # a scale/units error by the filer, not a restatement. Tesla's FY2016
        # `DebtCurrent` is the known instance.
        "looks_like_scale_error": bool(
            ratio is not None and any(abs(ratio - p) / p < 0.01 for p in (1000.0, 1_000_000.0))
        ),
        "detail": detail,
    }


# --------------------------------------------------------------------------
# 3. Pre-phase-in degradation
# --------------------------------------------------------------------------


def _coverage_by_filing_year(
    entry: dict[str, Any], history: Any, ratio_history: Any
) -> list[dict[str, Any]]:
    """Ratio coverage for each fiscal period, tagged with the vintage of the
    filing that first reported it.

    The concern the audit raised is not that old filings resolve badly -- they
    are allowed to -- but that a thin period might reach Phase 6/7 looking like
    a usable one. This makes the thinness visible per period so it can be
    checked that it is *reported* rather than hidden.
    """
    first_filed: dict[str, str] = {}
    for filing in sorted(history.financials.filings, key=lambda f: f.filed):
        for period_label in filing.period_labels:
            first_filed.setdefault(period_label, filing.filed)

    rows: list[dict[str, Any]] = []
    for period_label, filed in sorted(first_filed.items()):
        results = [
            r for series in ratio_history.values() for r in series if r.period_label == period_label
        ]
        if not results:
            continue
        calculated = sum(1 for r in results if r.status is RatioStatus.CALCULATED)
        rows.append(
            {
                "company": entry["company"],
                "period_label": period_label,
                "first_reported_by_filing_filed": filed,
                "filing_year": int(filed[:4]),
                "ratios_calculated": calculated,
                "ratios_total": len(results),
                "coverage": round(calculated / len(results), 4),
            }
        )
    return rows


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    client = SecEdgarClient()

    signal_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for entry in manifest["entries"]:
        history, ratio_history, report = _multi_filing_report(entry, client)
        signal_rows.extend(_signal_rows(entry, report))
        coverage_rows.extend(_coverage_by_filing_year(entry, history, ratio_history))
        logger.info(
            "%s (%s): %d signals, %d periods",
            entry["company"],
            entry["cohort"],
            len(report.signals),
            len(report.periods_considered),
        )

    signals = pd.DataFrame(signal_rows)
    coverage = pd.DataFrame(coverage_rows)
    signals.to_csv(OUT_DIR / "m4_signal_inspection.csv", index=False)
    coverage.to_csv(OUT_DIR / "m4_coverage_by_vintage.csv", index=False)

    # --- restatement verification -----------------------------------------
    restatements = pd.read_csv(OUT_DIR / "qm04_restatements.csv")
    rng = random.Random(SAMPLE_SEED)
    sampled: list[dict[str, Any]] = []
    for _category, group in restatements.groupby("category"):
        # Stratified, so a rare category is checked as thoroughly as a common
        # one; each record already carries its own `category` column.
        records = group.to_dict("records")
        picked = rng.sample(records, min(RESTATEMENT_SAMPLE_PER_CATEGORY, len(records)))
        sampled.extend(picked)

    facts_cache: dict[int, dict[str, Any]] = {}
    verified: list[dict[str, Any]] = []
    for row in sampled:
        cik = int(row["cik"])
        if cik not in facts_cache:
            facts_cache[cik] = _company_facts(cik)
        verified.append(_verify_restatement(row, facts_cache[cik]))
    verification = pd.DataFrame(verified)
    verification.to_csv(OUT_DIR / "m4_restatement_verification.csv", index=False)

    # Scale errors across *all* restatements, not just the sample -- a 1000x
    # gap between two values of one tag is cheap to detect and important.
    scale_errors = restatements[
        restatements.apply(
            lambda r: bool(
                r["original_value"]
                and r["restated_value"]
                and abs(
                    max(abs(r["original_value"]), abs(r["restated_value"]))
                    / max(min(abs(r["original_value"]), abs(r["restated_value"])), 1e-9)
                    - 1000.0
                )
                / 1000.0
                < 0.01
            ),
            axis=1,
        )
    ]
    scale_errors.to_csv(OUT_DIR / "m4_scale_errors.csv", index=False)

    healthy = signals[signals["review_candidate"]]
    summary: dict[str, Any] = {
        "analysis_window": ANALYSIS_WINDOW,
        "signals": {
            "total": len(signals),
            "by_cohort": signals["cohort"].value_counts().to_dict(),
            "by_code": signals["code"].value_counts().to_dict(),
            "healthy_cohort_signals_to_review": len(healthy),
            "healthy_cohort_by_company": healthy["company"].value_counts().to_dict(),
            "marginal_magnitude_count": int(signals["marginal_magnitude"].sum()),
            "factual_not_trend_count": int(signals["factual_not_trend"].sum()),
            "endpoint_artifact_candidates": int(signals["endpoint_artifact_candidate"].sum()),
            "endpoint_artifact_by_cohort": (
                signals[signals["endpoint_artifact_candidate"]]["cohort"].value_counts().to_dict()
            ),
            "slope_disagrees_count": int(signals["slope_disagrees_with_endpoints"].sum()),
        },
        "restatement_verification": {
            "sampled": len(verification),
            "by_verdict": verification["verdict"].value_counts().to_dict(),
            "by_category_and_verdict": (
                verification.groupby(["category", "verdict"]).size().unstack(fill_value=0).to_dict()
            ),
            "scale_errors_across_all_453": len(scale_errors),
            "scale_error_rows": scale_errors[
                ["company", "concept", "period_label", "original_value", "restated_value"]
            ].to_dict("records"),
        },
        "coverage_by_vintage": {
            "periods": len(coverage),
            "mean_coverage_by_filing_year": {
                int(year): round(float(group["coverage"].mean()), 4)
                for year, group in coverage.groupby("filing_year")
            },
            "period_count_by_filing_year": dict(sorted(Counter(coverage["filing_year"]).items())),
        },
    }
    (OUT_DIR / "m4_validation.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("M-4 validation summary:\n%s", json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
