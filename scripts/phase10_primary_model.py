"""Re-open D-028: should gradient boosting be the primary model?

[D-028](../docs/decision_log.md) kept regularised logistic regression as the
primary model even though gradient boosting scored higher on every
discrimination metric. It gave four reasons, and only two of them were claims
about the data rather than preferences:

- **(a)** the boosting gap is largest exactly where the cohort confound is
  largest, so boosting is the *less* trustworthy of the two on this corpus;
- **(b)** boosting's dominant feature is `log_total_assets`, which is the
  confound's own marker.

Reason (c) -- that only the logistic model's coefficients are readable -- was
overtaken by Phase 9: `explain/adapters.py` gives the boosting model exact
TreeSHAP contributions in the same `ModelExplanation` schema
([D-029](../docs/decision_log.md), [D-030](../docs/decision_log.md)), so the two
families are now equally explainable to every downstream phase. Reason (d),
that the simpler model is easier to defend line by line, is a preference.

So the decision turns entirely on (a) and (b), and both are testable. This
script runs the test D-028 named but never performed:

1. **Within the event cohort**, where cohort membership is constant and can
   carry no information, does boosting keep its lead? With a *paired*
   bootstrap on the difference ([D-027](../docs/decision_log.md)), not two
   overlapping intervals.
2. **Size-blinded** -- the `scale` family (`log_total_assets`, `log_revenue`)
   removed from both models. If boosting's advantage is size, it disappears
   here. If it survives, reason (b) is wrong about what boosting is using.
3. **Cohort separability of the size-blinded models**, so the confound is
   measured on the same feature set the discrimination numbers come from.
4. **Permutation importance inside the event cohort**, which is where the
   size-dominance claim has to hold if it is to justify the decision.

Every number is walk-forward out-of-time on the existing Phase 8 panel; no
model is scored on a row it or an earlier fold trained on.

    uv run python scripts/phase10_primary_model.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.metrics import delta_auc_ci, evaluate
from credit_risk_copilot.modeling.model import (
    RANDOM_SEED,
    ModelArtifact,
    ModelSpec,
    _gradient_boosting,
    _logistic_pipeline,
    build_model_specs,
    design_matrix,
    fit_final_model,
    labels_array,
    linear_coefficients,
    run_walk_forward,
    utc_now,
)
from credit_risk_copilot.modeling.splits import assert_temporal_ordering, walk_forward_folds

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
ARTIFACT_DIR = PHASE8_DIR / "artifacts"
OUT_DIR = Path("data/processed/phase10")

#: The Phase 8 spec promoted to primary by D-034. Deliberately the *existing*
#: `build_model_specs()` entry rather than this script's own comparison spec:
#: nothing about the model is retuned by this decision, so the shipped artifact
#: must be the object Phase 8 already evaluated, only re-designated.
PROMOTED_MODEL = "gradient_boosting_all"

#: The two families, with and without the `scale` family. Everything else --
#: hyperparameters, imputation, indicators -- is exactly what Phase 8 shipped,
#: so any difference measured here is the feature set or the family, never a
#: retuning.
FULL_FAMILIES = ("scale", "levels", "ratios", "trends", "signals", "quality")
BLIND_FAMILIES = ("levels", "ratios", "trends", "signals", "quality")


def _specs() -> dict[str, ModelSpec]:
    def spec(name: str, family: str, families: tuple[str, ...]) -> ModelSpec:
        factory = _logistic_pipeline if family == "logistic" else _gradient_boosting
        return ModelSpec(
            name=name,
            family=family,
            feature_families=families,
            configuration={"role": "D-028 re-examination"},
            estimator_factory=factory,
        )

    return {
        "logistic_full": spec("logistic_full", "logistic", FULL_FAMILIES),
        "boosting_full": spec("boosting_full", "gradient_boosting", FULL_FAMILIES),
        "logistic_size_blind": spec("logistic_size_blind", "logistic", BLIND_FAMILIES),
        "boosting_size_blind": spec("boosting_size_blind", "gradient_boosting", BLIND_FAMILIES),
    }


def load_panel() -> list[Observation]:
    frame = pd.read_csv(PHASE8_DIR / "observations_primary.csv")
    rows = frame.replace({np.nan: None}).to_dict("records")
    return [o for o in observations_from_rows(rows) if o.outcome.is_usable]


def cohort_map() -> dict[int, str]:
    manifest = json.loads((PHASE8_DIR / "corpus_manifest.json").read_text())
    return {int(record["cik"]): record["cohort"] for record in manifest["companies"]}


def _scores(
    spec: ModelSpec, observations: list[Observation], plan: Any
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pooled out-of-fold scores, truth and CIK, in one fixed row order.

    Both models are scored on identical rows in identical order, which is what
    makes the paired bootstrap in `delta_auc_ci` valid. The CIKs are what the
    bootstrap resamples on, so one company's ten filings count as one draw
    rather than ten ([D-027](../docs/decision_log.md)).
    """
    indices, scores, _ = run_walk_forward(spec, observations, plan)
    order = np.argsort(indices, kind="stable")
    ordered = indices[order]
    return (
        scores[order],
        np.array([observations[i].outcome.label for i in ordered], dtype=int),
        np.array([observations[i].key.cik for i in ordered]),
    )


