"""Phase 8 step 3: baselines, ablation, model comparison, robustness, artifact.

Runs every candidate in `modeling.model.build_model_specs()` through the same
walk-forward, out-of-time evaluation on the same panel, and reports:

- **Baselines** -- single-ratio heuristics and Phase 7's own deterioration
  count used directly as a score. If the learned models cannot beat these,
  the modelling layer is not earning its place.
- **Ablation** -- the six feature families stacked one at a time, which is the
  phase's real question: did Phases 6 and 7 create predictive information the
  raw facts did not already carry?
- **Alternative family** -- gradient boosting, on identical folds.
- **Robustness** -- held-out companies, cohort separability, per-year
  stability, leave-one-sector-out, and a longer horizon.

Every headline figure carries a company-clustered bootstrap interval, because
with this many events a 0.03 AUC difference is noise.

    uv run python scripts/phase8_train_evaluate.py
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.features import FAMILY_ORDER, SPECS_BY_NAME
from credit_risk_copilot.modeling.labels import load_event_table
from credit_risk_copilot.modeling.metrics import EvaluationResult, delta_auc_ci, evaluate
from credit_risk_copilot.modeling.model import (
    RANDOM_SEED,
    ModelArtifact,
    ModelSpec,
    build_model_specs,
    design_matrix,
    fit_final_model,
    labels_array,
    linear_coefficients,
    run_walk_forward,
    utc_now,
)
from credit_risk_copilot.modeling.splits import (
    FoldPlan,
    assert_temporal_ordering,
    fold_event_counts,
    held_out_company_folds,
    walk_forward_folds,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/processed/phase8")
CORPUS_MANIFEST = DATA_DIR / "corpus_manifest.json"
ARTIFACT_DIR = DATA_DIR / "artifacts"

#: The primary model reported as Phase 8's deliverable. Named here rather than
#: chosen by best score, because §23 is explicit that headline score is not the
#: selection criterion -- the choice is made in the report from the full table
#: (interpretability, calibration, stability), and this constant records it.
PRIMARY_MODEL = "logistic_scale+levels+ratios+trends+signals+quality"


def _load(name: str) -> tuple[Observation, ...]:
    frame = pd.read_csv(DATA_DIR / f"observations_{name}.csv")
    rows = frame.replace({np.nan: None}).to_dict("records")
    return observations_from_rows(rows)


def _usable(observations: tuple[Observation, ...]) -> list[Observation]:
    """Only rows with an observable outcome. Censored rows are never scored --
    they are not negatives, and including them would both inflate the row
    count and depress the apparent event rate."""
    return [obs for obs in observations if obs.outcome.is_usable]


def _evaluate_spec(
    spec: ModelSpec, observations: list[Observation], plan: FoldPlan, *, bootstrap: bool = True
) -> tuple[EvaluationResult | None, np.ndarray, np.ndarray]:
    indices, scores, _ = run_walk_forward(spec, observations, plan)
    if indices.size == 0:
        return None, indices, scores
    y = np.array([observations[i].outcome.label for i in indices], dtype=int)
    companies = np.array([observations[i].key.cik for i in indices])
    return evaluate(y, scores, companies, bootstrap=bootstrap), indices, scores


def _result_row(spec: ModelSpec, result: EvaluationResult) -> dict[str, Any]:
    row: dict[str, Any] = {
        "model": spec.name,
        "family": spec.family,
        "feature_families": "+".join(spec.feature_families),
        "n_features": len(spec.feature_names),
        "n_rows": result.n_rows,
        "n_events": result.n_events,
        "event_rate": round(result.event_rate, 5),
        "roc_auc": round(result.roc_auc, 4) if result.roc_auc is not None else None,
        "roc_auc_lo": round(result.roc_auc_ci[0], 4) if result.roc_auc_ci else None,
        "roc_auc_hi": round(result.roc_auc_ci[1], 4) if result.roc_auc_ci else None,
        "pr_auc": round(result.pr_auc, 4) if result.pr_auc is not None else None,
        "pr_auc_baseline": round(result.pr_auc_baseline, 4),
        "brier": round(result.brier, 5) if result.brier is not None else None,
        "calibration_slope": (
            round(result.calibration_slope, 3) if result.calibration_slope is not None else None
        ),
    }
    for alert in result.alert_rates:
        tag = f"{int(alert.alert_rate * 100)}pct"
        row[f"recall_at_{tag}"] = round(alert.recall, 4)
        row[f"precision_at_{tag}"] = round(alert.precision, 4)
    return row


def _missingness(observations: list[Observation]) -> dict[str, Any]:
    """How much of each feature family is actually observed.

    Reported because it bounds how the model families can be compared: the
    logistic pipeline median-imputes every gap (and flags it), while the
    gradient-boosting model consumes `NaN` directly. If missingness is heavy,
    a difference between them is as likely to be about missing-data handling
    as about linearity.
    """
    by_family: dict[str, list[float]] = {}
    per_feature: list[dict[str, Any]] = []
    for name, spec in SPECS_BY_NAME.items():
        missing = sum(1 for obs in observations if obs.features.get(name) is None)
        rate = missing / len(observations) if observations else 0.0
        by_family.setdefault(spec.family, []).append(rate)
        per_feature.append({"feature": name, "family": spec.family, "missing_rate": round(rate, 4)})
    return {
        "by_family_mean_missing_rate": {
            family: round(sum(rates) / len(rates), 4) for family, rates in sorted(by_family.items())
        },
        "most_missing_features": sorted(per_feature, key=lambda r: -float(r["missing_rate"]))[:10],
    }


def _cohort_separability(
    observations: list[Observation], plan: FoldPlan, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Can a model tell the two cohorts apart *without* being asked about bankruptcy?

    The comparison cohort was drawn from SEC's current ticker file, so every
    company in it survived to today by construction, while the event cohort is
    selected on having failed. If the two are separable on features alone, any
    event model inherits that separation for free and part of its apparent
    discrimination is survivorship, not credit risk.

    This substitutes cohort membership for the label, changes nothing else,
    and reports the AUC. It is a diagnostic, not a model: a high number does
    not invalidate the event results, but it does bound how much of them can
    be attributed to genuine risk discrimination.
    """
    cohort_of = {int(record["cik"]): record["cohort"] for record in manifest["companies"]}
    # `Outcome` refuses a positive without an event date, and rightly so -- the
    # probe must not fabricate one. Every event-cohort company has a real BRD
    # petition date, so the relabelled positive carries it; what changes is
    # only *which rows* are positive (all of an event company's rows, not just
    # those inside a horizon), which is exactly the cohort question.
    events = load_event_table(Path("data/raw/brd/cases.csv"))
    relabelled: list[Observation] = []
    for observation in observations:
        cohort = cohort_of.get(observation.key.cik)
        if cohort is None:
            continue
        cases = events.cases(observation.key.cik)
        if cohort == "event" and not cases:
            continue
        is_event_cohort = cohort == "event"
        relabelled.append(
            Observation(
                key=observation.key,
                features=observation.features,
                outcome=observation.outcome.model_copy(
                    update={
                        "label": 1 if is_event_cohort else 0,
                        "event_date": cases[0].filed if is_event_cohort else None,
                        "days_to_event": None,
                        "censoring_reason": None,
                    }
                ),
            )
        )
    if len({obs.outcome.label for obs in relabelled}) < 2:
        return {}

    cohort_plan = walk_forward_folds(relabelled, min_train_events=20)
    results: dict[str, Any] = {
        "note": "label replaced by cohort membership; higher AUC means the sampling design "
        "itself is learnable",
        "event_cohort_rows": sum(1 for obs in relabelled if obs.outcome.label == 1),
        "comparison_cohort_rows": sum(1 for obs in relabelled if obs.outcome.label == 0),
    }
    for name in (PRIMARY_MODEL, "gradient_boosting_all"):
        spec = next(s for s in build_model_specs() if s.name == name)
        result, _, _ = _evaluate_spec(spec, relabelled, cohort_plan, bootstrap=False)
        results[name] = round(result.roc_auc, 4) if result and result.roc_auc else None
    return results


