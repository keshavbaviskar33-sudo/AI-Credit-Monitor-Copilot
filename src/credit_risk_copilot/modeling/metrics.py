"""Evaluation metrics chosen for a monitoring product, not a leaderboard.

## Why not accuracy

The event is rare -- a few percent of rows. A model that predicts "no
bankruptcy" for every company scores above 95% accuracy and is worth nothing.
Accuracy is not reported anywhere in this module.

## What the product actually needs

An analyst has a watchlist and finite attention. The operational question is
never "is this company going to fail" but **"of the companies I could look at
this quarter, which should I look at first, and how many do I have to read
before I have found most of the ones that matter?"** That makes this a
ranking problem first and a probability problem second, so:

- **ROC-AUC** -- overall ranking quality; the probability a randomly chosen
  future filer is ranked above a randomly chosen survivor. Reported because it
  is comparable across base rates and across the literature, with the caveat
  that it is optimistic-looking under heavy imbalance.
- **PR-AUC (average precision)** -- ranking quality *on the minority class*,
  which is the class the product exists for. Its baseline is the event rate
  itself, so it is quoted against that baseline rather than against 0.5.
- **Precision / recall at an alert rate** -- the metric that maps directly to
  a review queue. "If we flag the riskiest 5% of the book, what share of next
  year's bankruptcies is in that 5%?" is a question an analyst can act on;
  AUC is not.
- **Brier score and calibration** -- only meaningful if the model's output is
  going to be read as a probability. Reported with an explicit calibration
  curve so the report can say whether that reading is supported (§21).

## Confidence intervals, because the event count is small

With a few dozen test events, a difference of 0.03 AUC between two models is
noise. Every headline metric is reported with a bootstrap interval, resampled
over *companies* rather than rows, because rows from one company are not
independent draws.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

#: Share of the book an analyst reviews. 1% and 5% are realistic queue depths
#: for a watchlist; 10% is included as the point where "review everything
#: flagged" stops being cheap.
ALERT_RATES: tuple[float, ...] = (0.01, 0.05, 0.10)

#: Bootstrap resamples for the reported intervals. 1,000 is enough for a
#: 95% interval's endpoints to be stable to about +/-0.005 at this sample
#: size, and cheap on a few thousand rows.
BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 20260917


class AlertRateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_rate: float
    flagged: int
    precision: float
    recall: float
    events_captured: int
    #: How many rows an analyst reviews per event found -- the reciprocal of
    #: precision, stated the way a queue is actually experienced.
    rows_reviewed_per_event: float | None


class EvaluationResult(BaseModel):
    """Every metric for one set of scored observations."""

    model_config = ConfigDict(frozen=True)

    n_rows: int
    n_events: int
    n_companies: int
    event_rate: float
    roc_auc: float | None
    roc_auc_ci: tuple[float, float] | None
    pr_auc: float | None
    pr_auc_ci: tuple[float, float] | None
    #: PR-AUC of a random ranker, i.e. the event rate. PR-AUC is meaningless
    #: without it.
    pr_auc_baseline: float
    brier: float | None
    log_loss: float | None
    alert_rates: tuple[AlertRateResult, ...]
    calibration: tuple[tuple[float, float, int], ...]
    #: Slope and intercept of a logistic recalibration of the model's own
    #: log-odds. Slope 1 / intercept 0 is perfect; slope < 1 means the
    #: predictions are too extreme.
    calibration_slope: float | None
    calibration_intercept: float | None

    def headline(self) -> str:
        auc = f"{self.roc_auc:.3f}" if self.roc_auc is not None else "n/a"
        ap = f"{self.pr_auc:.3f}" if self.pr_auc is not None else "n/a"
        return (
            f"n={self.n_rows} events={self.n_events} ({self.event_rate:.2%}) "
            f"ROC-AUC={auc} PR-AUC={ap} (baseline {self.pr_auc_baseline:.3f})"
        )


def _alert_rate_result(
    y_true: np.ndarray, scores: np.ndarray, alert_rate: float
) -> AlertRateResult:
    n = len(scores)
    k = max(1, int(round(alert_rate * n)))
    # Rank descending; ties broken by original order, which is deterministic
    # because the caller supplies observations in a fixed order.
    order = np.argsort(-scores, kind="stable")[:k]
    captured = int(y_true[order].sum())
    total_events = int(y_true.sum())
    precision = captured / k
    return AlertRateResult(
        alert_rate=alert_rate,
        flagged=k,
        precision=precision,
        recall=(captured / total_events) if total_events else 0.0,
        events_captured=captured,
        rows_reviewed_per_event=(1.0 / precision) if precision > 0 else None,
    )


def is_probability_scale(scores: np.ndarray) -> bool:
    """Whether `scores` can be read as probabilities at all.

    The heuristic baselines rank on a raw ratio -- `debt_to_assets` is
    routinely above 1, `ebit_to_assets` is routinely negative -- so they
    produce a valid *ordering* and no probability. Brier score, log loss and
    calibration are undefined for such a score, and this is the check that
    keeps them from being computed (or crashing) rather than silently
    rescaling a ranking into a fake probability.
    """
    return bool(scores.size) and bool((scores >= 0).all() and (scores <= 1).all())


def _calibration_curve(
    y_true: np.ndarray, scores: np.ndarray, bins: int = 5
) -> tuple[tuple[float, float, int], ...]:
    """Mean predicted vs observed rate per quantile bin.

    Quantile bins, not equal-width: with a heavily skewed score distribution
    equal-width bins put almost every row in the lowest bin and report nothing.
    Duplicate edges are collapsed first -- a score with heavy ties (most rows
    sharing one low value) produces repeated quantiles, and keeping them would
    yield a run of empty bins and a curve with a single usable point.
    """
    if len(scores) < bins * 2:
        return ()
    unique_edges = np.unique(np.quantile(scores, np.linspace(0, 1, bins + 1)))
    if unique_edges.size < 2:
        return ()
    # Drop the top quantile as a lower edge (it would open a bin holding only
    # the maximum row) -- unless doing so would leave a single bin, which is
    # what happens when the score takes only two distinct values.
    lower_edges = unique_edges[:-1] if unique_edges.size > 2 else unique_edges
    edges = np.append(lower_edges, np.inf)
    rows: list[tuple[float, float, int]] = []
    for low, high in zip(edges[:-1], edges[1:], strict=False):
        mask = (scores >= low) & (scores < high)
        if not mask.any():
            continue
        rows.append((float(scores[mask].mean()), float(y_true[mask].mean()), int(mask.sum())))
    return tuple(rows)


def _calibration_fit(y_true: np.ndarray, scores: np.ndarray) -> tuple[float | None, float | None]:
    """Logistic recalibration of the model's own log-odds (Cox calibration)."""
    from sklearn.linear_model import LogisticRegression

    if len(np.unique(y_true)) < 2 or not is_probability_scale(scores):
        return None, None
    clipped = np.clip(scores, 1e-6, 1 - 1e-6)
    logit = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    # `C=inf` is the unpenalised fit; sklearn 1.8 deprecated `penalty=None`
    # in favour of expressing it this way.
    fitted = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000).fit(logit, y_true)
    return float(fitted.coef_[0][0]), float(fitted.intercept_[0])