def _head_to_head(
    observations: list[Observation], label: str, min_train_events: int = 20
) -> dict[str, Any]:
    """Both families, both feature sets, on one population."""
    plan = walk_forward_folds(observations, min_train_events=min_train_events)
    if not plan.folds:
        return {"note": f"{label}: too few rows to form a fold"}
    assert_temporal_ordering(observations, plan)

    specs = _specs()
    scored: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    metrics: dict[str, Any] = {}
    for name, spec in specs.items():
        scores, truth, ciks = _scores(spec, observations, plan)
        scored[name] = (scores, truth, ciks)
        result = evaluate(truth, scores, ciks)
        metrics[name] = {
            "roc_auc": round(result.roc_auc, 4) if result.roc_auc is not None else None,
            "roc_auc_ci": ([round(v, 4) for v in result.roc_auc_ci] if result.roc_auc_ci else None),
            "pr_auc": round(result.pr_auc, 4) if result.pr_auc is not None else None,
            "pr_auc_baseline": round(result.pr_auc_baseline, 4),
        }

    # Paired differences: boosting minus logistic on the same rows, and each
    # family's own cost of losing the scale features.
    pairs = {
        "boosting_minus_logistic_full": ("boosting_full", "logistic_full"),
        "boosting_minus_logistic_size_blind": ("boosting_size_blind", "logistic_size_blind"),
        "boosting_size_cost": ("boosting_size_blind", "boosting_full"),
        "logistic_size_cost": ("logistic_size_blind", "logistic_full"),
    }
    deltas: dict[str, Any] = {}
    for key, (left, right) in pairs.items():
        # `delta_auc_ci` reports AUC(second) - AUC(first), so the baseline is
        # passed first and the model under test second.
        truth, ciks = scored[right][1], scored[right][2]
        assert np.array_equal(truth, scored[left][1]), "paired bootstrap needs identical rows"
        interval = delta_auc_ci(truth, scored[right][0], scored[left][0], ciks)
        if interval is None:
            deltas[key] = {"note": "too few companies for a grouped bootstrap"}
            continue
        delta, low, high = interval
        deltas[key] = {
            "delta_roc_auc": round(delta, 4),
            "ci_low": round(low, 4),
            "ci_high": round(high, 4),
            "excludes_zero": bool(low > 0.0 or high < 0.0),
        }

    return {
        "population": label,
        "rows": len(observations),
        "events": sum(1 for o in observations if o.outcome.label == 1),
        "companies": len({o.key.cik for o in observations}),
        "folds": len(plan.folds),
        "metrics": metrics,
        "paired_deltas": deltas,
    }


def _cohort_separability(
    observations: list[Observation], cohorts: dict[int, str]
) -> dict[str, Any]:
    """How well each feature set predicts *which sample a company came from*.

    Identical to the Phase 8 probe except that it is also run on the
    size-blinded features, which is the question D-028's reason (b) implies:
    if size is what carries the confound, removing it should move this number.
    """
    relabelled: list[Observation] = []
    for observation in observations:
        cohort = cohorts.get(observation.key.cik)
        if cohort is None:
            continue
        outcome = observation.outcome.model_copy(update={"label": 1 if cohort == "event" else 0})
        relabelled.append(observation.model_copy(update={"outcome": outcome}))

    plan = walk_forward_folds(relabelled, min_train_events=20)
    if not plan.folds:
        return {"note": "no folds"}
    results: dict[str, Any] = {
        "note": "label replaced by cohort membership; higher means the sampling design is "
        "recoverable from the features alone",
        "event_cohort_rows": sum(1 for o in relabelled if o.outcome.label == 1),
        "comparison_cohort_rows": sum(1 for o in relabelled if o.outcome.label == 0),
    }
    for name, spec in _specs().items():
        scores, truth, ciks = _scores(spec, relabelled, plan)
        result = evaluate(truth, scores, ciks, bootstrap=False)
        results[name] = round(result.roc_auc, 4) if result.roc_auc is not None else None
    return results


def _permutation_importance(
    spec: ModelSpec, observations: list[Observation], top_n: int = 10
) -> list[dict[str, Any]]:
    from sklearn.inspection import permutation_importance

    estimator, names = fit_final_model(spec, observations)
    x, _ = design_matrix(
        observations, spec.feature_names, add_missing_indicators=spec.family == "logistic"
    )
    y = labels_array(observations)
    result = permutation_importance(
        estimator, x, y, scoring="roc_auc", n_repeats=5, random_state=RANDOM_SEED
    )
    order = np.argsort(-result.importances_mean)[:top_n]
    total = float(np.clip(result.importances_mean, 0.0, None).sum()) or 1.0
    return [
        {
            "feature": names[int(i)],
            "auc_drop": round(float(result.importances_mean[int(i)]), 5),
            "share_of_positive_drop": round(
                float(max(result.importances_mean[int(i)], 0.0)) / total, 4
            ),
        }
        for i in order
    ]


