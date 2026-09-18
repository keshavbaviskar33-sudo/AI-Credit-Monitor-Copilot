"""Phase 9 step 4: the confound is eligibility, not survivorship — and the fix.

Step 3 (`phase9_pit_panel.py`) ran the experiment Phase 8 asked for: rebuild
the comparison cohort point-in-time so it is no longer selected for having
survived. The result was **negative and instructive**. Performance barely moved
(logistic 0.803 -> 0.797) and cohort separability *rose* (0.792 -> 0.843).

The reason is visible in one number. BRD records only large public
bankruptcies, so the event cohort is large by construction, while a random draw
from the real filer population is dominated by small companies:

    median log(total assets)      event      comparison      gap
    Phase 8 survivor cohort       21.24      19.94           3.7x
    Phase 9 point-in-time         21.24      18.56          14.5x

Sampling point-in-time made the mismatch *worse*, because the survivor frame
was already biased toward larger companies. So what a cohort probe mostly
detects is not survivorship -- it is **size and eligibility**.

This script tests the fix that follows: restrict the comparison cohort to
companies that could plausibly have been BRD cases at all -- comparable size,
comparable filing history -- and re-measure. If the diagnosis is right, cohort
separability should fall sharply, and whatever bankruptcy discrimination
survives is much closer to a real signal.

It reuses the existing point-in-time panel; no new data is fetched.

    uv run python scripts/phase9_size_matched.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.metrics import evaluate
from credit_risk_copilot.modeling.model import (
    ModelSpec,
    build_model_specs,
    design_matrix,
    run_walk_forward,
)
from credit_risk_copilot.modeling.splits import assert_temporal_ordering, walk_forward_folds

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
OUT_DIR = Path("data/processed/phase9")

PRIMARY_MODEL = "logistic_scale+levels+ratios+trends+signals+quality"
CHALLENGER_MODEL = "gradient_boosting_all"

#: Comparison rows are kept only if their company size falls inside the event
#: cohort's own central range. The 10th-90th percentile band rather than the
#: full range: the aim is a comparison population the event cohort could have
#: been drawn from, and the extreme tails of the event cohort are single
#: companies rather than a population.
EVENT_SIZE_BAND = (0.10, 0.90)


def _load(
    path: Path, manifest_path: Path
) -> tuple[list[Observation], pd.DataFrame, dict[int, str]]:
    frame = pd.read_csv(path)
    rows = frame.replace({np.nan: None}).to_dict("records")
    observations = [o for o in observations_from_rows(rows) if o.outcome.is_usable]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cohort_of = {
        int(r["cik"]): ("event" if r["cohort"] == "event" else "comparison")
        for r in manifest["companies"]
    }
    return observations, frame[frame["label"].notna()].reset_index(drop=True), cohort_of


def _probe(
    observations: list[Observation], plan: Any, spec: ModelSpec, labels: np.ndarray
) -> float | None:
    """Walk-forward AUC for an arbitrary binary target on the same features."""
    add_indicators = spec.family == "logistic"
    scores: list[float] = []
    truth: list[int] = []
    for fold in plan.folds:
        train_idx, test_idx = list(fold.train_indices), list(fold.test_indices)
        if len(np.unique(labels[train_idx])) < 2 or len(np.unique(labels[test_idx])) < 2:
            continue
        x_train, names = design_matrix(
            [observations[i] for i in train_idx],
            spec.feature_names,
            add_missing_indicators=add_indicators,
        )
        x_test, _ = design_matrix(
            [observations[i] for i in test_idx],
            spec.feature_names,
            add_missing_indicators=add_indicators,
        )
        if x_test.shape[1] != len(names):
            x_test = np.hstack([x_test, np.zeros((x_test.shape[0], len(names) - x_test.shape[1]))])
        assert spec.estimator_factory is not None
        estimator = spec.estimator_factory()
        estimator.fit(x_train, labels[train_idx])
        scores.extend(estimator.predict_proba(x_test)[:, 1].tolist())
        truth.extend(labels[test_idx].tolist())
    if len(set(truth)) < 2:
        return None
    return float(roc_auc_score(truth, scores))


def _measure(
    observations: list[Observation], cohort_of: dict[int, str], label: str
) -> dict[str, Any]:
    plan = walk_forward_folds(observations)
    if not plan.folds:
        return {"note": "no fold met the burn-in requirement after filtering"}
    assert_temporal_ordering(observations, plan)
    specs = {spec.name: spec for spec in build_model_specs()}

    cohort_labels = np.array(
        [1 if cohort_of.get(o.key.cik) == "event" else 0 for o in observations]
    )
    result: dict[str, Any] = {
        "rows": len(observations),
        "events": sum(1 for o in observations if o.outcome.label == 1),
        "companies": len({o.key.cik for o in observations}),
        "event_cohort_rows": int(cohort_labels.sum()),
        "folds": len(plan.folds),
    }

    for name in (PRIMARY_MODEL, CHALLENGER_MODEL):
        spec = specs[name]
        indices, scores, _ = run_walk_forward(spec, observations, plan)
        if indices.size == 0:
            continue
        y = np.array([observations[i].outcome.label for i in indices], dtype=int)
        companies = np.array([observations[i].key.cik for i in indices])
        scored = evaluate(y, scores, companies, bootstrap=True)
        separability = _probe(observations, plan, spec, cohort_labels)
        result[name] = {
            "bankruptcy_roc_auc": round(scored.roc_auc, 4) if scored.roc_auc else None,
            "bankruptcy_roc_auc_ci": (
                [round(v, 4) for v in scored.roc_auc_ci] if scored.roc_auc_ci else None
            ),
            "bankruptcy_pr_auc": round(scored.pr_auc, 4) if scored.pr_auc else None,
            "pr_auc_baseline": round(scored.pr_auc_baseline, 4),
            "cohort_separability_auc": round(separability, 4) if separability else None,
            "separability_minus_bankruptcy": (
                round(separability - scored.roc_auc, 4) if separability and scored.roc_auc else None
            ),
        }
        logger.info(
            "[%s] %-52s bankruptcy %.4f | cohort %.4f",
            label,
            name,
            scored.roc_auc or 0.0,
            separability or 0.0,
        )
    return result


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    observations, frame, cohort_of = _load(
        OUT_DIR / "observations_pit.csv", OUT_DIR / "pit_corpus_manifest.json"
    )
    sizes = np.array([o.features.get("log_total_assets") or np.nan for o in observations])
    is_event = np.array([cohort_of.get(o.key.cik) == "event" for o in observations])

    low, high = np.nanquantile(sizes[is_event], EVENT_SIZE_BAND)
    logger.info(
        "Event cohort size band (log total assets): %.2f - %.2f (%.0f%%-%.0f%% of events)",
        low,
        high,
        EVENT_SIZE_BAND[0] * 100,
        EVENT_SIZE_BAND[1] * 100,
    )

    # Keep every event row; keep a comparison row only if its company sits
    # inside the band. The event cohort is not filtered -- narrowing it would
    # change the target population rather than the control group.
    keep = is_event | ((sizes >= low) & (sizes <= high))
    matched = [o for o, k in zip(observations, keep, strict=True) if k]
    logger.info(
        "Size-matched panel: %d rows (from %d); comparison rows %d -> %d",
        len(matched),
        len(observations),
        int((~is_event).sum()),
        int((~is_event & keep).sum()),
    )

    summary = {
        "method": {
            "note": "event rows all kept; comparison rows kept only inside the event cohort's "
            "10th-90th percentile size band. Tests whether the cohort probe is detecting "
            "eligibility/size rather than survivorship.",
            "event_size_band_log_assets": [round(float(low), 3), round(float(high), 3)],
            "event_size_band_usd": [
                round(float(np.exp(low)) / 1e6, 1),
                round(float(np.exp(high)) / 1e6, 1),
            ],
        },
        "unmatched_point_in_time": _measure(observations, cohort_of, "unmatched"),
        "size_matched": _measure(matched, cohort_of, "size-matched"),
    }

    phase8_observations, _, phase8_cohort = _load(
        PHASE8_DIR / "observations_primary.csv", PHASE8_DIR / "corpus_manifest.json"
    )
    phase8_sizes = np.array(
        [o.features.get("log_total_assets") or np.nan for o in phase8_observations]
    )
    phase8_is_event = np.array(
        [phase8_cohort.get(o.key.cik) == "event" for o in phase8_observations]
    )
    summary["size_gap_between_cohorts"] = {
        "phase8_survivor": {
            "event_median_log_assets": round(float(np.nanmedian(phase8_sizes[phase8_is_event])), 3),
            "comparison_median_log_assets": round(
                float(np.nanmedian(phase8_sizes[~phase8_is_event])), 3
            ),
        },
        "phase9_point_in_time": {
            "event_median_log_assets": round(float(np.nanmedian(sizes[is_event])), 3),
            "comparison_median_log_assets": round(float(np.nanmedian(sizes[~is_event])), 3),
        },
    }

    (OUT_DIR / "size_matched_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Summary:\n%s", json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
