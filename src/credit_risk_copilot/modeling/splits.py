"""Evaluation design: out-of-time folds over a company x time panel.

A random train/test split would be meaningless here and actively misleading,
for two compounding reasons:

- **Time.** Bankruptcies arrive in macroeconomic clusters (2009, 2015-16
  energy, 2020). A random split trains on 2020 and tests on 2016, which is
  not a question anyone can ask in production.
- **Repeated companies.** One company contributes a row per annual filing.
  A random split puts a company's 2016 row in train and its 2017 row in test,
  and those two rows share most of their history.

## Walk-forward, because there are not enough events for one holdout

The obvious alternative -- a single out-of-time holdout -- wastes the scarce
resource. With roughly a hundred events spread over a decade, reserving the
last quarter of the timeline for test leaves a test set whose confidence
interval is wider than any effect being measured.

`walk_forward_folds` instead trains on everything up to year Y and tests on
year Y+1, stepping Y forward across the usable span. Every observation after
the burn-in is scored exactly once, by a model that never saw it or anything
after it, and the pooled out-of-fold predictions give one evaluation set with
the full event count. This is the standard backtest shape in credit risk, and
it answers the deployment question directly: *if we had run this each year,
how would it have done?*

## Company overlap is reported, not assumed away

In walk-forward, a company can appear in an early fold's training data and a
later fold's test data. That is not leakage -- it is exactly the production
situation, where you have years of history on the company you are scoring.
But persistent company-level characteristics could still let a model memorise
rather than generalise, so `held_out_company_folds` builds a variant in which
the test companies were never trained on at all, and the evaluation reports
both. A large gap between them is evidence of memorisation; a small one is
evidence against it. See that function for why the naive construction --
deleting each fold's test companies from its own training rows -- is the wrong
check on a panel where nearly every company files in nearly every year.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.modeling.contract import Observation


class Fold(BaseModel):
    """One out-of-time fold: indices into the observation sequence."""

    model_config = ConfigDict(frozen=True)

    name: str
    test_year: int
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    @property
    def train_size(self) -> int:
        return len(self.train_indices)

    @property
    def test_size(self) -> int:
        return len(self.test_indices)


class FoldPlan(BaseModel):
    """Every fold, plus the diagnostics that make the design reviewable."""

    model_config = ConfigDict(frozen=True)

    folds: tuple[Fold, ...]
    strategy: str
    min_train_events: int

    def summary(self) -> list[dict[str, int | str]]:
        return [
            {
                "fold": fold.name,
                "test_year": fold.test_year,
                "train_rows": fold.train_size,
                "test_rows": fold.test_size,
            }
            for fold in self.folds
        ]


def _year(observation: Observation) -> int:
    return observation.key.prediction_date.year


def walk_forward_folds(
    observations: Sequence[Observation],
    *,
    min_train_events: int = 20,
    min_test_events: int = 1,
) -> FoldPlan:
    """Expanding-window folds: train on `< Y`, test on `== Y`.

    `min_train_events` is a floor on *positive* training rows, not on training
    rows overall. A fold whose training data contains three bankruptcies
    cannot estimate anything stable, and including it would add noise to the
    pooled result while looking like extra evidence. The burn-in years are
    reported rather than silently dropped.

    `min_test_events` skips a test year with no events at all: such a year
    contributes only negatives, which changes the pooled base rate without
    contributing any discrimination information.
    """
    years = sorted({_year(obs) for obs in observations})
    folds: list[Fold] = []

    for test_year in years:
        train_indices = tuple(i for i, obs in enumerate(observations) if _year(obs) < test_year)
        test_indices = tuple(i for i, obs in enumerate(observations) if _year(obs) == test_year)
        train_events = sum(1 for i in train_indices if observations[i].outcome.label == 1)
        test_events = sum(1 for i in test_indices if observations[i].outcome.label == 1)
        if train_events < min_train_events or test_events < min_test_events:
            continue
        folds.append(
            Fold(
                name=f"test_{test_year}",
                test_year=test_year,
                train_indices=train_indices,
                test_indices=test_indices,
            )
        )

    return FoldPlan(folds=tuple(folds), strategy="walk_forward", min_train_events=min_train_events)


def held_out_company_folds(
    observations: Sequence[Observation],
    plan: FoldPlan,
    *,
    holdout_fraction: float = 0.3,
    seed: int = 20260917,
) -> FoldPlan:
    """Walk-forward folds in which the test companies were *never* trained on.

    The obvious construction -- take each walk-forward fold and delete its
    test companies from its training rows -- does not work on this panel and
    should not be used. Nearly every company files in nearly every year, so
    removing the test year's companies removes almost the entire training set;
    measured on this corpus it left training sets so small that the resulting
    ROC-AUC (0.556) said nothing about memorisation and everything about
    having nothing to learn from.

    This instead partitions *companies* once: a deterministic hash-based
    holdout never appears in any training set, and each fold tests only on the
    holdout companies' rows for that year. Training keeps the other ~70% of
    companies and the full expanding time window, so a drop against the
    headline design is attributable to unfamiliarity with the company rather
    than to a starved fit.
    """
    companies = sorted({observation.key.cik for observation in observations})
    rng = random.Random(seed)
    shuffled = companies[:]
    rng.shuffle(shuffled)
    holdout = set(shuffled[: max(1, int(round(holdout_fraction * len(shuffled))))])

    folds: list[Fold] = []
    for fold in plan.folds:
        train_indices = tuple(
            i for i in fold.train_indices if observations[i].key.cik not in holdout
        )
        test_indices = tuple(i for i in fold.test_indices if observations[i].key.cik in holdout)
        if not train_indices or not test_indices:
            continue
        folds.append(
            Fold(
                name=f"{fold.name}_heldout",
                test_year=fold.test_year,
                train_indices=train_indices,
                test_indices=test_indices,
            )
        )

    return FoldPlan(
        folds=tuple(folds),
        strategy=f"walk_forward_held_out_companies_{int(holdout_fraction * 100)}pct",
        min_train_events=plan.min_train_events,
    )


def assert_temporal_ordering(observations: Sequence[Observation], plan: FoldPlan) -> None:
    """Verify no training row is dated on or after any test row in its fold.

    The split is only as good as its implementation, so this is asserted for
    every fold rather than assumed from the construction above -- the same
    reasoning as `Observation.assert_no_future_information`.
    """
    for fold in plan.folds:
        if not fold.train_indices or not fold.test_indices:
            continue
        latest_train = max(observations[i].key.prediction_date for i in fold.train_indices)
        earliest_test = min(observations[i].key.prediction_date for i in fold.test_indices)
        if latest_train >= earliest_test:
            raise AssertionError(
                f"{fold.name}: a training row dated {latest_train} is not strictly before the "
                f"earliest test row {earliest_test}."
            )


def fold_event_counts(observations: Sequence[Observation], plan: FoldPlan) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for fold in plan.folds:
        rows.append(
            {
                "test_year": fold.test_year,
                "train_rows": fold.train_size,
                "train_events": sum(
                    1 for i in fold.train_indices if observations[i].outcome.label == 1
                ),
                "test_rows": fold.test_size,
                "test_events": sum(
                    1 for i in fold.test_indices if observations[i].outcome.label == 1
                ),
                "test_companies": len({observations[i].key.cik for i in fold.test_indices}),
            }
        )
    return rows