def _ship_promoted_artifact(
    observations: list[Observation], metrics: dict[str, Any]
) -> dict[str, Any]:
    """Refit and persist the promoted model beside the one it supersedes.

    The logistic artifact is **not** deleted. It remains the measured
    comparator D-028 made it, it is what every Phase 8/9 number quoted for the
    "primary model" was computed from, and a decision that erases its own
    predecessor cannot be audited.
    """
    spec = next(s for s in build_model_specs() if s.name == PROMOTED_MODEL)
    estimator, names = fit_final_model(spec, observations)
    dates = sorted(observation.key.prediction_date for observation in observations)
    plan = walk_forward_folds(observations, min_train_events=20)

    artifact = ModelArtifact(
        name=spec.name,
        family=spec.family,
        created_utc=utc_now(),
        feature_families=spec.feature_families,
        feature_names=tuple(names),
        configuration={**spec.configuration, "role": "primary (promoted by D-034)"},
        random_seed=RANDOM_SEED,
        target_definition={
            "event": "BRD-recorded Chapter 7/11 petition",
            "horizon_days": 365,
            "observation_unit": "one company per annual filing, at the filing receipt date",
            "censoring": "rows whose window exceeds label completeness, or that sit inside an "
            "active proceeding, are excluded",
        },
        dataset_summary={
            "rows": len(observations),
            "events": sum(1 for o in observations if o.outcome.label == 1),
            "companies": len({o.key.cik for o in observations}),
        },
        training_period=(dates[0].isoformat(), dates[-1].isoformat()),
        evaluation_strategy=f"{plan.strategy} ({len(plan.folds)} folds)",
        metrics=metrics,
        # A tree ensemble has no coefficient vector. `None` here is the honest
        # shape, and Phase 9's TreeSHAP adapter is what reads this model.
        coefficients=linear_coefficients(estimator, names),
    )
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(estimator, ARTIFACT_DIR / f"{spec.name}.joblib")
    (ARTIFACT_DIR / f"{spec.name}.json").write_text(
        artifact.model_dump_json(indent=2), encoding="utf-8"
    )
    logger.info("shipped promoted artifact %s", ARTIFACT_DIR / f"{spec.name}.joblib")
    return artifact.model_dump(mode="json")


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    observations = load_panel()
    cohorts = cohort_map()
    event_rows = [o for o in observations if cohorts.get(o.key.cik) == "event"]
    logger.info("panel %d rows, event cohort %d rows", len(observations), len(event_rows))

    summary: dict[str, Any] = {
        "question": "D-028 reasons (a) and (b): does boosting's lead survive the cohort "
        "confound, and is it a size effect?",
        "panel": "data/processed/phase8/observations_primary.csv",
        "pooled": _head_to_head(observations, "pooled (event + comparison cohorts)"),
        "within_event_cohort": _head_to_head(event_rows, "event cohort only"),
        "cohort_separability": _cohort_separability(observations, cohorts),
    }

    specs = _specs()
    summary["permutation_importance_within_event_cohort"] = {
        name: _permutation_importance(specs[name], event_rows)
        for name in ("boosting_full", "boosting_size_blind", "logistic_full")
    }
    summary["promoted_artifact"] = _ship_promoted_artifact(
        observations,
        {
            "pooled": summary["pooled"]["metrics"]["boosting_full"],
            "within_event_cohort": summary["within_event_cohort"]["metrics"]["boosting_full"],
            "cohort_separability": summary["cohort_separability"]["boosting_full"],
            "note": "every figure is walk-forward out-of-time; the shipped estimator is refit "
            "on all usable history, as a deployment would be",
        },
    )

    path = OUT_DIR / "primary_model_review.json"
    path.write_text(json.dumps(summary, indent=2))
    logger.info("wrote %s", path)

    for population in ("pooled", "within_event_cohort"):
        block = summary[population]
        if "metrics" not in block:
            continue
        logger.info("--- %s (%d events) ---", population, block["events"])
        for name, values in block["metrics"].items():
            logger.info("  %-22s ROC-AUC %s  PR-AUC %s", name, values["roc_auc"], values["pr_auc"])
        for key, values in block["paired_deltas"].items():
            logger.info(
                "  %-36s %+0.4f [%s, %s] excludes zero: %s",
                key,
                values["delta_roc_auc"] or 0.0,
                values["ci_low"],
                values["ci_high"],
                values["excludes_zero"],
            )


if __name__ == "__main__":
    main()