def _within_event_cohort(
    observations: list[Observation], manifest: dict[str, Any]
) -> dict[str, Any]:
    """Discrimination with the cohort confound removed entirely.

    If `cohort_separability` is high, the pooled AUC is partly the model
    recognising *which sample a company was drawn from* rather than *when it
    is about to fail*. This restricts both training and testing to the event
    cohort, where every company eventually files: the positives are the rows
    inside a petition's horizon and the negatives are the same companies'
    earlier rows. Cohort membership is then constant and carries no
    information, so whatever discrimination remains is timing.

    This is the harder and more honest question for a monitoring product,
    which watches companies it already considers risky. A large drop from the
    pooled figure is the measurement of how much of that figure was sampling
    design.
    """
    cohort_of = {int(record["cik"]): record["cohort"] for record in manifest["companies"]}
    subset = [
        observation for observation in observations if cohort_of.get(observation.key.cik) == "event"
    ]
    if not subset:
        return {}
    plan = walk_forward_folds(subset, min_train_events=20)
    if not plan.folds:
        return {"note": "too few event-cohort rows to form a fold"}
    assert_temporal_ordering(subset, plan)

    results: dict[str, Any] = {
        "note": "event cohort only; cohort membership is constant, so this isolates timing",
        "rows": len(subset),
        "events": sum(1 for obs in subset if obs.outcome.label == 1),
        "companies": len({obs.key.cik for obs in subset}),
        "folds": len(plan.folds),
    }
    specs = {spec.name: spec for spec in build_model_specs()}
    for name in (
        "heuristic_leverage",
        "heuristic_phase7_deterioration",
        PRIMARY_MODEL,
        "gradient_boosting_all",
    ):
        result, _, _ = _evaluate_spec(specs[name], subset, plan, bootstrap=False)
        results[name] = {
            "roc_auc": round(result.roc_auc, 4) if result and result.roc_auc else None,
            "pr_auc": round(result.pr_auc, 4) if result and result.pr_auc else None,
            "event_rate": round(result.event_rate, 4) if result else None,
        }
    return results


