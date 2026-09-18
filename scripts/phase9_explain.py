"""Phase 9: global drivers, explanation stability, and worked local examples.

Answers the phase's questions 2, 3, 4, 6 and 10 -- what drives the model,
whether those drivers trace to evidence, whether they are economically
plausible, whether they are stable, and what an analyst could safely be shown.

Three deliberate choices, each defended in `explain/`:

- **Grouped, not ranked.** Financial features are heavily correlated by
  construction, and every additive attribution splits a shared effect among
  correlated inputs arbitrarily. The headline is per-dimension; individual
  features appear only inside their group.
- **Out-of-fold attribution.** Explanations are computed from the model each
  walk-forward fold actually fitted, on rows that fold never saw. Attributing
  with a model fitted on everything would describe a model that never made a
  prediction anyone could have acted on.
- **One method per model family, chosen on merit.** Exact linear
  contributions for the logistic pipeline; TreeSHAP for the boosting
  challenger. See `adapters.py` for why SHAP is not used on the linear model.

    uv run python scripts/phase9_explain.py
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credit_risk_copilot.explain import attributor_for, explain_observation, group_of
from credit_risk_copilot.financials.history import resolve_company_history
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.model import (
    ModelSpec,
    build_model_specs,
    design_matrix,
    labels_array,
)
from credit_risk_copilot.modeling.splits import assert_temporal_ordering, walk_forward_folds
from credit_risk_copilot.sec_edgar import SecEdgarClient

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
OUT_DIR = Path("data/processed/phase9")
RAW_DIR = Path("data/raw")

PRIMARY_MODEL = "logistic_scale+levels+ratios+trends+signals+quality"
CHALLENGER_MODEL = "gradient_boosting_all"

#: Eras for temporal stability. Chosen from the panel's own fold structure
#: (2013-2019 test years) and the macro shape of the events -- a post-crisis
#: stretch, the 2015-16 energy default wave, and the late expansion -- rather
#: than by cutting the range into equal thirds.
ERAS: tuple[tuple[str, int, int], ...] = (
    ("2013-2014 post-crisis", 2013, 2014),
    ("2015-2016 energy wave", 2015, 2016),
    ("2017-2019 late expansion", 2017, 2019),
)


def load_panel(name: str = "primary") -> list[Observation]:
    frame = pd.read_csv(PHASE8_DIR / f"observations_{name}.csv")
    rows = frame.replace({np.nan: None}).to_dict("records")
    return [o for o in observations_from_rows(rows) if o.outcome.is_usable]


def out_of_fold_attributions(
    spec: ModelSpec, observations: list[Observation], plan: Any
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...], list[int]]:
    """Attribute every test row using the model its own fold fitted.

    Returns `(contributions, scores, feature_names, row_indices)`. Rows appear
    in fold order, each exactly once.
    """
    add_indicators = spec.family == "logistic"
    all_contributions: list[np.ndarray] = []
    all_scores: list[np.ndarray] = []
    all_indices: list[int] = []
    names: tuple[str, ...] = ()

    for fold in plan.folds:
        train = [observations[i] for i in fold.train_indices]
        test = [observations[i] for i in fold.test_indices]
        x_train, train_names = design_matrix(
            train, spec.feature_names, add_missing_indicators=add_indicators
        )
        x_test, _ = design_matrix(test, spec.feature_names, add_missing_indicators=add_indicators)
        if x_test.shape[1] != x_train.shape[1]:
            padding = np.zeros((x_test.shape[0], x_train.shape[1] - x_test.shape[1]))
            x_test = np.hstack([x_test, padding])

        y_train = labels_array(train)
        if len(np.unique(y_train)) < 2:
            continue
        assert spec.estimator_factory is not None
        estimator = spec.estimator_factory()
        estimator.fit(x_train, y_train)

        names = tuple(train_names)
        attributor = attributor_for(estimator, names)
        result = attributor.attribute(x_test)
        all_contributions.append(result.contributions)
        all_scores.append(estimator.predict_proba(x_test)[:, 1])
        all_indices.extend(fold.test_indices)

    return (
        np.vstack(all_contributions),
        np.concatenate(all_scores),
        names,
        all_indices,
    )


def group_attribution(
    contributions: np.ndarray, names: tuple[str, ...], *, axis: str = "dimension"
) -> pd.DataFrame:
    """Mean absolute contribution per group, plus mean signed contribution.

    Absolute share answers "how much of the model's movement does this group
    account for"; signed mean answers "in which direction does it usually
    push". Both are needed: a group can be large and directionally neutral.
    """
    groups = defaultdict(list)
    for column, name in enumerate(names):
        groups[group_of(name, axis=axis)].append(column)

    total = np.abs(contributions).sum()
    rows = []
    for group, columns in groups.items():
        block = contributions[:, columns]
        rows.append(
            {
                "group": group,
                "features": len(columns),
                "share_of_absolute": float(np.abs(block).sum() / total) if total else 0.0,
                "mean_absolute_per_row": float(np.abs(block).sum(axis=1).mean()),
                "mean_signed_per_row": float(block.sum(axis=1).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("share_of_absolute", ascending=False)


def feature_attribution(contributions: np.ndarray, names: tuple[str, ...]) -> pd.DataFrame:
    total = np.abs(contributions).sum()
    return (
        pd.DataFrame(
            {
                "feature": names,
                "group": [group_of(n) for n in names],
                "family": [group_of(n, axis="family") for n in names],
                "share_of_absolute": np.abs(contributions).sum(axis=0) / (total or 1.0),
                "mean_signed": contributions.mean(axis=0),
            }
        )
        .sort_values("share_of_absolute", ascending=False)
        .reset_index(drop=True)
    )


def era_stability(
    contributions: np.ndarray,
    names: tuple[str, ...],
    observations: list[Observation],
    indices: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group attribution within each era, and the rank correlation between them.

    A driver that only matters in one macro regime is not a general
    credit-risk driver, and a model whose grouped drivers reorder between eras
    should not have its global ranking quoted as if it were timeless.
    """
    years = np.array([observations[i].key.prediction_date.year for i in indices])
    per_era: list[pd.DataFrame] = []
    for label, first, last in ERAS:
        mask = (years >= first) & (years <= last)
        if mask.sum() < 50:
            continue
        frame = group_attribution(contributions[mask], names)
        frame.insert(0, "era", label)
        frame.insert(1, "rows", int(mask.sum()))
        per_era.append(frame)

    if not per_era:
        return pd.DataFrame(), pd.DataFrame()

    combined = pd.concat(per_era, ignore_index=True)
    wide = combined.pivot(index="group", columns="era", values="share_of_absolute").fillna(0.0)
    correlations = wide.corr(method="spearman")
    return combined, correlations.reset_index()


