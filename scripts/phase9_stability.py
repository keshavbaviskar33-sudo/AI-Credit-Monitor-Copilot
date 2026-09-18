"""Phase 9: are the explanations stable, and how should the score be read?

Two questions the earlier scripts leave open.

**Stability (§19).** Era-wise attribution shows the drivers holding their
order across macro regimes, but that is stability against *time*. This adds
stability against *sampling*: refit the model on bootstrap resamples of the
training companies and watch how far the grouped attribution moves. An
explanation that reorders when a few companies are swapped is not something to
put in front of an analyst, however exact its arithmetic.

Resampling is by **company**, not by row -- a company's ten filings are not ten
independent draws, and resampling rows would understate the variation exactly
as it would for a confidence interval (the same reasoning as
`metrics._bootstrap_ci`).

**Ranking (§23).** Phase 8 concluded the output is a ranking, not a
probability (D-033). This measures what that ranking is actually like: how
concentrated the scores are, how much of the event set a given alert budget
captures, and how stable a company's position is from one year to the next --
because a watchlist that reshuffles annually is not a watchlist.

    uv run python scripts/phase9_stability.py
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credit_risk_copilot.explain import attributor_for, group_of
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.model import (
    RANDOM_SEED,
    ModelSpec,
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

#: Bootstrap resamples for attribution stability. Fewer than the 1,000 used for
#: metric intervals because each one refits the model rather than re-scoring,
#: and 60 is enough to separate "the ordering holds" from "the ordering moves".
BOOTSTRAP_FITS = 60

#: Alert budgets an analyst might actually work to, as a share of the book.
ALERT_RATES: tuple[float, ...] = (0.01, 0.02, 0.05, 0.10, 0.20)


def load_panel() -> list[Observation]:
    frame = pd.read_csv(PHASE8_DIR / "observations_primary.csv")
    rows = frame.replace({np.nan: None}).to_dict("records")
    return [o for o in observations_from_rows(rows) if o.outcome.is_usable]


def _group_shares(contributions: np.ndarray, names: tuple[str, ...]) -> dict[str, float]:
    groups: dict[str, list[int]] = defaultdict(list)
    for column, name in enumerate(names):
        groups[group_of(name)].append(column)
    total = np.abs(contributions).sum() or 1.0
    return {
        group: float(np.abs(contributions[:, columns]).sum() / total)
        for group, columns in groups.items()
    }


def attribution_stability(
    spec: ModelSpec, observations: list[Observation], plan: Any
) -> dict[str, Any]:
    """How far grouped attribution moves when the training companies are resampled.

    The final fold is used: it has the most training data, so any instability
    here is not a small-sample artefact of an early fold.
    """
    fold = plan.folds[-1]
    train = [observations[i] for i in fold.train_indices]
    test = [observations[i] for i in fold.test_indices]

    x_train, names_list = design_matrix(train, spec.feature_names, add_missing_indicators=True)
    x_test, _ = design_matrix(test, spec.feature_names, add_missing_indicators=True)
    if x_test.shape[1] != x_train.shape[1]:
        x_test = np.hstack(
            [x_test, np.zeros((x_test.shape[0], x_train.shape[1] - x_test.shape[1]))]
        )
    names = tuple(names_list)
    y_train = labels_array(train)

    assert spec.estimator_factory is not None
    baseline_estimator = spec.estimator_factory().fit(x_train, y_train)
    baseline = _group_shares(
        attributor_for(baseline_estimator, names).attribute(x_test).contributions, names
    )

    # Company-level bootstrap: resample companies, take all of their rows.
    company_rows: dict[int, list[int]] = defaultdict(list)
    for position, observation in enumerate(train):
        company_rows[observation.key.cik].append(position)
    companies = sorted(company_rows)

    rng = np.random.default_rng(RANDOM_SEED)
    samples: list[dict[str, float]] = []
    for _ in range(BOOTSTRAP_FITS):
        drawn = rng.choice(companies, size=len(companies), replace=True)
        rows = np.concatenate([company_rows[int(c)] for c in drawn])
        if len(np.unique(y_train[rows])) < 2:
            continue
        estimator = spec.estimator_factory().fit(x_train[rows], y_train[rows])
        samples.append(
            _group_shares(attributor_for(estimator, names).attribute(x_test).contributions, names)
        )

    frame = pd.DataFrame(samples).fillna(0.0)
    ordered = sorted(baseline, key=lambda g: -baseline[g])
    baseline_ranks = pd.Series({g: i for i, g in enumerate(ordered)})
    rank_correlations = [
        float(
            pd.Series(row)
            .rank(ascending=False)
            .corr(baseline_ranks.rank(ascending=True), method="spearman")
        )
        for _, row in frame.iterrows()
    ]

    return {
        "fold": fold.name,
        "bootstrap_fits": len(samples),
        "resampled_by": "company",
        "baseline_shares": {g: round(baseline[g], 4) for g in ordered},
        "share_spread": {
            group: {
                "p05": round(float(frame[group].quantile(0.05)), 4),
                "p50": round(float(frame[group].quantile(0.50)), 4),
                "p95": round(float(frame[group].quantile(0.95)), 4),
            }
            for group in ordered
            if group in frame
        },
        "top_group_agreement": round(
            float(np.mean([max(s, key=s.get) == ordered[0] for s in samples])), 4
        ),
        "median_rank_correlation_with_baseline": round(float(np.median(rank_correlations)), 4),
    }


def ranking_analysis(spec: ModelSpec, observations: list[Observation], plan: Any) -> dict[str, Any]:
    """What the ranking looks like, and how much it moves year to year."""
    indices, scores, per_fold = run_walk_forward(spec, observations, plan)
    labels = np.array([observations[i].outcome.label for i in indices], dtype=int)

    alerts = []
    for rate in ALERT_RATES:
        k = max(1, int(round(rate * len(scores))))
        order = np.argsort(-scores, kind="stable")[:k]
        captured = int(labels[order].sum())
        alerts.append(
            {
                "alert_rate": rate,
                "reviewed": k,
                "events_captured": captured,
                "recall": round(captured / labels.sum(), 4),
                "precision": round(captured / k, 4),
                "rows_read_per_event": round(k / captured, 1) if captured else None,
            }
        )

    # Within-year percentile, then how far a company moves between consecutive years.
    percentile_by_key: dict[tuple[int, int], float] = {}
    for prediction in per_fold:
        fold_scores = np.array(prediction.scores)
        ranks = pd.Series(fold_scores).rank(pct=True).to_numpy()
        for position, observation_index in enumerate(prediction.indices):
            observation = observations[observation_index]
            percentile_by_key[(observation.key.cik, observation.key.prediction_date.year)] = float(
                ranks[position]
            )

    moves: list[float] = []
    for (cik, year), percentile in percentile_by_key.items():
        following = percentile_by_key.get((cik, year + 1))
        if following is not None:
            moves.append(abs(following - percentile))

    return {
        "score_distribution": {
            "min": round(float(scores.min()), 5),
            "p50": round(float(np.percentile(scores, 50)), 5),
            "p90": round(float(np.percentile(scores, 90)), 5),
            "p99": round(float(np.percentile(scores, 99)), 5),
            "max": round(float(scores.max()), 5),
            "share_above_0_5": round(float((scores > 0.5).mean()), 4),
            "note": "concentration in the tail is why the score is read as a rank (D-033)",
        },
        "alert_rate_table": alerts,
        "year_over_year_percentile_move": {
            "pairs": len(moves),
            "median_absolute_move": round(float(np.median(moves)), 4) if moves else None,
            "p90_absolute_move": round(float(np.percentile(moves, 90)), 4) if moves else None,
            "share_moving_over_25_points": (
                round(float(np.mean([m > 0.25 for m in moves])), 4) if moves else None
            ),
        },
    }


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    observations = load_panel()
    plan = walk_forward_folds(observations)
    assert_temporal_ordering(observations, plan)
    spec = next(s for s in build_model_specs() if s.name == PRIMARY_MODEL)

    logger.info("Attribution stability (%d bootstrap refits)...", BOOTSTRAP_FITS)
    stability = attribution_stability(spec, observations, plan)
    logger.info("Ranking analysis...")
    ranking = ranking_analysis(spec, observations, plan)

    summary = {"attribution_stability": stability, "ranking": ranking}
    (OUT_DIR / "stability_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Stability: %s", json.dumps(stability, indent=2))
    logger.info("Ranking: %s", json.dumps(ranking, indent=2))


if __name__ == "__main__":
    main()
