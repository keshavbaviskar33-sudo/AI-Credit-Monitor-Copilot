"""Artifact round-trips and feature-schema consistency.

A saved model and a saved explanation are only useful together if the column
order they were built with is reproducible. These tests guard the seam where
that could silently break: `design_matrix` must lay columns out identically
across calls, a reloaded estimator must attribute identically to the one that
was saved, and an explanation must name the model it came from.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import joblib
import numpy as np

from credit_risk_copilot.explain import attributor_for
from credit_risk_copilot.explain.adapters import AttributionResult
from credit_risk_copilot.explain.local import explain_observation
from credit_risk_copilot.modeling.contract import Observation, ObservationKey, Outcome
from credit_risk_copilot.modeling.features import FAMILY_ORDER, feature_names_for_families
from credit_risk_copilot.modeling.model import (
    _logistic_pipeline,
    build_model_specs,
    design_matrix,
    fit_final_model,
    labels_array,
)


def _observations(n: int = 120, seed: int = 0) -> list[Observation]:
    """A small panel over the real feature schema, with realistic gaps."""
    rng = np.random.default_rng(seed)
    names = feature_names_for_families(FAMILY_ORDER)
    built: list[Observation] = []
    for i in range(n):
        features: dict[str, float | None] = {}
        for j, name in enumerate(names):
            # Deterministic sparsity: every 7th feature missing for every 3rd row.
            features[name] = None if (i % 3 == 0 and j % 7 == 0) else float(rng.normal())
        features["periods_available"] = 5.0
        prediction_date = date(2013 + i % 6, 3, 1)
        built.append(
            Observation(
                key=ObservationKey(
                    cik=1000 + i,
                    company=f"Co {i}",
                    prediction_date=prediction_date,
                    information_cutoff=prediction_date,
                    source_accession=f"{i:010d}-19-000001",
                    source_form="10-K",
                    fiscal_period_label=f"FY{prediction_date.year - 1}",
                ),
                features=features,
                outcome=(
                    Outcome(
                        label=1,
                        horizon_end=date(prediction_date.year + 1, 3, 1),
                        event_date=date(prediction_date.year, 9, 1),
                    )
                    if i % 8 == 0
                    else Outcome(label=0, horizon_end=date(prediction_date.year + 1, 3, 1))
                ),
            )
        )
    return built


class TestFeatureSchemaConsistency:
    def test_design_matrix_column_order_is_reproducible(self) -> None:
        """Coefficients are positional. If column order drifts between the fit
        and the explanation, every attribution silently points at the wrong
        feature."""
        observations = _observations()
        names = feature_names_for_families(FAMILY_ORDER)

        first, first_names = design_matrix(observations, names, add_missing_indicators=True)
        second, second_names = design_matrix(observations, names, add_missing_indicators=True)

        assert first_names == second_names
        assert np.array_equal(first, second, equal_nan=True)

    def test_base_columns_come_first_and_in_the_declared_order(self) -> None:
        observations = _observations()
        names = feature_names_for_families(FAMILY_ORDER)

        _, built = design_matrix(observations, names, add_missing_indicators=True)

        assert built[: len(names)] == list(names)

    def test_indicator_columns_are_suffixed_consistently(self) -> None:
        observations = _observations()
        names = feature_names_for_families(FAMILY_ORDER)

        _, built = design_matrix(observations, names, add_missing_indicators=True)

        indicators = built[len(names) :]
        assert indicators
        assert all(name.endswith("__missing") for name in indicators)
        assert all(name.removesuffix("__missing") in names for name in indicators)

    def test_a_subset_of_families_yields_a_prefix_consistent_schema(self) -> None:
        """The ablation relies on this: narrowing the families must not
        reorder the columns that remain."""
        wide = feature_names_for_families(FAMILY_ORDER)
        narrow = feature_names_for_families(FAMILY_ORDER[:3])

        assert list(narrow) == [name for name in wide if name in set(narrow)]


class TestArtifactRoundTrip:
    def test_a_reloaded_model_attributes_identically(self, tmp_path: Path) -> None:
        observations = _observations()
        spec = next(
            s
            for s in build_model_specs()
            if s.name == "logistic_scale+levels+ratios+trends+signals+quality"
        )
        estimator, names = fit_final_model(spec, observations)
        x, _ = design_matrix(observations, spec.feature_names, add_missing_indicators=True)

        path = tmp_path / "model.joblib"
        joblib.dump(estimator, path)
        reloaded = joblib.load(path)

        before = attributor_for(estimator, tuple(names)).attribute(x)
        after = attributor_for(reloaded, tuple(names)).attribute(x)

        assert np.allclose(before.contributions, after.contributions)
        assert before.baseline == after.baseline

    def test_a_reloaded_model_scores_identically(self, tmp_path: Path) -> None:
        observations = _observations()
        x, names = design_matrix(
            observations,
            feature_names_for_families(FAMILY_ORDER),
            add_missing_indicators=True,
        )
        estimator = _logistic_pipeline().fit(x, labels_array(observations))

        path = tmp_path / "model.joblib"
        joblib.dump(estimator, path)

        assert np.allclose(
            estimator.predict_proba(x)[:, 1], joblib.load(path).predict_proba(x)[:, 1]
        )

    def test_the_artifacts_feature_count_matches_its_design_matrix(self) -> None:
        """The check that would have caught a schema drift between Phase 8's
        saved artifact and Phase 9's attribution."""
        observations = _observations()
        spec = next(
            s
            for s in build_model_specs()
            if s.name == "logistic_scale+levels+ratios+trends+signals+quality"
        )
        estimator, names = fit_final_model(spec, observations)

        assert len(names) == estimator.named_steps["model"].coef_.shape[1]


class TestExplanationIdentifiesItsModel:
    def test_the_explanation_records_model_and_method(self) -> None:
        """An explanation detached from the model that produced it cannot be
        audited later."""
        observations = _observations()
        attribution = AttributionResult(
            method="linear_contribution",
            feature_names=("ratio_debt_to_assets",),
            contributions=np.array([[0.3]]),
            baseline=-4.0,
            values=np.array([[0.6]]),
        )

        explanation = explain_observation(
            observation=observations[0],
            attribution=attribution,
            row=0,
            score=0.3,
            link_score=-3.7,
            facts={},
            model_name="logistic_v1",
            model_family="logistic",
        )

        assert explanation.model_name == "logistic_v1"
        assert explanation.model_family == "logistic"
        assert explanation.attribution_method == "linear_contribution"
        assert explanation.baseline == -4.0