def _facts_for(observation: Observation, client: SecEdgarClient) -> dict[Any, Any]:
    """Re-resolve the exact `as_of` view an observation's features came from."""
    company_facts = json.loads(
        (RAW_DIR / "companyfacts" / f"CIK{observation.key.cik:010d}.json").read_text(
            encoding="utf-8"
        )
    )
    history = resolve_company_history(
        company_facts,
        client.annual_filings(observation.key.cik),
        cik=observation.key.cik,
        company=observation.key.company,
        filed_on_or_before=observation.key.prediction_date.isoformat(),
    )
    return history.financials.as_of(observation.key.prediction_date)


def local_examples(
    spec: ModelSpec,
    observations: list[Observation],
    plan: Any,
    contributions: np.ndarray,
    scores: np.ndarray,
    names: tuple[str, ...],
    indices: list[int],
    calibration_slope: float,
) -> list[dict[str, Any]]:
    """Full explanations, with provenance, for a few representative rows.

    Chosen to cover the cases an analyst would actually meet: the
    highest-ranked true event, the highest-ranked non-event (the costly false
    positive), and the lowest-ranked true event (the miss).
    """
    client = SecEdgarClient()
    labels = np.array([observations[i].outcome.label for i in indices])
    order = np.argsort(-scores)

    picks: dict[str, int] = {}
    events = [int(i) for i in order if labels[i] == 1]
    non_events = [int(i) for i in order if labels[i] == 0]
    if events:
        picks["highest_ranked_event"] = events[0]
        picks["lowest_ranked_event"] = events[-1]
    if non_events:
        picks["highest_ranked_non_event"] = non_events[0]

    percentiles = pd.Series(scores).rank(pct=True).to_numpy()
    add_indicators = spec.family == "logistic"
    examples: list[dict[str, Any]] = []

    for role, position in picks.items():
        observation = observations[indices[position]]
        try:
            facts = _facts_for(observation, client)
        except Exception as exc:  # noqa: BLE001 - a missing cache must not stop the report
            logger.warning("%s: could not re-resolve facts (%s)", observation.key.company, exc)
            continue

        single, _ = design_matrix(
            [observation], spec.feature_names, add_missing_indicators=add_indicators
        )
        from credit_risk_copilot.explain.adapters import AttributionResult

        attribution = AttributionResult(
            method="linear_contribution" if add_indicators else "tree_shap",
            feature_names=names,
            contributions=contributions[position : position + 1],
            baseline=0.0,
            values=single[:, : len(names)]
            if single.shape[1] >= len(names)
            else np.pad(
                single, ((0, 0), (0, len(names) - single.shape[1])), constant_values=np.nan
            ),
        )
        explanation = explain_observation(
            observation=observation,
            attribution=attribution,
            row=0,
            score=float(scores[position]),
            link_score=float(attribution.contributions[0].sum()),
            facts=facts,
            model_name=spec.name,
            model_family=spec.family,
            calibration_slope=calibration_slope,
            cohort_confounded=True,
            score_percentile=float(percentiles[position]),
        )
        examples.append(
            {"role": role, "label": int(labels[position]), **explanation.model_dump(mode="json")}
        )
        logger.info(
            "%s: %s (%s), score %.4f, pct %.1f%%, label %d, %d caveats",
            role,
            observation.key.company,
            observation.key.prediction_date,
            scores[position],
            100 * percentiles[position],
            labels[position],
            len(explanation.caveats),
        )
    return examples


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    observations = load_panel()
    plan = walk_forward_folds(observations)
    assert_temporal_ordering(observations, plan)
    logger.info(
        "Panel: %d usable rows, %d events, %d folds",
        len(observations),
        sum(1 for o in observations if o.outcome.label == 1),
        len(plan.folds),
    )

    model_summary = json.loads((PHASE8_DIR / "model_summary.json").read_text(encoding="utf-8"))
    calibration = {row["model"]: row.get("calibration_slope") for row in model_summary["results"]}

    specs = {spec.name: spec for spec in build_model_specs()}
    summary: dict[str, Any] = {"models": {}}

    for model_name in (PRIMARY_MODEL, CHALLENGER_MODEL):
        spec = specs[model_name]
        contributions, scores, names, indices = out_of_fold_attributions(spec, observations, plan)
        logger.info("%s: attributed %d rows over %d features", model_name, *contributions.shape)

        by_dimension = group_attribution(contributions, names)
        by_family = group_attribution(contributions, names, axis="family")
        by_feature = feature_attribution(contributions, names)
        era_frame, era_corr = era_stability(contributions, names, observations, indices)

        tag = "primary" if model_name == PRIMARY_MODEL else "challenger"
        by_dimension.to_csv(OUT_DIR / f"global_by_dimension_{tag}.csv", index=False)
        by_family.to_csv(OUT_DIR / f"global_by_family_{tag}.csv", index=False)
        by_feature.to_csv(OUT_DIR / f"global_by_feature_{tag}.csv", index=False)
        if not era_frame.empty:
            era_frame.to_csv(OUT_DIR / f"era_attribution_{tag}.csv", index=False)

        summary["models"][model_name] = {
            "attribution_method": "linear_contribution"
            if spec.family == "logistic"
            else "tree_shap",
            "rows_attributed": int(contributions.shape[0]),
            "features": int(contributions.shape[1]),
            "by_dimension": by_dimension.to_dict("records"),
            "by_family": by_family.to_dict("records"),
            "top_features": by_feature.head(15).to_dict("records"),
            "era_rank_correlation": (
                era_corr.set_index("era").to_dict() if not era_corr.empty else {}
            ),
        }

        if model_name == PRIMARY_MODEL:
            summary["local_examples"] = local_examples(
                spec,
                observations,
                plan,
                contributions,
                scores,
                names,
                indices,
                float(calibration.get(model_name) or 0.0),
            )

    # Do the two model families agree about what matters?
    primary = pd.DataFrame(summary["models"][PRIMARY_MODEL]["by_dimension"]).set_index("group")
    challenger = pd.DataFrame(summary["models"][CHALLENGER_MODEL]["by_dimension"]).set_index(
        "group"
    )
    joined = (
        primary[["share_of_absolute"]]
        .join(
            challenger[["share_of_absolute"]],
            lsuffix="_primary",
            rsuffix="_challenger",
            how="outer",
        )
        .fillna(0.0)
    )
    summary["model_agreement"] = {
        "spearman_on_dimension_shares": float(
            joined["share_of_absolute_primary"].corr(
                joined["share_of_absolute_challenger"], method="spearman"
            )
        ),
        "per_group": joined.reset_index().to_dict("records"),
    }
    joined.to_csv(OUT_DIR / "model_agreement_by_dimension.csv")

    (OUT_DIR / "explainability_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Model agreement: %s", json.dumps(summary["model_agreement"], indent=2))


if __name__ == "__main__":
    main()
