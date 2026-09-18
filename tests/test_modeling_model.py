"""The estimators and the walk-forward runner.

Two things are tested here that a model test usually skips and that matter
more than any score: that no fold's preprocessing is fitted on data the fold
should not see, and that a heuristic baseline ranks the way its rule says.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from credit_risk_copilot.modeling.contract import Observation, ObservationKey, Outcome
from credit_risk_copilot.modeling.features import FAMILY_ORDER
from credit_risk_copilot.modeling.model import (
    ModelSpec,
    build_model_specs,
    design_matrix,
    fit_final_model,
    labels_array,
    linear_coefficients,
    run_walk_forward,
)
from credit_risk_copilot.modeling.splits import walk_forward_folds


def _observation(cik: int, year: int, label: int, **features: float | None) -> Observation:
    prediction_date = date(year, 3, 1)
    return Observation(
        key=ObservationKey(
            cik=cik,
            company=f"Co {cik}",
            prediction_date=prediction_date,
            information_cutoff=prediction_date,
            source_accession=f"{cik:010d}-{str(year)[2:]}-000001",
            source_form="10-K",
            fiscal_period_label=f"FY{year - 1}",
        ),
        features=dict(features),
        outcome=(
            Outcome(label=1, horizon_end=date(year + 1, 3, 1), event_date=date(year, 9, 1))
            if label == 1
            else Outcome(label=0, horizon_end=date(year + 1, 3, 1))
        ),
    )


def _panel(seed: int = 0) -> list[Observation]:
    """A separable panel: failing companies carry a lower `signal`."""
    rng = np.random.default_rng(seed)
    observations: list[Observation] = []
    for year in range(2012, 2020):
        for cik in range(1, 61):
            failed = cik <= 6
            observations.append(
                _observation(
                    cik,
                    year,
                    1 if failed else 0,
                    log_total_assets=float(rng.normal(-1.0 if failed else 1.0, 0.8)),
                    log_revenue=float(rng.normal(0.0, 1.0)),
                )
            )
    return observations


class TestModelSpecs:
    def test_the_ablation_ladder_covers_every_family_cumulatively(self) -> None:
        specs = {spec.name: spec for spec in build_model_specs()}

        for depth in range(1, len(FAMILY_ORDER) + 1):
            name = f"logistic_{'+'.join(FAMILY_ORDER[:depth])}"
            assert name in specs
            assert specs[name].feature_families == FAMILY_ORDER[:depth]

    def test_baselines_and_an_alternative_family_are_present(self) -> None:
        families = {spec.family for spec in build_model_specs()}

        assert families == {"heuristic", "logistic", "gradient_boosting"}

    def test_phase7_own_output_is_one_of_the_baselines(self) -> None:
        """The comparison that decides whether ML earns its place: does the
        model beat the product's existing deterioration count?"""
        specs = {spec.name: spec for spec in build_model_specs()}

        assert specs["heuristic_phase7_deterioration"].heuristic_feature == (
            "n_deteriorating_ratios"
        )

    def test_heuristics_declare_their_own_direction(self) -> None:
        specs = {spec.name: spec for spec in build_model_specs()}

        assert specs["heuristic_leverage"].heuristic_higher_is_riskier
        assert not specs["heuristic_working_capital"].heuristic_higher_is_riskier


class TestDesignMatrix:
    def test_features_are_emitted_in_the_declared_order(self) -> None:
        """Column order must be stable, or a saved model's coefficients stop
        matching the features they were fitted on."""
        observations = [_observation(1, 2015, 0, a=1.0, b=2.0, c=3.0)]

        matrix, names = design_matrix(observations, ("c", "a", "b"), add_missing_indicators=False)

        assert names == ["c", "a", "b"]
        assert matrix[0].tolist() == [3.0, 1.0, 2.0]

    def test_labels_are_extracted_as_integers(self) -> None:
        observations = [_observation(1, 2015, 1, a=1.0), _observation(2, 2015, 0, a=1.0)]

        assert labels_array(observations).tolist() == [1, 0]