def _permutation_importance(
    spec: ModelSpec, observations: list[Observation], top_n: int = 15
) -> list[dict[str, Any]]:
    """Which features a fitted model actually leans on.

    Kept to the simplest technique that answers the question (§22): permuting
    one feature and measuring the ROC-AUC it costs. Phase 9 owns anything
    beyond this, which is why `shap` -- installed with the `ml` extra -- is
    deliberately unused in Phase 8.

    Measured on the final model over the whole panel, so it describes what the
    shipped artifact relies on, not an out-of-sample effect. It is a
    diagnostic for reading the model, not a performance claim.
    """
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
    return [
        {
            "feature": names[int(i)],
            "family": (
                SPECS_BY_NAME[names[int(i)]].family
                if names[int(i)] in SPECS_BY_NAME
                else "missing_indicator"
            ),
            "auc_drop": round(float(result.importances_mean[int(i)]), 5),
            "std": round(float(result.importances_std[int(i)]), 5),
        }
        for i in order
    ]


def _sector_of(manifest: dict[str, Any]) -> dict[int, int]:
    """CIK -> two-digit SIC major group, for leave-one-sector-out."""
    return {
        int(record["cik"]): int(record["sic"]) // 100
        for record in manifest["companies"]
        if record.get("sic")
    }


def main() -> None:
    configure_logging()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))

    observations = _usable(_load("primary"))
    logger.info(
        "Panel: %d usable rows, %d events (%.2f%%), %d companies",
        len(observations),
        sum(1 for o in observations if o.outcome.label == 1),
        100 * sum(1 for o in observations if o.outcome.label == 1) / max(1, len(observations)),
        len({o.key.cik for o in observations}),
    )

    plan = walk_forward_folds(observations)
    assert_temporal_ordering(observations, plan)
    fold_table = fold_event_counts(observations, plan)
    logger.info("Folds:\n%s", pd.DataFrame(fold_table).to_string(index=False))

    specs = build_model_specs()
    rows: list[dict[str, Any]] = []
    scores_by_model: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for spec in specs:
        result, indices, scores = _evaluate_spec(spec, observations, plan)
        if result is None:
            logger.warning("%s: no fold produced predictions", spec.name)
            continue
        scores_by_model[spec.name] = (indices, scores)
        rows.append(_result_row(spec, result))
        logger.info("%-52s %s", spec.name, result.headline())

    results = pd.DataFrame(rows)
    results.to_csv(DATA_DIR / "model_results.csv", index=False)

    summary: dict[str, Any] = {
        "panel": {
            "usable_rows": len(observations),
            "events": sum(1 for o in observations if o.outcome.label == 1),
            "companies": len({o.key.cik for o in observations}),
            "companies_with_events": len({o.key.cik for o in observations if o.outcome.label == 1}),
            "prediction_years": sorted({o.key.prediction_date.year for o in observations}),
        },
        "folds": fold_table,
        "results": rows,
    }

    summary["missingness"] = _missingness(observations)
    summary["incremental_value"] = _ablation_deltas(observations, scores_by_model)
    summary["robustness"] = _robustness(observations, plan, manifest, scores_by_model)
    specs_by_name = {spec.name: spec for spec in specs}
    summary["permutation_importance"] = {
        name: _permutation_importance(specs_by_name[name], observations)
        for name in (PRIMARY_MODEL, "gradient_boosting_all")
        if name in specs_by_name
    }
    summary["primary_model"] = _fit_and_save_artifact(
        specs, observations, plan, rows, summary["panel"]
    )

    (DATA_DIR / "model_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Results table:\n%s", results.to_string(index=False))
    logger.info("Incremental value:\n%s", json.dumps(summary["incremental_value"], indent=2))
    logger.info("Robustness:\n%s", json.dumps(summary["robustness"], indent=2, default=str))


