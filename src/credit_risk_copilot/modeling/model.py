"""The estimators, the walk-forward runner, and the model artifact.

## The formulation, and why it is this one

Each row is one company at one filing date, asked whether the modelled event
occurs in the following horizon. Stacked across companies and years that is a
**discrete-time hazard model**: the panel is in person-period form, each row
is one at-risk interval, censored intervals are excluded rather than scored,
and the conditional hazard is estimated by a binary classifier over the
intervals. Fitting a logistic regression to that panel is the standard
multi-period bankruptcy hazard specification (Shumway's correction to the
single-snapshot Altman-style discriminant), and it is not a reinterpretation
of the data to make classification convenient -- it is what the data is.

Three consequences follow, and each is why a plain "classify the company"
framing was rejected:

- **Censoring is first class.** A row whose forward window is not fully
  observable is dropped by `labels.py`, not labelled negative. A snapshot
  classifier has nowhere to put such a row.
- **A company contributes many rows, not one.** Using only each company's
  final pre-event filing would discard the years of survival that identify
  the baseline hazard, and would build a dataset in which every bankrupt
  company is represented only at its worst.
- **The output is a conditional one-period hazard**, so it is directly
  comparable across companies and years, which is what a watchlist ranking
  needs.

## Estimators

Three families, chosen to answer different questions rather than to fill a
leaderboard:

- `heuristic` -- no fitting at all. A single ratio, or Phase 7's own
  deterioration count, used directly as a score. These are the baselines that
  decide whether the modelling layer earns its existence (§18).
- `logistic` -- L2-regularised logistic regression on standardised features
  with median imputation and missingness indicators. The primary candidate:
  interpretable coefficients, probabilities that mean something, and the
  specification the hazard framing implies.
- `gradient_boosting` -- `HistGradientBoostingClassifier`, which handles
  missing values natively and non-linear interactions. Included as the
  serious alternative, not as an upgrade: with a few hundred events it is the
  model most likely to overfit, and the comparison is the point.

No hyperparameter sweep (§24). Each estimator gets one deliberately
conservative configuration, chosen for the sample size and stated in
`ModelSpec.configuration`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.features import FAMILY_ORDER, feature_names_for_families
from credit_risk_copilot.modeling.splits import FoldPlan

RANDOM_SEED = 20260917


@dataclass(frozen=True)
class ModelSpec:
    """One candidate: what it is trained on and how it is built."""

    name: str
    family: str
    feature_families: tuple[str, ...]
    configuration: dict[str, Any]
    #: `None` for heuristics, which are not fitted.
    estimator_factory: Callable[[], Any] | None = None
    #: `heuristic` only: which feature to rank on, and whether higher is riskier.
    heuristic_feature: str | None = None
    heuristic_higher_is_riskier: bool = True

    @property
    def feature_names(self) -> tuple[str, ...]:
        return feature_names_for_families(self.feature_families)


def _logistic_pipeline(c: float = 0.1) -> Pipeline:
    """Median imputation -> standardisation -> L2 logistic.

    L2 is sklearn's default penalty, so it is not passed explicitly (the
    `penalty=` argument was deprecated in sklearn 1.8).

    `C=0.1` (i.e. fairly strong shrinkage) is set from the sample size, not
    tuned: with tens of features and a low hundreds of events, the
    events-per-variable ratio is well under the conventional 10, and an
    unregularised fit would produce large, unstable coefficients that look
    like findings. Imputation is *inside* the pipeline so it is refit on each
    fold's training rows only -- imputing on the full panel would leak the
    future's medians into the past.
    """
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=c,
                    solver="lbfgs",
                    max_iter=5000,
                    random_state=RANDOM_SEED,
                ),
            ),
        ]
    )


def _gradient_boosting() -> HistGradientBoostingClassifier:
    """Deliberately small trees and heavy leaf regularisation.

    Defaults would grow 31-leaf trees for 255 iterations on a few thousand
    rows with a hundred-odd events, which memorises. `max_leaf_nodes=4`,
    `min_samples_leaf=40` and `max_iter=150` with early stopping keep the
    model closer in capacity to the logistic baseline, which is the only way
    the comparison says anything about the data rather than about capacity.
    NaNs are passed through untouched: native missing handling is the reason
    this family is in the comparison at all.
    """
    return HistGradientBoostingClassifier(
        max_leaf_nodes=4,
        min_samples_leaf=40,
        max_iter=150,
        learning_rate=0.05,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.2,
        random_state=RANDOM_SEED,
    )


def build_model_specs() -> tuple[ModelSpec, ...]:
    """The candidate set: baselines, the ablation ladder, and the alternative."""
    specs: list[ModelSpec] = [
        ModelSpec(
            name="heuristic_leverage",
            family="heuristic",
            feature_families=("ratios",),
            configuration={"rule": "rank by debt_to_assets, higher is riskier"},
            heuristic_feature="ratio_debt_to_assets",
        ),
        ModelSpec(
            name="heuristic_working_capital",
            family="heuristic",
            feature_families=("levels",),
            configuration={"rule": "rank by working_capital_to_assets, lower is riskier"},
            heuristic_feature="working_capital_to_assets",
            heuristic_higher_is_riskier=False,
        ),
        ModelSpec(
            name="heuristic_ebit_to_assets",
            family="heuristic",
            feature_families=("levels",),
            configuration={"rule": "rank by ebit_to_assets, lower is riskier"},
            heuristic_feature="ebit_to_assets",
            heuristic_higher_is_riskier=False,
        ),
        ModelSpec(
            name="heuristic_phase7_deterioration",
            family="heuristic",
            feature_families=("trends",),
            configuration={
                "rule": "rank by Phase 7 n_deteriorating_ratios, higher is riskier -- the "
                "existing product's own output used directly as a score"
            },
            heuristic_feature="n_deteriorating_ratios",
        ),
    ]

    for depth in range(1, len(FAMILY_ORDER) + 1):
        families = FAMILY_ORDER[:depth]
        specs.append(
            ModelSpec(
                name=f"logistic_{'+'.join(families)}",
                family="logistic",
                feature_families=families,
                configuration={"penalty": "l2", "C": 0.1, "imputation": "median+indicators"},
                estimator_factory=_logistic_pipeline,
            )
        )

    # Sensitivity, not a sweep. `C=0.1` is the pre-specified primary; this
    # weaker-shrinkage variant exists only to tell two explanations apart if
    # the logistic models underperform the single-ratio baselines -- "the
    # penalty is crippling the fit" versus "this many features cannot beat one
    # good ratio at this event count". Choosing between the two *on the
    # out-of-fold score* would be selection on the evaluation set, so the
    # primary stays the pre-specified one whatever this reports.
    specs.append(
        ModelSpec(
            name="logistic_all_weak_penalty",
            family="logistic",
            feature_families=FAMILY_ORDER,
            configuration={
                "penalty": "l2",
                "C": 1.0,
                "imputation": "median+indicators",
                "role": "sensitivity analysis on the penalty, not a candidate for selection",
            },
            estimator_factory=lambda: _logistic_pipeline(1.0),
        )
    )

    specs.append(
        ModelSpec(
            name="gradient_boosting_all",
            family="gradient_boosting",
            feature_families=FAMILY_ORDER,
            configuration={
                "max_leaf_nodes": 4,
                "min_samples_leaf": 40,
                "max_iter": 150,
                "missing": "native",
            },
            estimator_factory=_gradient_boosting,
        )
    )
    return tuple(specs)


def design_matrix(
    observations: Sequence[Observation],
    feature_names: Sequence[str],
    *,
    add_missing_indicators: bool,
) -> tuple[np.ndarray, list[str]]:
    """Features as a float array, `None` becoming `np.nan`.

    When `add_missing_indicators` is set, every feature that is missing for at
    least one row gains a companion `<name>__missing` column. This is what
    keeps "we could not compute leverage" distinguishable from "leverage
    happens to equal the median" after imputation -- without it, imputation
    silently asserts the company is typical (§15).
    """
    base = np.array(
        [
            [
                np.nan if observation.features.get(name) is None else observation.features[name]
                for name in feature_names
            ]
            for observation in observations
        ],
        dtype=float,
    )
    names = list(feature_names)
    if not add_missing_indicators or base.size == 0:
        return base, names

    missing = np.isnan(base)
    informative = np.flatnonzero(missing.any(axis=0))
    if informative.size == 0:
        return base, names
    indicators = missing[:, informative].astype(float)
    names.extend(f"{feature_names[int(i)]}__missing" for i in informative)
    return np.hstack([base, indicators]), names


def labels_array(observations: Sequence[Observation]) -> np.ndarray:
    return np.array([obs.outcome.label for obs in observations], dtype=int)


class FoldPrediction(BaseModel):
    """Out-of-fold scores for one fold."""

    model_config = ConfigDict(frozen=True)

    fold_name: str
    test_year: int
    indices: tuple[int, ...]
    scores: tuple[float, ...]


def run_walk_forward(
    spec: ModelSpec, observations: Sequence[Observation], plan: FoldPlan
) -> tuple[np.ndarray, np.ndarray, list[FoldPrediction]]:
    """Fit `spec` on each fold's training rows and score its test rows.

    Returns pooled `(indices, scores, per-fold predictions)`. Nothing is fitted
    on a row it later scores, and nothing is fitted on a row dated at or after
    any row it scores -- `splits.assert_temporal_ordering` checks the second
    claim independently of this function.
    """
    add_indicators = spec.family == "logistic"
    all_indices: list[int] = []
    all_scores: list[float] = []
    per_fold: list[FoldPrediction] = []

    for fold in plan.folds:
        test_observations = [observations[i] for i in fold.test_indices]

        if spec.family == "heuristic":
            scores = _heuristic_scores(spec, test_observations)
        else:
            train_observations = [observations[i] for i in fold.train_indices]
            x_train, _ = design_matrix(
                train_observations, spec.feature_names, add_missing_indicators=add_indicators
            )
            x_test, _ = design_matrix(
                test_observations, spec.feature_names, add_missing_indicators=add_indicators
            )
            # An indicator column exists only when the *training* rows had a
            # missing value there, so the two matrices can disagree in width.
            x_test = _align_columns(x_test, x_train.shape[1])
            y_train = labels_array(train_observations)
            if len(np.unique(y_train)) < 2:
                continue
            assert spec.estimator_factory is not None
            estimator = spec.estimator_factory()
            estimator.fit(x_train, y_train)
            scores = estimator.predict_proba(x_test)[:, 1]

        all_indices.extend(fold.test_indices)
        all_scores.extend(float(value) for value in scores)
        per_fold.append(
            FoldPrediction(
                fold_name=fold.name,
                test_year=fold.test_year,
                indices=tuple(fold.test_indices),
                scores=tuple(float(value) for value in scores),
            )
        )

    return np.array(all_indices, dtype=int), np.array(all_scores, dtype=float), per_fold


def _align_columns(matrix: np.ndarray, width: int) -> np.ndarray:
    """Pad or trim `matrix` to `width` columns, padding with 0.0.

    A padded indicator column means "not missing", which is the correct
    default: the column only exists because some training row lacked the
    feature, and a test row that has it is genuinely not missing.
    """
    if matrix.shape[1] == width:
        return matrix
    if matrix.shape[1] > width:
        return matrix[:, :width]
    padding = np.zeros((matrix.shape[0], width - matrix.shape[1]))
    return np.hstack([matrix, padding])


def _heuristic_scores(spec: ModelSpec, observations: Sequence[Observation]) -> np.ndarray:
    """Rank directly on one feature, with missing values ranked as least risky.

    Ranking a missing value as *least* risky is the conservative choice for a
    baseline: it refuses to let "we could not compute this" masquerade as
    evidence of danger, so the heuristic is never flattered by data gaps that
    happen to correlate with distress. The learned models, which receive an
    explicit missingness indicator, are free to find the opposite.
    """
    assert spec.heuristic_feature is not None
    raw = np.array(
        [
            np.nan
            if observation.features.get(spec.heuristic_feature) is None
            else observation.features[spec.heuristic_feature]
            for observation in observations
        ],
        dtype=float,
    )
    signed = raw if spec.heuristic_higher_is_riskier else -raw
    if np.isnan(signed).all():
        return np.zeros(len(signed))
    floor = np.nanmin(signed) - 1.0
    return np.where(np.isnan(signed), floor, signed)


class ModelArtifact(BaseModel):
    """Everything needed to reproduce and interpret a trained model (§29)."""

    model_config = ConfigDict(frozen=True)

    name: str
    family: str
    created_utc: str
    feature_families: tuple[str, ...]
    feature_names: tuple[str, ...]
    configuration: dict[str, Any]
    random_seed: int
    target_definition: dict[str, Any]
    dataset_summary: dict[str, Any]
    training_period: tuple[str, str]
    evaluation_strategy: str
    metrics: dict[str, Any]
    #: Present for linear models only; `None` otherwise.
    coefficients: dict[str, float] | None = None
    intercept: float | None = None


def fit_final_model(spec: ModelSpec, observations: Sequence[Observation]) -> tuple[Any, list[str]]:
    """Fit `spec` on every usable observation, for the shipped artifact.

    The shipped model is trained on all available history, which is what a
    deployment would do; every *number reported about* it comes from the
    walk-forward evaluation, which never trained on what it scored.
    """
    assert spec.estimator_factory is not None
    add_indicators = spec.family == "logistic"
    x, names = design_matrix(
        observations, spec.feature_names, add_missing_indicators=add_indicators
    )
    y = labels_array(observations)
    estimator = spec.estimator_factory()
    estimator.fit(x, y)
    return estimator, names


def linear_coefficients(estimator: Any, names: Sequence[str]) -> dict[str, float] | None:
    """Standardised-scale coefficients for a fitted logistic pipeline.

    Because the pipeline standardises first, these are directly comparable to
    each other: each is the change in log-odds per standard deviation of its
    feature. That is enough interpretability for Phase 8 (§22) -- Phase 9 owns
    anything beyond it.
    """
    model = estimator.named_steps.get("model") if hasattr(estimator, "named_steps") else estimator
    if not hasattr(model, "coef_"):
        return None
    return {name: float(value) for name, value in zip(names, model.coef_[0], strict=False)}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
