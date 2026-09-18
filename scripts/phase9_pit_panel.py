"""Phase 9 step 3: rebuild the panel on a point-in-time cohort and re-measure.

The controlled experiment Phase 8's limitations section could only describe.
Two panels, differing in exactly one respect:

    Panel A (Phase 8)   264 event companies + 426 comparison companies drawn
                        from SEC's *current* ticker file (survivors)
    Panel B (Phase 9)   the same 264 event companies + 426 comparison companies
                        drawn from the *point-in-time* filer universe

Everything else is held constant: same event cohort, same comparison-cohort
**size**, same SIC screen, same horizon policy, same feature pipeline, same
walk-forward evaluation. Size-matching matters -- a comparison cohort of a
different size would change the base rate and confound the very comparison
this script exists to make, so the point-in-time cohort is subsampled to 426
rather than using every company the corpus build kept.

What moves between A and B is the answer to "how much of Phase 8's measured
performance was survivorship?".

    uv run python scripts/phase9_pit_panel.py
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import HorizonPolicy, Observation
from credit_risk_copilot.modeling.dataset import (
    as_rows,
    build_company_observations,
    censoring_reasons,
    outcome_counts,
)
from credit_risk_copilot.modeling.labels import load_event_table, measure_label_completeness
from credit_risk_copilot.modeling.metrics import evaluate
from credit_risk_copilot.modeling.model import (
    ModelSpec,
    build_model_specs,
    design_matrix,
    run_walk_forward,
)
from credit_risk_copilot.modeling.splits import assert_temporal_ordering, walk_forward_folds
from credit_risk_copilot.sec_edgar import SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
PHASE8_DIR = Path("data/processed/phase8")
OUT_DIR = Path("data/processed/phase9")
PIT_MANIFEST = OUT_DIR / "pit_corpus_manifest.json"
PANEL = OUT_DIR / "observations_pit.csv"

PRIMARY_MODEL = "logistic_scale+levels+ratios+trends+signals+quality"
CHALLENGER_MODEL = "gradient_boosting_all"

HORIZON_DAYS = 365
MATCH_SEED = 20260918


def _company_facts(cik: int) -> dict[str, Any] | None:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    if not path.exists():
        return None
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _matched_companies(manifest: dict[str, Any], target_comparison: int) -> list[dict[str, Any]]:
    """Event cohort in full, comparison cohort subsampled to Phase 8's size."""
    events = [r for r in manifest["companies"] if r["cohort"] == "event"]
    comparison = [r for r in manifest["companies"] if r["cohort"] == "comparison_pit"]
    rng = random.Random(MATCH_SEED)
    if len(comparison) > target_comparison:
        comparison = rng.sample(comparison, target_comparison)
    logger.info(
        "Matched corpus: %d event + %d point-in-time comparison (%d still listed today)",
        len(events),
        len(comparison),
        sum(1 for r in comparison if r.get("survived_to_current_ticker_file")),
    )
    return events + comparison


def build_panel(companies: list[dict[str, Any]], horizon: HorizonPolicy) -> list[Observation]:
    client = SecEdgarClient()
    events = load_event_table(RAW_DIR / "brd" / "cases.csv")
    observations: list[Observation] = []

    for index, record in enumerate(companies, start=1):
        cik = int(record["cik"])
        company_facts = _company_facts(cik)
        if company_facts is None:
            continue
        try:
            filings = client.annual_filings(cik)
        except Exception as exc:  # noqa: BLE001
            logger.debug("CIK%010d: filing index unavailable (%s)", cik, exc)
            continue
        built, _ = build_company_observations(
            company_facts=company_facts,
            filings=filings,
            cik=cik,
            company=str(record.get("company") or f"CIK{cik}"),
            events=events,
            horizon=horizon,
        )
        observations.extend(built)
        if index % 50 == 0:
            logger.info(
                "%d/%d companies -> %d observations", index, len(companies), len(observations)
            )
    return observations


def _measure(observations: list[Observation], label: str) -> dict[str, Any]:
    plan = walk_forward_folds(observations)
    assert_temporal_ordering(observations, plan)
    specs = {spec.name: spec for spec in build_model_specs()}

    results: dict[str, Any] = {"folds": len(plan.folds)}
    for name in ("heuristic_leverage", PRIMARY_MODEL, CHALLENGER_MODEL):
        indices, scores, _ = run_walk_forward(specs[name], observations, plan)
        if indices.size == 0:
            continue
        y = np.array([observations[i].outcome.label for i in indices], dtype=int)
        companies = np.array([observations[i].key.cik for i in indices])
        result = evaluate(y, scores, companies, bootstrap=True)
        results[name] = {
            "roc_auc": round(result.roc_auc, 4) if result.roc_auc else None,
            "roc_auc_ci": ([round(v, 4) for v in result.roc_auc_ci] if result.roc_auc_ci else None),
            "pr_auc": round(result.pr_auc, 4) if result.pr_auc else None,
            "pr_auc_baseline": round(result.pr_auc_baseline, 4),
            "recall_at_10pct": round(result.alert_rates[-1].recall, 4),
            "calibration_slope": (
                round(result.calibration_slope, 3) if result.calibration_slope else None
            ),
            "n_rows": result.n_rows,
            "n_events": result.n_events,
        }
        logger.info("[%s] %-52s %s", label, name, result.headline())

    results["cohort_separability"] = _cohort_probe(observations, plan, specs)
    return results