def _ablation_deltas(
    observations: list[Observation], scores_by_model: dict[str, tuple[np.ndarray, np.ndarray]]
) -> list[dict[str, Any]]:
    """Paired bootstrap AUC deltas for each rung of the ablation ladder.

    Paired, not two separate intervals: both models score identical rows, so
    the difference has far less variance than either level, and comparing
    overlapping CIs would be the wrong (and over-conservative) test.
    """
    deltas: list[dict[str, Any]] = []
    ladder = [f"logistic_{'+'.join(FAMILY_ORDER[:n])}" for n in range(1, len(FAMILY_ORDER) + 1)]
    for previous, current in zip(ladder, ladder[1:], strict=False):
        if previous not in scores_by_model or current not in scores_by_model:
            continue
        indices_a, scores_a = scores_by_model[previous]
        indices_b, scores_b = scores_by_model[current]
        if not np.array_equal(indices_a, indices_b):
            continue
        y = np.array([observations[i].outcome.label for i in indices_a], dtype=int)
        companies = np.array([observations[i].key.cik for i in indices_a])
        interval = delta_auc_ci(y, scores_a, scores_b, companies)
        if interval is None:
            continue
        point, low, high = interval
        deltas.append(
            {
                "added_family": FAMILY_ORDER[ladder.index(current)],
                "from": previous,
                "to": current,
                "delta_roc_auc": round(point, 4),
                "ci_low": round(low, 4),
                "ci_high": round(high, 4),
                "significant": bool(low > 0 or high < 0),
            }
        )
    return deltas


def _robustness(
    observations: list[Observation],
    plan: FoldPlan,
    manifest: dict[str, Any],
    scores_by_model: dict[str, tuple[np.ndarray, np.ndarray]],
) -> dict[str, Any]:
    """Four checks on whether the headline result depends on something fragile."""
    specs = {spec.name: spec for spec in build_model_specs()}
    primary = specs[PRIMARY_MODEL]
    checks: dict[str, Any] = {}

    # 1. Held-out companies: is the model memorising companies rather than
    #    learning financial distress?
    for name in (PRIMARY_MODEL, "gradient_boosting_all"):
        held_out_plan = held_out_company_folds(observations, plan)
        assert_temporal_ordering(observations, held_out_plan)
        held_out, _, _ = _evaluate_spec(specs[name], observations, held_out_plan)
        checks[f"held_out_companies::{name}"] = (
            {
                "roc_auc": round(held_out.roc_auc, 4) if held_out.roc_auc else None,
                "n_rows": held_out.n_rows,
                "n_events": held_out.n_events,
                "train_rows_first_fold": held_out_plan.folds[0].train_size
                if held_out_plan.folds
                else 0,
            }
            if held_out
            else None
        )

    # 2. Cohort separability: can a model tell an event-cohort company from a
    #    comparison-cohort one *without* being asked about bankruptcy? A high
    #    score here means the two cohorts differ for reasons beyond credit
    #    risk (survivorship in the comparison sample), and any event model
    #    inherits that separation for free.
    checks["cohort_separability"] = _cohort_separability(observations, plan, manifest)

    # 3. The same question with the confound removed: within the event cohort,
    #    can the model tell the year before failure from earlier years?
    checks["within_event_cohort"] = _within_event_cohort(observations, manifest)

    # 2. Per-year stability: is one year carrying the whole result?
    indices, scores = scores_by_model.get(PRIMARY_MODEL, (np.array([]), np.array([])))
    per_year: list[dict[str, Any]] = []
    if indices.size:
        years = np.array([observations[i].key.prediction_date.year for i in indices])
        y = np.array([observations[i].outcome.label for i in indices], dtype=int)
        companies = np.array([observations[i].key.cik for i in indices])
        for year in sorted(set(years.tolist())):
            mask = years == year
            if len(np.unique(y[mask])) < 2:
                continue
            result = evaluate(y[mask], scores[mask], companies[mask], bootstrap=False)
            per_year.append(
                {
                    "year": int(year),
                    "rows": result.n_rows,
                    "events": result.n_events,
                    "roc_auc": round(result.roc_auc, 4) if result.roc_auc else None,
                }
            )
        checks["per_year"] = per_year

        # 3. Drop the single most influential year and re-measure.
        if per_year:
            worst = min(per_year, key=lambda r: r["roc_auc"] or 1.0)["year"]
            best = max(per_year, key=lambda r: r["roc_auc"] or 0.0)["year"]
            for label, dropped in (("without_best_year", best), ("without_worst_year", worst)):
                mask = years != dropped
                if len(np.unique(y[mask])) < 2:
                    continue
                result = evaluate(y[mask], scores[mask], companies[mask], bootstrap=False)
                checks[label] = {
                    "dropped_year": int(dropped),
                    "roc_auc": round(result.roc_auc, 4) if result.roc_auc else None,
                }

        # 4. Leave-one-sector-out: is the result a single industry's story?
        sectors = _sector_of(manifest)
        row_sectors = np.array([sectors.get(observations[i].key.cik, -1) for i in indices])
        counts = Counter(row_sectors[y == 1].tolist())
        sector_rows: list[dict[str, Any]] = []
        for sector, event_count in counts.most_common(5):
            if sector == -1:
                continue
            mask = row_sectors != sector
            if len(np.unique(y[mask])) < 2:
                continue
            result = evaluate(y[mask], scores[mask], companies[mask], bootstrap=False)
            sector_rows.append(
                {
                    "excluded_sic_major_group": int(sector),
                    "events_excluded": int(event_count),
                    "roc_auc_without": round(result.roc_auc, 4) if result.roc_auc else None,
                }
            )
        checks["leave_one_sector_out"] = sector_rows

    # 5. The longer horizon, as its own panel.
    robustness_observations = _usable(_load("robustness"))
    if robustness_observations:
        long_plan = walk_forward_folds(robustness_observations)
        assert_temporal_ordering(robustness_observations, long_plan)
        long_result, _, _ = _evaluate_spec(
            primary, robustness_observations, long_plan, bootstrap=False
        )
        checks["horizon_730d"] = (
            {
                "roc_auc": round(long_result.roc_auc, 4) if long_result.roc_auc else None,
                "n_rows": long_result.n_rows,
                "n_events": long_result.n_events,
                "event_rate": round(long_result.event_rate, 5),
            }
            if long_result
            else None
        )

    return checks