def _bootstrap_ci(
    y_true: np.ndarray,
    scores: np.ndarray,
    groups: np.ndarray,
    metric: str,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval, resampling companies with replacement.

    Resampling rows would treat a company's ten filings as ten independent
    observations and report an interval far too narrow.
    """
    unique_groups = np.unique(groups)
    if len(unique_groups) < 5:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    index_by_group = {g: np.flatnonzero(groups == g) for g in unique_groups}
    values: list[float] = []

    for _ in range(BOOTSTRAP_SAMPLES):
        drawn = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        indices = np.concatenate([index_by_group[g] for g in drawn])
        sample_y, sample_s = y_true[indices], scores[indices]
        if len(np.unique(sample_y)) < 2:
            continue
        values.append(
            float(roc_auc_score(sample_y, sample_s))
            if metric == "roc_auc"
            else float(average_precision_score(sample_y, sample_s))
        )

    if len(values) < BOOTSTRAP_SAMPLES // 10:
        return None
    return (float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5)))


def evaluate(
    y_true: Sequence[int],
    scores: Sequence[float],
    companies: Sequence[int],
    *,
    bootstrap: bool = True,
) -> EvaluationResult:
    """Score one set of predictions. `companies` is the CIK per row, used for
    grouped bootstrap resampling."""
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(scores, dtype=float)
    g = np.asarray(companies)

    n_events = int(y.sum())
    event_rate = float(y.mean()) if len(y) else 0.0
    both_classes = len(np.unique(y)) == 2
    # A heuristic baseline ranks on a raw ratio, not a probability. Ranking
    # metrics still apply; probability metrics do not, and are reported as
    # `None` rather than computed on a rescaled fiction.
    probabilistic = both_classes and is_probability_scale(s)
    slope, intercept = _calibration_fit(y, s) if probabilistic else (None, None)

    return EvaluationResult(
        n_rows=len(y),
        n_events=n_events,
        n_companies=int(len(np.unique(g))),
        event_rate=event_rate,
        roc_auc=float(roc_auc_score(y, s)) if both_classes else None,
        roc_auc_ci=_bootstrap_ci(y, s, g, "roc_auc") if both_classes and bootstrap else None,
        pr_auc=float(average_precision_score(y, s)) if both_classes else None,
        pr_auc_ci=_bootstrap_ci(y, s, g, "pr_auc") if both_classes and bootstrap else None,
        pr_auc_baseline=event_rate,
        brier=float(brier_score_loss(y, s)) if probabilistic else None,
        log_loss=(
            float(log_loss(y, np.clip(s, 1e-9, 1 - 1e-9), labels=[0, 1])) if probabilistic else None
        ),
        alert_rates=tuple(_alert_rate_result(y, s, rate) for rate in ALERT_RATES),
        calibration=_calibration_curve(y, s) if probabilistic else (),
        calibration_slope=slope,
        calibration_intercept=intercept,
    )


def delta_auc_ci(
    y_true: Sequence[int],
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    companies: Sequence[int],
) -> tuple[float, float, float] | None:
    """Paired bootstrap interval for ROC-AUC(b) - ROC-AUC(a).

    Comparing two models by whether their separate confidence intervals
    overlap is the wrong test and usually too conservative; the paired
    difference is the right one because both models see identical rows.
    Returns (point estimate, lower, upper).
    """
    y = np.asarray(y_true, dtype=int)
    a = np.asarray(scores_a, dtype=float)
    b = np.asarray(scores_b, dtype=float)
    g = np.asarray(companies)
    if len(np.unique(y)) < 2:
        return None

    point = float(roc_auc_score(y, b) - roc_auc_score(y, a))
    unique_groups = np.unique(g)
    if len(unique_groups) < 5:
        return None

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    index_by_group = {grp: np.flatnonzero(g == grp) for grp in unique_groups}
    deltas: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        drawn = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        indices = np.concatenate([index_by_group[grp] for grp in drawn])
        sample_y = y[indices]
        if len(np.unique(sample_y)) < 2:
            continue
        deltas.append(
            float(roc_auc_score(sample_y, b[indices]) - roc_auc_score(sample_y, a[indices]))
        )
    if len(deltas) < BOOTSTRAP_SAMPLES // 10:
        return None
    return (point, float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
