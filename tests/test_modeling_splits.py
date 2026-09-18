"""Evaluation design: fold construction, temporal ordering, leakage checks.

A split is a claim about what the model was allowed to know. These tests check
the claim rather than trusting the construction, which is the same standard
`test_modeling_contract.py` applies to the feature side.
"""

from __future__ import annotations

from datetime import date

import pytest

from credit_risk_copilot.modeling.contract import Observation, ObservationKey, Outcome
from credit_risk_copilot.modeling.splits import (
    assert_temporal_ordering,
    fold_event_counts,
    held_out_company_folds,
    walk_forward_folds,
)


def _observation(cik: int, year: int, label: int) -> Observation:
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
        features={},
        outcome=(
            Outcome(label=1, horizon_end=date(year + 1, 3, 1), event_date=date(year, 9, 1))
            if label == 1
            else Outcome(label=0, horizon_end=date(year + 1, 3, 1))
        ),
    )


def _panel(events_per_year: int = 5, companies: int = 40, years: range = range(2012, 2020)):
    """A synthetic panel: `companies` companies observed every year, with the
    first `events_per_year` of them failing in each year."""
    observations = []
    for year in years:
        for cik in range(1, companies + 1):
            observations.append(_observation(cik, year, 1 if cik <= events_per_year else 0))
    return observations


class TestWalkForwardFolds:
    def test_each_fold_trains_only_on_earlier_years(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)

        for fold in plan.folds:
            train_years = {observations[i].key.prediction_date.year for i in fold.train_indices}
            assert max(train_years) < fold.test_year

    def test_every_year_after_burn_in_is_tested_exactly_once(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)

        tested = [i for fold in plan.folds for i in fold.test_indices]
        assert len(tested) == len(set(tested))
        assert {fold.test_year for fold in plan.folds} == set(range(2013, 2020))

    def test_burn_in_years_are_excluded_not_trained_on_nothing(self) -> None:
        """A fold whose training data holds three bankruptcies cannot estimate
        anything stable; including it would add noise while looking like extra
        evidence."""
        observations = _panel(events_per_year=5)

        plan = walk_forward_folds(observations, min_train_events=20)

        # 5 events/year, so 20 training events needs 4 prior years: 2016 on.
        assert min(fold.test_year for fold in plan.folds) == 2016

    def test_a_test_year_with_no_events_is_skipped(self) -> None:
        observations = [
            *[_observation(cik, 2015, 1 if cik <= 25 else 0) for cik in range(1, 40)],
            *[_observation(cik, 2016, 0) for cik in range(1, 40)],
            *[_observation(cik, 2017, 1 if cik <= 3 else 0) for cik in range(1, 40)],
        ]

        plan = walk_forward_folds(observations, min_train_events=20)

        assert {fold.test_year for fold in plan.folds} == {2017}

    def test_temporal_ordering_holds_for_every_fold(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)

        assert_temporal_ordering(observations, plan)


class TestTemporalAssertion:
    def test_an_overlapping_fold_is_caught(self) -> None:
        """The assertion has to actually fire, or it is decoration."""
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)
        broken = plan.model_copy(
            update={
                "folds": (
                    plan.folds[0].model_copy(
                        update={
                            "train_indices": (
                                *plan.folds[0].train_indices,
                                plan.folds[0].test_indices[0],
                            )
                        }
                    ),
                )
            }
        )

        with pytest.raises(AssertionError, match="not strictly before"):
            assert_temporal_ordering(observations, broken)


class TestHeldOutCompanyFolds:
    def test_no_held_out_company_appears_in_any_training_set(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)

        strict = held_out_company_folds(observations, plan)

        held_out = {observations[i].key.cik for f in strict.folds for i in f.test_indices}
        trained_on = {observations[i].key.cik for f in strict.folds for i in f.train_indices}
        assert not (held_out & trained_on)

    def test_the_training_set_survives_rather_than_collapsing(self) -> None:
        """The whole point of this construction. Deleting each fold's test
        companies from its own training rows leaves nearly nothing on a panel
        where every company files every year, and the resulting score measures
        starvation rather than memorisation."""
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)

        strict = held_out_company_folds(observations, plan, holdout_fraction=0.3)

        for original, variant in zip(plan.folds, strict.folds, strict=False):
            assert variant.train_size > 0.5 * original.train_size

    def test_the_holdout_is_deterministic(self) -> None:
        observations = _panel()
        plan = walk_forward_folds(observations, min_train_events=5)

        first = held_out_company_folds(observations, plan)
        second = held_out_company_folds(observations, plan)

        assert [f.test_indices for f in first.folds] == [f.test_indices for f in second.folds]

    def test_temporal_ordering_still_holds(self) -> None:
        observations = _panel()
        plan = held_out_company_folds(
            observations, walk_forward_folds(observations, min_train_events=5)
        )

        assert_temporal_ordering(observations, plan)


class TestFoldDiagnostics:
    def test_event_counts_are_reported_per_fold(self) -> None:
        observations = _panel(events_per_year=5, companies=40)
        plan = walk_forward_folds(observations, min_train_events=5)

        counts = fold_event_counts(observations, plan)

        assert counts[0]["test_year"] == 2013
        assert counts[0]["train_events"] == 5
        assert counts[0]["test_events"] == 5
        assert counts[0]["test_rows"] == 40
        assert counts[0]["test_companies"] == 40