def _fit_and_save_artifact(
    specs: tuple[ModelSpec, ...],
    observations: list[Observation],
    plan: FoldPlan,
    rows: list[dict[str, Any]],
    panel_summary: dict[str, Any],
) -> dict[str, Any]:
    """Fit the chosen model on all usable history and persist it with metadata."""
    spec = next(s for s in specs if s.name == PRIMARY_MODEL)
    estimator, names = fit_final_model(spec, observations)
    coefficients = linear_coefficients(estimator, names)
    metrics = next((row for row in rows if row["model"] == spec.name), {})

    dates = sorted(obs.key.prediction_date for obs in observations)
    artifact = ModelArtifact(
        name=spec.name,
        family=spec.family,
        created_utc=utc_now(),
        feature_families=spec.feature_families,
        feature_names=tuple(names),
        configuration=spec.configuration,
        random_seed=RANDOM_SEED,
        target_definition={
            "event": "BRD-recorded Chapter 7/11 petition",
            "horizon_days": 365,
            "observation_unit": "one company per annual filing, at the filing receipt date",
            "censoring": "rows whose window exceeds label completeness, or that sit inside an "
            "active proceeding, are excluded",
        },
        dataset_summary=panel_summary,
        training_period=(dates[0].isoformat(), dates[-1].isoformat()),
        evaluation_strategy=f"{plan.strategy} ({len(plan.folds)} folds)",
        metrics=metrics,
        coefficients=coefficients,
        intercept=(
            float(estimator.named_steps["model"].intercept_[0])
            if hasattr(estimator, "named_steps")
            else None
        ),
    )
    joblib.dump(estimator, ARTIFACT_DIR / f"{spec.name}.joblib")
    (ARTIFACT_DIR / f"{spec.name}.json").write_text(
        artifact.model_dump_json(indent=2), encoding="utf-8"
    )

    if coefficients:
        ranked = sorted(coefficients.items(), key=lambda kv: -abs(kv[1]))[:15]
        logger.info(
            "Top standardised coefficients:\n%s",
            "\n".join(f"  {name:<44} {value:+.4f}" for name, value in ranked),
        )
    return artifact.model_dump(mode="json")


if __name__ == "__main__":
    main()
