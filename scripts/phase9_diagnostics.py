"""Phase 9: is the model learning finance, or learning the sample?

Four investigations, each aimed at a specific way the Phase 8 numbers could be
right about the data and wrong about the world.

**1. Missingness (§13).** The global attribution shows the primary model
drawing ~44% of its total movement from `__missing` indicators. That is not
automatically wrong -- a filing that stops reporting cash flow is telling you
something -- but it is only legitimate if missingness carries information
beyond "this is an old, small filing". So: what is missing, for whom, when,
and does the model still work without it?

**2. Confounding (§14).** Cohort membership is one proxy; it is not the only
one. Anything the sampling design correlates with -- size, era, industry,
filing richness -- can stand in for the label. Each is probed by substituting
it for the label and asking how well the same features predict it.

**3. Data quality (§25).** Explaining individual predictions surfaced
definitionally impossible ratio values (a gross margin above 1 means revenue
resolved below gross profit). This quantifies them and measures what removing
them does.

**4. Error analysis (§21, §22).** Which observations does the model get wrong,
and can the errors be sorted into causes rather than listed?

    uv run python scripts/phase9_diagnostics.py
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
from credit_risk_copilot.modeling.features import FAMILY_ORDER, feature_names_for_families
from credit_risk_copilot.modeling.metrics import evaluate
from credit_risk_copilot.modeling.model import (
    ModelSpec,
    _logistic_pipeline,
    build_model_specs,
    design_matrix,
    labels_array,
    run_walk_forward,
)
from credit_risk_copilot.modeling.splits import assert_temporal_ordering, walk_forward_folds

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
OUT_DIR = Path("data/processed/phase9")

PRIMARY_MODEL = "logistic_scale+levels+ratios+trends+signals+quality"
CHALLENGER_MODEL = "gradient_boosting_all"

#: Minimum events for a subgroup to be scored at all. Below this the interval
#: is wider than any difference worth reporting, so the group is listed as
#: insufficient rather than given a misleading number (§28).
_MIN_SUBGROUP_EVENTS = 15

#: Ratios with a definitional ceiling. Gross margin is gross profit over
#: revenue: a value above 1 means revenue resolved *below* gross profit, which
#: no real company reports and which therefore indicates a resolution error
#: rather than an extreme business.
_IMPOSSIBLE_RULES: tuple[tuple[str, str, float], ...] = (
    ("ratio_gross_margin", "gross margin above 1 (revenue resolved below gross profit)", 1.0),
    ("ratio_operating_margin", "operating margin above 5 (500% of revenue)", 5.0),
    ("ratio_net_profit_margin", "net margin above 5 (500% of revenue)", 5.0),
)


def load_panel(name: str = "primary") -> tuple[list[Observation], pd.DataFrame]:
    frame = pd.read_csv(PHASE8_DIR / f"observations_{name}.csv")
    rows = frame.replace({np.nan: None}).to_dict("records")
    observations = [o for o in observations_from_rows(rows) if o.outcome.is_usable]
    usable = frame[frame["label"].notna()].reset_index(drop=True)
    return observations, usable


def _auc_for_alternative_label(
    observations: list[Observation], plan: Any, spec: ModelSpec, alt_labels: np.ndarray
) -> float | None:
    """Walk-forward AUC when the model is asked to predict something else.

    The probe behind §14: substitute a property of the *sampling design* for
    the bankruptcy label and keep everything else identical. A high score means
    the features carry that property, so any model trained on the real label
    inherits it for free.
    """
    add_indicators = spec.family == "logistic"
    scores: list[float] = []
    truth: list[int] = []
    for fold in plan.folds:
        train_idx, test_idx = list(fold.train_indices), list(fold.test_indices)
        y_train = alt_labels[train_idx]
        if len(np.unique(y_train)) < 2 or len(np.unique(alt_labels[test_idx])) < 2:
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
            padding = np.zeros((x_test.shape[0], len(train_names) - x_test.shape[1]))
            x_test = np.hstack([x_test, padding])
        assert spec.estimator_factory is not None
        estimator = spec.estimator_factory()
        estimator.fit(x_train, y_train)
        scores.extend(estimator.predict_proba(x_test)[:, 1].tolist())
        truth.extend(alt_labels[test_idx].tolist())

    if len(set(truth)) < 2:
        return None
    return float(roc_auc_score(truth, scores))


def missingness_analysis(
    observations: list[Observation], frame: pd.DataFrame, plan: Any, specs: dict[str, ModelSpec]
) -> dict[str, Any]:
    """What is missing, for whom -- and does the model still work without it?"""
    base_features = feature_names_for_families(FAMILY_ORDER)
    missing_matrix = frame[list(base_features)].isna()
    frame = frame.assign(
        missing_count=missing_matrix.sum(axis=1),
        year=pd.to_datetime(frame["prediction_date"]).dt.year,
    )

    # Does missingness track things other than distress?
    correlations = {
        "vs_log_total_assets": float(
            frame["missing_count"].corr(frame["log_total_assets"], method="spearman")
        ),
        "vs_prediction_year": float(frame["missing_count"].corr(frame["year"], method="spearman")),
        "vs_periods_available": float(
            frame["missing_count"].corr(frame["periods_available"], method="spearman")
        ),
        "vs_label": float(frame["missing_count"].corr(frame["label"], method="spearman")),
    }

    by_year = frame.groupby("year")["missing_count"].agg(["mean", "count"]).round(2).reset_index()
    by_label = frame.groupby("label")["missing_count"].agg(["mean", "median", "count"]).round(2)

    size_tercile = pd.qcut(frame["log_total_assets"], 3, labels=["small", "mid", "large"])
    by_size = (
        frame.groupby(size_tercile, observed=True)["missing_count"].agg(["mean", "count"]).round(2)
    )

    # The ablation that matters: same features, indicators withheld.
    primary = specs[PRIMARY_MODEL]
    with_indicators = _evaluate(primary, observations, plan, add_indicators=True)
    without_indicators = _evaluate(primary, observations, plan, add_indicators=False)

    return {
        "mean_missing_features_per_row": float(frame["missing_count"].mean()),
        "of_total_base_features": len(base_features),
        "correlations_spearman": correlations,
        "by_year": by_year.to_dict("records"),
        "by_label": by_label.reset_index().to_dict("records"),
        "by_size_tercile": by_size.reset_index().to_dict("records"),
        "most_missing_features": (
            missing_matrix.mean().sort_values(ascending=False).head(10).round(4).to_dict()
        ),
        "ablation": {
            "with_missingness_indicators": with_indicators,
            "without_missingness_indicators": without_indicators,
            "roc_auc_delta": (
                round(without_indicators["roc_auc"] - with_indicators["roc_auc"], 4)
                if with_indicators["roc_auc"] and without_indicators["roc_auc"]
                else None
            ),
        },
    }


def _evaluate(
    spec: ModelSpec, observations: list[Observation], plan: Any, *, add_indicators: bool
) -> dict[str, Any]:
    """Walk-forward evaluation with the indicator columns forced on or off."""
    scores: list[float] = []
    indices: list[int] = []
    for fold in plan.folds:
        train = [observations[i] for i in fold.train_indices]
        test = [observations[i] for i in fold.test_indices]
        x_train, train_names = design_matrix(
            train, spec.feature_names, add_missing_indicators=add_indicators
        )
        x_test, _ = design_matrix(test, spec.feature_names, add_missing_indicators=add_indicators)
        if x_test.shape[1] != len(train_names):
            padding = np.zeros((x_test.shape[0], len(train_names) - x_test.shape[1]))
            x_test = np.hstack([x_test, padding])
        y_train = labels_array(train)
        if len(np.unique(y_train)) < 2:
            continue
        estimator = _logistic_pipeline()
        estimator.fit(x_train, y_train)
        scores.extend(estimator.predict_proba(x_test)[:, 1].tolist())
        indices.extend(fold.test_indices)

    y = np.array([observations[i].outcome.label for i in indices], dtype=int)
    companies = np.array([observations[i].key.cik for i in indices])
    result = evaluate(y, np.array(scores), companies, bootstrap=False)
    return {
        "roc_auc": round(result.roc_auc, 4) if result.roc_auc else None,
        "pr_auc": round(result.pr_auc, 4) if result.pr_auc else None,
        "calibration_slope": (
            round(result.calibration_slope, 3) if result.calibration_slope else None
        ),
        "recall_at_10pct": round(result.alert_rates[-1].recall, 4),
        "n_features": len(
            design_matrix(
                observations[:2], spec.feature_names, add_missing_indicators=add_indicators
            )[1]
        ),
    }


#: Probes whose target is *defined from a feature the model is given* are
#: circular and their AUC means nothing: asking the model to identify large
#: companies while handing it `log_total_assets` is not a finding. Each such
#: probe therefore withholds the family that defines it, so the question
#: becomes the interesting one -- can the *rest* of the financial picture
#: recover this property?
_PROBE_EXCLUDED_FAMILIES: dict[str, tuple[str, ...]] = {
    "large_company_top_tercile": ("scale",),
    "data_rich_top_tercile": ("quality",),
}


def confound_probes(
    observations: list[Observation], frame: pd.DataFrame, plan: Any, specs: dict[str, ModelSpec]
) -> dict[str, Any]:
    """Can the features recover properties of the sampling design itself?"""
    manifest = json.loads((PHASE8_DIR / "corpus_manifest.json").read_text(encoding="utf-8"))
    cohort_of = {int(r["cik"]): r["cohort"] for r in manifest["companies"]}
    sic_of = {int(r["cik"]): int(r["sic"]) for r in manifest["companies"] if r.get("sic")}

    assets = frame["log_total_assets"].to_numpy()
    ciks = frame["cik"].to_numpy()

    # `early_era_*` is deliberately absent: walk-forward tests one year per
    # fold, so an era label is constant within every fold and the probe has no
    # variation to score. Temporal behaviour is measured by era-wise
    # attribution in `phase9_explain.py` instead.
    probes: dict[str, np.ndarray] = {
        "event_cohort_membership": np.array(
            [1 if cohort_of.get(int(c)) == "event" else 0 for c in ciks]
        ),
        "large_company_top_tercile": (assets >= np.nanquantile(assets, 2 / 3)).astype(int),
        "energy_sector_sic13": np.array(
            [1 if sic_of.get(int(c), 0) // 100 == 13 else 0 for c in ciks]
        ),
        "data_rich_top_tercile": (
            frame["fact_coverage"].to_numpy()
            >= np.nanquantile(frame["fact_coverage"].to_numpy(), 2 / 3)
        ).astype(int),
    }

    results: dict[str, Any] = {
        "note": "each row substitutes a sampling-design property for the bankruptcy label; "
        "everything else is identical. A high AUC means the features carry that property.",
        "reference_bankruptcy_auc": {},
    }
    for model_name in (PRIMARY_MODEL, CHALLENGER_MODEL):
        spec = specs[model_name]
        _, scores, _ = run_walk_forward(spec, observations, plan)
        indices, model_scores, _ = run_walk_forward(spec, observations, plan)
        y = np.array([observations[i].outcome.label for i in indices], dtype=int)
        results["reference_bankruptcy_auc"][model_name] = round(
            float(roc_auc_score(y, model_scores)), 4
        )
        del scores

    for probe_name, labels in probes.items():
        excluded = _PROBE_EXCLUDED_FAMILIES.get(probe_name, ())
        families = tuple(f for f in FAMILY_ORDER if f not in excluded)
        entry: dict[str, Any] = {
            "positive_rate": round(float(labels.mean()), 4),
            "withheld_feature_families": list(excluded),
            "note": (
                f"the {', '.join(excluded)} family defines this target and is withheld, so the "
                "score measures whether the rest of the financial picture recovers it"
            )
            if excluded
            else "target is independent of every feature",
        }
        for model_name in (PRIMARY_MODEL, CHALLENGER_MODEL):
            spec = specs[model_name]
            probe_spec = ModelSpec(
                name=f"{spec.name}::{probe_name}",
                family=spec.family,
                feature_families=families,
                configuration=spec.configuration,
                estimator_factory=spec.estimator_factory,
            )
            auc = _auc_for_alternative_label(observations, plan, probe_spec, labels)
            entry[model_name] = round(auc, 4) if auc is not None else None
        results[probe_name] = entry
    return results


def data_quality_analysis(frame: pd.DataFrame) -> dict[str, Any]:
    """Definitionally impossible values, and what removing them changes."""
    findings: list[dict[str, Any]] = []
    impossible = pd.Series(False, index=frame.index)
    for column, description, ceiling in _IMPOSSIBLE_RULES:
        flagged = frame[column] > ceiling
        impossible |= flagged.fillna(False)
        findings.append(
            {
                "rule": description,
                "column": column,
                "rows": int(flagged.sum()),
                "share_of_rows": round(float(flagged.mean()), 5),
                "companies": int(frame.loc[flagged.fillna(False), "cik"].nunique()),
                "worst_value": (
                    float(frame.loc[flagged.fillna(False), column].max()) if flagged.any() else None
                ),
            }
        )

    trend_columns = [c for c in frame.columns if c.startswith("trend_pct_")]
    extreme = (frame[trend_columns].abs() > 50).any(axis=1)

    return {
        "impossible_value_rules": findings,
        "rows_with_any_impossible_value": int(impossible.sum()),
        "companies_with_any_impossible_value": int(frame.loc[impossible, "cik"].nunique()),
        "trend_feature_extremes": {
            "note": "|percent_change| > 50 means a 5000%+ move; mathematically correct when a "
            "ratio's baseline is near zero, economically meaningless, and unbounded input to a "
            "standardised linear model.",
            "rows_with_any": int(extreme.sum()),
            "share_of_rows": round(float(extreme.mean()), 4),
            "widest_ranges": {
                column: {
                    "min": round(float(frame[column].min()), 1),
                    "max": round(float(frame[column].max()), 1),
                }
                for column in sorted(
                    trend_columns, key=lambda c: -float(frame[c].abs().max() or 0)
                )[:5]
            },
        },
    }


def error_analysis(
    observations: list[Observation], frame: pd.DataFrame, plan: Any, specs: dict[str, ModelSpec]
) -> dict[str, Any]:
    """Who the model flags wrongly, who it misses, and why -- by category."""
    spec = specs[PRIMARY_MODEL]
    indices, scores, _ = run_walk_forward(spec, observations, plan)
    labels = np.array([observations[i].outcome.label for i in indices], dtype=int)
    percentile = pd.Series(scores).rank(pct=True).to_numpy()

    rows: list[dict[str, Any]] = []
    for position, observation_index in enumerate(indices):
        observation = observations[observation_index]
        features = observation.features
        missing_base = sum(
            1 for name in feature_names_for_families(FAMILY_ORDER) if features.get(name) is None
        )
        rows.append(
            {
                "cik": observation.key.cik,
                "company": observation.key.company,
                "prediction_date": observation.key.prediction_date.isoformat(),
                "label": int(labels[position]),
                "score": float(scores[position]),
                "percentile": float(percentile[position]),
                "missing_features": missing_base,
                "periods_available": features.get("periods_available"),
                "fact_coverage": features.get("fact_coverage"),
                "log_total_assets": features.get("log_total_assets"),
                "negative_equity": features.get("signal_negative_equity"),
            }
        )
    errors = pd.DataFrame(rows)

    # A flag is "top decile"; a miss is an event outside it.
    errors["flagged"] = errors["percentile"] >= 0.90
    errors["category"] = errors.apply(_categorise, axis=1)
    errors.to_csv(OUT_DIR / "error_analysis.csv", index=False)

    false_positives = errors[(errors["label"] == 0) & errors["flagged"]]
    false_negatives = errors[(errors["label"] == 1) & ~errors["flagged"]]
    confident_errors = errors[
        ((errors["label"] == 0) & (errors["percentile"] >= 0.99))
        | ((errors["label"] == 1) & (errors["percentile"] <= 0.10))
    ]

    return {
        "flag_rule": "top decile of the pooled out-of-fold ranking",
        "counts": {
            "rows": len(errors),
            "events": int(errors["label"].sum()),
            "flagged": int(errors["flagged"].sum()),
            "true_positives": int(((errors["label"] == 1) & errors["flagged"]).sum()),
            "false_positives": len(false_positives),
            "false_negatives": len(false_negatives),
        },
        "taxonomy_counts": errors.groupby(["label", "category"])
        .size()
        .unstack(fill_value=0)
        .to_dict(),
        "false_negative_profile": {
            "mean_missing_features": round(float(false_negatives["missing_features"].mean()), 2),
            "mean_periods_available": round(float(false_negatives["periods_available"].mean()), 2),
            "mean_fact_coverage": round(float(false_negatives["fact_coverage"].mean()), 3),
        },
        "true_positive_profile": {
            "mean_missing_features": round(
                float(
                    errors[(errors["label"] == 1) & errors["flagged"]]["missing_features"].mean()
                ),
                2,
            ),
            "mean_periods_available": round(
                float(
                    errors[(errors["label"] == 1) & errors["flagged"]]["periods_available"].mean()
                ),
                2,
            ),
        },
        "confident_errors": confident_errors.nlargest(10, "percentile")[
            ["company", "prediction_date", "label", "score", "percentile", "category"]
        ].to_dict("records"),
    }


def _categorise(row: pd.Series) -> str:
    """A cause for one error, from evidence on the row itself.

    Rules are checked in order of how decisively they explain the outcome, and
    a row that matches none is `unexplained` rather than being forced into the
    nearest bucket -- an error taxonomy that always finds a category is not
    measuring anything.
    """
    if row["label"] == 1 and row["percentile"] < 0.90:
        if (row["missing_features"] or 0) >= 20:
            return "missed_data_sparse"
        if (row["periods_available"] or 0) < 3:
            return "missed_insufficient_history"
        if (row["fact_coverage"] or 1) < 0.7:
            return "missed_low_fact_coverage"
        return "missed_despite_complete_data"
    if row["label"] == 0 and row["percentile"] >= 0.90:
        if row["negative_equity"] == 1.0:
            return "flagged_negative_equity"
        if (row["missing_features"] or 0) >= 20:
            return "flagged_data_sparse"
        if (row["log_total_assets"] or 99) < 18:
            return "flagged_small_company"
        return "flagged_on_financials"
    return "correct_or_unflagged"


def redundancy_analysis(frame: pd.DataFrame) -> dict[str, Any]:
    """Why did the `signals` family add nothing to the ablation? (§17)

    Phase 8 measured `signals` at +0.007 ROC-AUC (not significant) on top of
    `trends`. The natural hypothesis is redundancy: a Phase 7 signal code fires
    *because* a ratio trend deteriorated, so once the trend is in the model the
    indicator restates it. This tests that directly -- how well can each signal
    be predicted from the trend features alone?

    A high score is not a criticism of Phase 7. A signal is a coarsening of the
    trend that raised it, so redundancy is the expected and correct
    relationship; it just means the signal is valuable as *explanation* rather
    than as additional evidence for a model.
    """
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    trend_columns = [c for c in frame.columns if c.startswith("trend_pct_")] + [
        "n_deteriorating_ratios",
        "n_improving_ratios",
        "max_deterioration_persistence",
        "n_unusual_movements",
    ]
    trend_columns = [c for c in trend_columns if c in frame.columns]
    x = frame[trend_columns].to_numpy(dtype=float)

    rows: list[dict[str, Any]] = []
    for column in [c for c in frame.columns if c.startswith("signal_")]:
        y = frame[column].fillna(0.0).to_numpy(dtype=float).astype(int)
        if len(np.unique(y)) < 2 or y.sum() < 20:
            rows.append({"signal": column, "positives": int(y.sum()), "auc_from_trends": None})
            continue
        pipeline = make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(),
            LogisticRegression(C=0.1, max_iter=2000),
        )
        scores = cross_val_score(pipeline, x, y, cv=4, scoring="roc_auc")
        rows.append(
            {
                "signal": column,
                "positives": int(y.sum()),
                "auc_from_trends": round(float(scores.mean()), 4),
            }
        )

    scored = [r for r in rows if r["auc_from_trends"] is not None]
    return {
        "note": "how well each Phase 7 signal is reconstructed from Phase 7 trend features "
        "alone; high values explain why the `signals` family added ~0 to the ablation",
        "trend_features_used": len(trend_columns),
        "per_signal": sorted(scored, key=lambda r: -r["auc_from_trends"]),
        "unscored_too_rare": [r["signal"] for r in rows if r["auc_from_trends"] is None],
        "median_auc": (
            round(float(np.median([r["auc_from_trends"] for r in scored])), 4) if scored else None
        ),
    }


def subgroup_analysis(
    observations: list[Observation], frame: pd.DataFrame, plan: Any, specs: dict[str, ModelSpec]
) -> dict[str, Any]:
    """Does the model behave differently by size and industry? (§28)

    Reported with event counts attached, because a subgroup AUC computed on
    four events is not a finding. Groups below `_MIN_SUBGROUP_EVENTS` are
    listed as insufficient rather than scored.
    """
    manifest = json.loads((PHASE8_DIR / "corpus_manifest.json").read_text(encoding="utf-8"))
    sic_of = {int(r["cik"]): int(r["sic"]) for r in manifest["companies"] if r.get("sic")}

    indices, scores, _ = run_walk_forward(specs[PRIMARY_MODEL], observations, plan)
    labels = np.array([observations[i].outcome.label for i in indices], dtype=int)
    assets = np.array([observations[i].features.get("log_total_assets") or np.nan for i in indices])
    sics = np.array([sic_of.get(observations[i].key.cik, 0) // 100 for i in indices])

    def _score(mask: np.ndarray, name: str) -> dict[str, Any]:
        events = int(labels[mask].sum())
        entry: dict[str, Any] = {"group": name, "rows": int(mask.sum()), "events": events}
        if events < _MIN_SUBGROUP_EVENTS or len(np.unique(labels[mask])) < 2:
            entry["roc_auc"] = None
            entry["note"] = f"fewer than {_MIN_SUBGROUP_EVENTS} events; not scored"
        else:
            entry["roc_auc"] = round(float(roc_auc_score(labels[mask], scores[mask])), 4)
            entry["event_rate"] = round(float(labels[mask].mean()), 4)
        return entry

    terciles = np.nanquantile(assets, [1 / 3, 2 / 3])
    by_size = [
        _score(assets < terciles[0], "small"),
        _score((assets >= terciles[0]) & (assets < terciles[1]), "mid"),
        _score(assets >= terciles[1], "large"),
    ]
    by_industry = [
        _score(sics == major, f"sic_{major:02d}")
        for major in sorted({int(s) for s in sics if s})
        if (sics == major).sum() >= 100
    ]
    return {
        "note": "pooled out-of-fold scores, split after the fact; subgroups with too few "
        "events are listed unscored rather than given a number",
        "by_size_tercile": by_size,
        "by_sic_major_group": sorted(
            [g for g in by_industry if g["roc_auc"] is not None],
            key=lambda g: -g["events"],
        ),
        "industries_too_few_events": [g["group"] for g in by_industry if g["roc_auc"] is None],
    }


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    observations, frame = load_panel()
    plan = walk_forward_folds(observations)
    assert_temporal_ordering(observations, plan)
    specs = {spec.name: spec for spec in build_model_specs()}

    logger.info("Missingness analysis...")
    missingness = missingness_analysis(observations, frame, plan, specs)
    logger.info("Confound probes...")
    confounds = confound_probes(observations, frame, plan, specs)
    logger.info("Data quality...")
    quality = data_quality_analysis(frame)
    logger.info("Error analysis...")
    errors = error_analysis(observations, frame, plan, specs)
    logger.info("Redundancy...")
    redundancy = redundancy_analysis(frame)
    logger.info("Subgroups...")
    subgroups = subgroup_analysis(observations, frame, plan, specs)

    summary = {
        "missingness": missingness,
        "confound_probes": confounds,
        "data_quality": quality,
        "errors": errors,
        "signal_redundancy": redundancy,
        "subgroups": subgroups,
    }
    (OUT_DIR / "diagnostics_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Missingness ablation: %s", json.dumps(missingness["ablation"], indent=2))
    logger.info("Confound probes: %s", json.dumps(confounds, indent=2))
    logger.info("Errors: %s", json.dumps(errors["counts"], indent=2))
    logger.info("Signal redundancy: %s", json.dumps(redundancy, indent=2))
    logger.info("Subgroups: %s", json.dumps(subgroups, indent=2))


if __name__ == "__main__":
    main()