class TestHeuristicScoring:
    def _run(self, name: str, values: list[float | None]) -> np.ndarray:
        spec = next(s for s in build_model_specs() if s.name == name)
        feature = spec.heuristic_feature
        assert feature is not None
        observations = [
            _observation(i + 1, 2015, 0, **{feature: value}) for i, value in enumerate(values)
        ]
        return np.array(
            [
                float(v)
                for v in _heuristic(spec, observations)  # type: ignore[arg-type]
            ]
        )

    def test_a_higher_is_riskier_rule_ranks_larger_values_first(self) -> None:
        scores = self._run("heuristic_leverage", [0.1, 0.9, 0.5])

        assert scores.argmax() == 1

    def test_a_lower_is_riskier_rule_ranks_smaller_values_first(self) -> None:
        scores = self._run("heuristic_working_capital", [0.1, 0.9, 0.5])

        assert scores.argmax() == 0

    def test_a_missing_value_is_ranked_least_risky(self) -> None:
        """Conservative on purpose: a baseline must never be flattered by
        data gaps that happen to correlate with distress."""
        scores = self._run("heuristic_leverage", [0.1, None, 0.9])

        assert scores[1] == scores.min()

    def test_an_all_missing_feature_scores_flat_rather_than_raising(self) -> None:
        scores = self._run("heuristic_leverage", [None, None, None])

        assert scores.tolist() == [0.0, 0.0, 0.0]


def _heuristic(spec: ModelSpec, observations: list[Observation]) -> np.ndarray:
    from credit_risk_copilot.modeling.model import _heuristic_scores

    return _heuristic_scores(spec, observations)


class TestWalkForwardRunner:
    def test_a_learned_model_produces_one_score_per_test_row(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=6)
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")

        indices, scores, folds = run_walk_forward(spec, observations, plan)

        assert len(indices) == len(scores)
        assert len(indices) == sum(fold.test_size for fold in plan.folds)
        assert len(folds) == len(plan.folds)

    def test_every_row_is_scored_at_most_once(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=6)
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")

        indices, _, _ = run_walk_forward(spec, observations, plan)

        assert len(set(indices.tolist())) == len(indices)

    def test_scores_are_probabilities_for_a_learned_model(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=6)
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")

        _, scores, _ = run_walk_forward(spec, observations, plan)

        assert ((scores >= 0) & (scores <= 1)).all()

    def test_the_run_is_deterministic(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=6)
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")

        first = run_walk_forward(spec, observations, plan)[1]
        second = run_walk_forward(spec, observations, plan)[1]

        assert np.array_equal(first, second)

    def test_imputation_is_refit_per_fold_not_on_the_whole_panel(self) -> None:
        """The quiet, invalidating error: imputing on the full panel leaks the
        future's medians into the past. Here the feature's median shifts
        sharply after 2016, so a panel-wide median would give the 2013 fold a
        value no 2013 model could have known.
        """
        observations: list[Observation] = []
        for year in range(2012, 2020):
            for cik in range(1, 61):
                failed = cik <= 6
                # Missing for one company every year; the observed level jumps
                # by two orders of magnitude from 2017 onwards.
                value = None if cik == 7 else (1.0 if year < 2017 else 100.0)
                observations.append(
                    _observation(
                        cik, year, 1 if failed else 0, log_total_assets=value, log_revenue=1.0
                    )
                )

        plan = walk_forward_folds(observations, min_train_events=6)
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")
        estimator = spec.estimator_factory
        assert estimator is not None

        early_fold = plan.folds[0]
        train = [observations[i] for i in early_fold.train_indices]
        x_train, _ = design_matrix(train, spec.feature_names, add_missing_indicators=True)
        fitted = estimator()
        fitted.fit(x_train, labels_array(train))

        # The imputer saw only pre-2017 rows, so its median must be 1.0.
        assert fitted.named_steps["impute"].statistics_[0] == pytest.approx(1.0)


class TestFinalArtifact:
    def test_the_final_model_fits_on_every_usable_row(self) -> None:
        observations = _panel()
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")

        estimator, names = fit_final_model(spec, observations)

        assert hasattr(estimator, "predict_proba")
        assert names[: len(spec.feature_names)] == list(spec.feature_names)

    def test_coefficients_are_recoverable_and_named(self) -> None:
        observations = _panel()
        spec = next(s for s in build_model_specs() if s.name == "logistic_scale")
        estimator, names = fit_final_model(spec, observations)

        coefficients = linear_coefficients(estimator, names)

        assert coefficients is not None
        assert set(coefficients) == set(names)
        # Failing companies were given a *lower* log_total_assets, so the
        # coefficient must be negative.
        assert coefficients["log_total_assets"] < 0

    def test_a_tree_model_reports_no_coefficients_rather_than_fabricating_them(self) -> None:
        observations = _panel()
        spec = next(s for s in build_model_specs() if s.family == "gradient_boosting")
        reduced = ModelSpec(
            name=spec.name,
            family=spec.family,
            feature_families=("scale",),
            configuration=spec.configuration,
            estimator_factory=spec.estimator_factory,
        )
        estimator, names = fit_final_model(reduced, observations)

        assert linear_coefficients(estimator, names) is None
