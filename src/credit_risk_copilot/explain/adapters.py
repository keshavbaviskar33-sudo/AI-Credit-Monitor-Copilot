"""Attribution methods, behind one interface.

## Why the primary model needs no attribution library

For the Phase 8 primary model -- `SimpleImputer -> StandardScaler ->
LogisticRegression` -- the contribution of feature *j* to observation *i*'s
log-odds is exactly

    contribution_ij = coefficient_j * scaled_value_ij

and those contributions plus the intercept sum to the model's own log-odds.
That is not an approximation of the model; it *is* the model, rearranged. A
linear SHAP explainer computes `coefficient_j * (x_ij - E[x_j])`, which is the
same decomposition with the mean folded into the baseline instead of the
intercept, at meaningfully more cost and with a dependency in the middle.

So `LinearContributions` is the primary method, and the honest finding for the
phase brief's §8 is that **SHAP adds nothing for a linear model**. It is not
used there.

## Where SHAP does earn its place

For the gradient-boosting challenger there is no closed form: a tree ensemble's
prediction is not a weighted sum of its inputs. TreeSHAP computes exact
additive Shapley values for tree models in polynomial time, which is the one
thing here that cannot be reproduced in a few lines. `TreeShapContributions`
uses it, and it is the only place `shap` is imported.

## What both methods share, and what neither claims

Both produce **additive contributions in the model's own link units**, so both
land in the same `FeatureContribution` objects and can be grouped, compared and
traced identically. Neither is a causal statement: a contribution says this
input moved this model's output, not that the quantity caused the event. That
distinction is carried explicitly into the explanation schema rather than left
to the reader (§31).

## Correlated features

Both methods split a shared effect between correlated inputs, and financial
features are heavily correlated by construction. Individual feature rankings
are therefore unstable in a way group rankings are not, which is why
`groups.py` exists and why the report leads with dimensions rather than
features.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class AttributionResult:
    """Per-observation additive contributions, plus the baseline they sit on.

    A plain container rather than a pydantic model: this is the internal
    hand-off from an attribution method to `local.py`, which converts it into
    the provenance-carrying domain schema. Nothing outside `explain/` sees it.
    """

    __slots__ = ("method", "feature_names", "contributions", "baseline", "values")

    def __init__(
        self,
        *,
        method: str,
        feature_names: tuple[str, ...],
        contributions: np.ndarray,
        baseline: float,
        values: np.ndarray,
    ) -> None:
        if contributions.shape != values.shape:
            raise ValueError(
                f"contributions {contributions.shape} and values {values.shape} must align"
            )
        if contributions.shape[1] != len(feature_names):
            raise ValueError(
                f"{contributions.shape[1]} contribution columns for "
                f"{len(feature_names)} feature names"
            )
        self.method = method
        self.feature_names = feature_names
        self.contributions = contributions
        self.baseline = baseline
        self.values = values

    def reconstruction_error(self, link_scores: np.ndarray) -> float:
        """Max absolute gap between `baseline + sum(contributions)` and the
        model's own output in link units.

        An additive attribution that does not reconstruct the prediction is
        wrong, and silently so. `tests/test_explain_adapters.py` asserts this
        is near zero for both methods; `local.py` reports it as a caveat if it
        ever is not.
        """
        reconstructed = self.baseline + self.contributions.sum(axis=1)
        return float(np.max(np.abs(reconstructed - link_scores)))


class Attributor(Protocol):
    """What an explanation method has to provide.

    Deliberately small. Adding a model family later means writing one of these,
    not touching the schema, the grouping or the provenance chain.
    """

    name: str

    def attribute(self, x: np.ndarray) -> AttributionResult: ...

    def link_scores(self, x: np.ndarray) -> np.ndarray: ...


class LinearContributions:
    """Exact additive contributions for a fitted scikit-learn logistic pipeline.

    Applies the pipeline's own fitted imputer and scaler, so contributions are
    computed on exactly the values the model saw -- an imputed feature
    contributes through its imputed value, which is what makes the
    missingness analysis in §13 meaningful rather than notional.
    """

    name = "linear_contribution"

    def __init__(self, pipeline: Any, feature_names: tuple[str, ...]) -> None:
        self._pipeline = pipeline
        self._model = pipeline.named_steps["model"]
        self._feature_names = feature_names

    def _transform(self, x: np.ndarray) -> np.ndarray:
        transformed = x
        for name, step in self._pipeline.steps[:-1]:
            del name
            transformed = step.transform(transformed)
        return np.asarray(transformed, dtype=float)

    def attribute(self, x: np.ndarray) -> AttributionResult:
        scaled = self._transform(x)
        coefficients = self._model.coef_[0]
        return AttributionResult(
            method=self.name,
            feature_names=self._feature_names,
            contributions=scaled * coefficients,
            baseline=float(self._model.intercept_[0]),
            # The *untransformed* values, because an explanation must show the
            # analyst the ratio as filed, not its z-score.
            values=np.asarray(x, dtype=float),
        )

    def link_scores(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.decision_function(self._transform(x)), dtype=float)


class TreeShapContributions:
    """TreeSHAP attributions for a fitted gradient-boosting classifier.

    The one place `shap` is imported. Imported lazily so the rest of the
    explanation layer -- and every test that does not exercise the challenger
    model -- stays independent of it.
    """

    name = "tree_shap"

    def __init__(self, model: Any, feature_names: tuple[str, ...]) -> None:
        self._model = model
        self._feature_names = feature_names
        self._explainer: Any | None = None

    def _get_explainer(self) -> Any:
        if self._explainer is None:
            import shap  # noqa: PLC0415 - deliberate: keep the dependency optional

            self._explainer = shap.TreeExplainer(self._model)
        return self._explainer

    def attribute(self, x: np.ndarray) -> AttributionResult:
        explainer = self._get_explainer()
        explanation = explainer(np.asarray(x, dtype=float), check_additivity=False)
        contributions = np.asarray(explanation.values, dtype=float)
        # Binary classifiers may return (n, features, 2); keep the positive class.
        if contributions.ndim == 3:
            contributions = contributions[:, :, 1]
        base = np.asarray(explanation.base_values, dtype=float)
        if base.ndim > 1:
            base = base[:, -1]
        return AttributionResult(
            method=self.name,
            feature_names=self._feature_names,
            contributions=contributions,
            baseline=float(np.mean(base)),
            values=np.asarray(x, dtype=float),
        )

    def link_scores(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.decision_function(np.asarray(x, dtype=float)), dtype=float)


def attributor_for(estimator: Any, feature_names: tuple[str, ...]) -> Attributor:
    """Pick the right method for a fitted estimator.

    Dispatches on what the estimator *is* rather than on a string the caller
    passes, so a future model family is wired in here once and every consumer
    of `ModelExplanation` keeps working unchanged (§45).
    """
    if hasattr(estimator, "named_steps") and "model" in estimator.named_steps:
        inner = estimator.named_steps["model"]
        if hasattr(inner, "coef_"):
            return LinearContributions(estimator, feature_names)
        raise TypeError(
            f"Pipeline's final step {type(inner).__name__} has no coefficients and no "
            "attribution adapter; add one in explain/adapters.py."
        )
    if hasattr(estimator, "coef_"):
        raise TypeError(
            "A bare linear model has no fitted preprocessing; wrap it in the pipeline it "
            "was trained as, so contributions are computed on the values the model saw."
        )
    if estimator.__class__.__name__.startswith("HistGradientBoosting"):
        return TreeShapContributions(estimator, feature_names)
    raise TypeError(
        f"No attribution adapter for {type(estimator).__name__}; add one in "
        "explain/adapters.py rather than exposing a library object to callers."
    )
