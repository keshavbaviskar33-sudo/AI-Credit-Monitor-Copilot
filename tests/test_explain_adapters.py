"""Attribution adapters: exactness, determinism, and dispatch.

The property that matters most is **reconstruction**: an additive attribution
that does not sum back to the model's own output is not a decomposition of
that model, it is a plausible-looking fiction. Every method here is tested
against the model it claims to explain rather than against a fixture of
expected numbers.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from credit_risk_copilot.explain.adapters import (
    AttributionResult,
    LinearContributions,
    TreeShapContributions,
    attributor_for,
)
from credit_risk_copilot.modeling.model import _logistic_pipeline


def _data(n: int = 200, features: int = 6, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, features))
    logit = 1.5 * x[:, 0] - 1.0 * x[:, 1]
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return x, y


def _data_with_gaps(n: int = 200, features: int = 6, seed: int = 1):  # type: ignore[no-untyped-def]
    x, y = _data(n, features, seed)
    x = x.copy()
    x[::5, 2] = np.nan  # every fifth row lacks feature 2
    return x, y


class TestLinearContributions:
    def _fitted(self, seed: int = 0):  # type: ignore[no-untyped-def]
        x, y = _data_with_gaps(seed=seed)
        pipeline = _logistic_pipeline()
        pipeline.fit(x, y)
        names = tuple(f"f{i}" for i in range(x.shape[1]))
        return pipeline, LinearContributions(pipeline, names), x

    def test_contributions_reconstruct_the_models_own_log_odds(self) -> None:
        """The decisive property. For a linear model this is exact, not
        approximate, which is why no attribution library is needed here."""
        pipeline, attributor, x = self._fitted()

        result = attributor.attribute(x)

        assert result.reconstruction_error(attributor.link_scores(x)) < 1e-9

    def test_the_link_score_is_the_models_own_decision_function(self) -> None:
        pipeline, attributor, x = self._fitted()

        link = attributor.link_scores(x)

        assert np.allclose(1 / (1 + np.exp(-link)), pipeline.predict_proba(x)[:, 1])

    def test_contributions_are_computed_on_the_values_the_model_saw(self) -> None:
        """An imputed feature must contribute through its imputed value --
        otherwise the missingness analysis would describe a model that does
        not exist."""
        _, attributor, x = self._fitted()

        result = attributor.attribute(x)

        missing_rows = np.isnan(x[:, 2])
        # Every imputed row got the same imputed value, so the same contribution.
        assert np.allclose(
            result.contributions[missing_rows, 2], result.contributions[missing_rows, 2][0]
        )

    def test_reported_values_are_the_raw_ones_not_the_scaled_ones(self) -> None:
        """An explanation must show the analyst the ratio as filed."""
        _, attributor, x = self._fitted()

        result = attributor.attribute(x)

        assert np.allclose(result.values, x, equal_nan=True)

    def test_attribution_is_deterministic(self) -> None:
        _, attributor, x = self._fitted()

        assert np.array_equal(
            attributor.attribute(x).contributions, attributor.attribute(x).contributions
        )

    def test_a_zero_coefficient_feature_contributes_nothing(self) -> None:
        x, y = _data()
        pipeline = _logistic_pipeline()
        pipeline.fit(x, y)
        pipeline.named_steps["model"].coef_[0][3] = 0.0
        attributor = LinearContributions(pipeline, tuple(f"f{i}" for i in range(x.shape[1])))

        assert np.allclose(attributor.attribute(x).contributions[:, 3], 0.0)


class TestTreeShapContributions:
    def _fitted(self):  # type: ignore[no-untyped-def]
        x, y = _data_with_gaps(n=300)
        model = HistGradientBoostingClassifier(
            max_leaf_nodes=4, min_samples_leaf=20, max_iter=25, random_state=0
        )
        model.fit(x, y)
        names = tuple(f"f{i}" for i in range(x.shape[1]))
        return model, TreeShapContributions(model, names), x

    def test_shap_values_reconstruct_the_models_own_output(self) -> None:
        """Why SHAP is used here and not on the linear model: a tree ensemble
        has no closed-form decomposition, and this is the check that TreeSHAP's
        one is faithful."""
        _, attributor, x = self._fitted()

        result = attributor.attribute(x)

        assert result.reconstruction_error(attributor.link_scores(x)) < 1e-4

    def test_nan_inputs_are_passed_through_rather_than_imputed(self) -> None:
        """Native missing handling is the reason this family is in the
        comparison at all."""
        _, attributor, x = self._fitted()

        result = attributor.attribute(x)

        assert np.isnan(result.values[::5, 2]).all()

    def test_attribution_is_deterministic(self) -> None:
        _, attributor, x = self._fitted()

        assert np.allclose(
            attributor.attribute(x).contributions, attributor.attribute(x).contributions
        )


class TestDispatch:
    def test_a_logistic_pipeline_gets_exact_linear_contributions(self) -> None:
        x, y = _data()
        pipeline = _logistic_pipeline().fit(x, y)

        attributor = attributor_for(pipeline, tuple(f"f{i}" for i in range(x.shape[1])))

        assert attributor.name == "linear_contribution"

    def test_a_boosting_model_gets_tree_shap(self) -> None:
        x, y = _data()
        model = HistGradientBoostingClassifier(max_iter=10, random_state=0).fit(x, y)

        attributor = attributor_for(model, tuple(f"f{i}" for i in range(x.shape[1])))

        assert attributor.name == "tree_shap"

    def test_a_bare_linear_model_is_refused_with_a_reason(self) -> None:
        """Explaining a bare model would compute contributions on unscaled
        values the model never saw."""
        x, y = _data()
        model = LogisticRegression().fit(x, y)

        with pytest.raises(TypeError, match="wrap it in the pipeline"):
            attributor_for(model, tuple(f"f{i}" for i in range(x.shape[1])))

    def test_an_unknown_model_is_refused_rather_than_guessed_at(self) -> None:
        class Mystery:
            pass

        with pytest.raises(TypeError, match="No attribution adapter"):
            attributor_for(Mystery(), ("a",))


class TestAttributionResult:
    def test_misaligned_shapes_are_refused(self) -> None:
        with pytest.raises(ValueError, match="must align"):
            AttributionResult(
                method="x",
                feature_names=("a", "b"),
                contributions=np.zeros((3, 2)),
                baseline=0.0,
                values=np.zeros((4, 2)),
            )

    def test_a_name_count_mismatch_is_refused(self) -> None:
        with pytest.raises(ValueError, match="contribution columns"):
            AttributionResult(
                method="x",
                feature_names=("a",),
                contributions=np.zeros((3, 2)),
                baseline=0.0,
                values=np.zeros((3, 2)),
            )