def _cohort_probe(
    observations: list[Observation], plan: Any, specs: dict[str, ModelSpec]
) -> dict[str, Any]:
    """The Phase 8 probe, re-run on this panel.

    If the point-in-time cohort works, this is the number that should fall:
    the comparison companies are no longer selected for having survived, so
    there should be less for a model to recognise about which sample a company
    came from.
    """
    manifest = json.loads(PIT_MANIFEST.read_text(encoding="utf-8"))
    cohort_of = {int(r["cik"]): r["cohort"] for r in manifest["companies"]}
    labels = np.array([1 if cohort_of.get(obs.key.cik) == "event" else 0 for obs in observations])
    if len(np.unique(labels)) < 2:
        return {}

    probed: dict[str, Any] = {}
    for name in (PRIMARY_MODEL, CHALLENGER_MODEL):
        spec = specs[name]
        add_indicators = spec.family == "logistic"
        scores: list[float] = []
        truth: list[int] = []
        for fold in plan.folds:
            train_idx, test_idx = list(fold.train_indices), list(fold.test_indices)
            if len(np.unique(labels[train_idx])) < 2 or len(np.unique(labels[test_idx])) < 2:
                continue
            x_train, train_names = design_matrix(
                [observations[i] for i in train_idx],
                spec.feature_names,
                add_missing_indicators=add_indicators,
            )
            x_test, _ = design_matrix(
                [observations[i] for i in test_idx],
                spec.feature_names,
                add_missing_indicators=add_indicators,
            )
            if x_test.shape[1] != len(train_names):
                x_test = np.hstack(
                    [x_test, np.zeros((x_test.shape[0], len(train_names) - x_test.shape[1]))]
                )
            assert spec.estimator_factory is not None
            estimator = spec.estimator_factory()
            estimator.fit(x_train, labels[train_idx])
            scores.extend(estimator.predict_proba(x_test)[:, 1].tolist())
            truth.extend(labels[test_idx].tolist())
        if len(set(truth)) > 1:
            probed[name] = round(float(roc_auc_score(truth, scores)), 4)
    return probed


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    phase8_manifest = json.loads((PHASE8_DIR / "corpus_manifest.json").read_text(encoding="utf-8"))
    target = sum(1 for r in phase8_manifest["companies"] if r["cohort"] == "comparison")

    manifest = json.loads(PIT_MANIFEST.read_text(encoding="utf-8"))
    companies = _matched_companies(manifest, target)

    completeness = measure_label_completeness(load_event_table(RAW_DIR / "brd" / "cases.csv"))
    horizon = HorizonPolicy(
        horizon_days=HORIZON_DAYS, label_complete_through=completeness.label_complete_through
    )

    observations = build_panel(companies, horizon)
    usable = [o for o in observations if o.outcome.is_usable]
    pd.DataFrame(as_rows(observations)).to_csv(PANEL, index=False)

    counts = outcome_counts(observations)
    logger.info(
        "PIT panel: %d observations, %d usable (%d positive), %d companies",
        len(observations),
        len(usable),
        counts["positive"],
        len({o.key.cik for o in usable}),
    )

    summary: dict[str, Any] = {
        "design": {
            "event_companies": sum(1 for r in companies if r["cohort"] == "event"),
            "comparison_companies": sum(1 for r in companies if r["cohort"] == "comparison_pit"),
            "comparison_still_listed_today": sum(
                1 for r in companies if r.get("survived_to_current_ticker_file")
            ),
            "matched_to_phase8_comparison_size": target,
            "horizon_days": HORIZON_DAYS,
            "label_complete_through": completeness.label_complete_through.isoformat(),
        },
        "panel": {
            "observations_built": len(observations),
            "usable_rows": len(usable),
            "outcome_counts": counts,
            "censoring_reasons": censoring_reasons(observations),
            "event_rate": round(counts["positive"] / len(usable), 5) if usable else None,
            "companies_with_rows": len({o.key.cik for o in usable}),
            "companies_with_events": len({o.key.cik for o in usable if o.outcome.label == 1}),
        },
        "point_in_time_results": _measure(usable, "PIT"),
    }

    phase8 = json.loads((PHASE8_DIR / "model_summary.json").read_text(encoding="utf-8"))
    by_model = {row["model"]: row for row in phase8["results"]}
    summary["phase8_survivor_results"] = {
        name: {
            "roc_auc": by_model[name]["roc_auc"],
            "pr_auc": by_model[name]["pr_auc"],
            "pr_auc_baseline": by_model[name]["pr_auc_baseline"],
            "recall_at_10pct": by_model[name]["recall_at_10pct"],
        }
        for name in ("heuristic_leverage", PRIMARY_MODEL, CHALLENGER_MODEL)
        if name in by_model
    }
    summary["phase8_cohort_separability"] = phase8["robustness"].get("cohort_separability", {})

    (OUT_DIR / "pit_panel_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info(
        "Survivor vs point-in-time:\n%s",
        json.dumps(
            {
                "survivor": summary["phase8_survivor_results"],
                "point_in_time": {
                    k: v for k, v in summary["point_in_time_results"].items() if isinstance(v, dict)
                },
            },
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
