"""The trend engine: one ratio's `RatioResult` history -> a `RatioTrend`
(§6, §7, §12, §13, §14, §17, §21, §28, §29 of the phase brief).

Pure arithmetic and explicit gap/threshold logic over already-calculated
`RatioResult`s -- no LLM, no ML, no financial judgement beyond the disclosed
`EconomicDirection` interpretation (§31, §32).

## Why this module sorts its own input

`CanonicalFilingFacts.period_labels` follows XBRL fact insertion order, not
fiscal order -- confirmed against the real golden-set corpus, e.g.
iHeartMedia's own filing reports `('FY2014', 'FY2015', 'FY2016', 'FY2013')`,
oldest year *last*. `ratios/engine.py::calculate_ratio_history` and
`ratio_history_changes` both assume chronological input and are fixed here
to sort defensively (see that module's own docstring), but this engine never
relies on a caller having done so upstream: every `RatioTrend` is computed
from `results` re-sorted by this module's own `fiscal_sort_key`, regardless
of what order it arrived in. Trusting an unsorted series would silently
compute nonsense deltas -- exactly the kind of hidden bug §39's "every
signal should have deterministic evidence" is meant to rule out.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from statistics import median

from credit_risk_copilot.health.direction import economic_direction
from credit_risk_copilot.health.models import (
    DataQualityLevel,
    HistoryDepth,
    RatioDirection,
    RatioTrend,
    TrendDirection,
)
from credit_risk_copilot.health.thresholds import (
    ABSOLUTE_CHANGE_NOISE_EPSILON,
    MIN_CONSECUTIVE_PERIODS_FOR_TREND,
    MIN_PRIOR_VALUES_FOR_BASELINE,
    NEAR_ZERO_BASELINE_EPSILON,
    PERSISTENCE_DELTA_EPSILON,
    STABLE_MAGNITUDE_THRESHOLD,
    UNUSUAL_MOVEMENT_MIN_PRIOR_DELTAS,
    UNUSUAL_MOVEMENT_Z,
)
from credit_risk_copilot.ratios.engine import ratio_history_changes
from credit_risk_copilot.ratios.models import RatioResult, RatioStatus, WarningCode

_YEAR_RE = re.compile(r"\d{4}")


def fiscal_sort_key(period_label: str) -> int:
    """Chronological sort key for an annual period label like `"FY2025"`
    (D-007: annual-only scope). Falls back to 0 for an unparseable label
    rather than raising -- a caller passing a malformed label gets a stable,
    if wrong, position rather than a crash mid-analysis; nothing in this
    engine treats period ordering as unchecked-safe in the first place."""
    match = _YEAR_RE.search(period_label)
    return int(match.group()) if match else 0


def _sorted_results(results: Sequence[RatioResult]) -> tuple[RatioResult, ...]:
    return tuple(sorted(results, key=lambda r: fiscal_sort_key(r.period_label)))


def _calculated_indices(results: tuple[RatioResult, ...]) -> list[int]:
    return [i for i, r in enumerate(results) if r.status is RatioStatus.CALCULATED]


def _gap_periods(results: tuple[RatioResult, ...], calculated: list[int]) -> tuple[str, ...]:
    if len(calculated) < 2:
        return ()
    first, last = calculated[0], calculated[-1]
    return tuple(
        results[i].period_label for i in range(first, last + 1) if i not in set(calculated)
    )


def _has_negative_equity(results: tuple[RatioResult, ...]) -> bool:
    return any(
        r.status is RatioStatus.CALCULATED
        and any(w.code is WarningCode.NEGATIVE_EQUITY for w in r.warnings)
        for r in results
    )


def _data_quality(results: tuple[RatioResult, ...]) -> DataQualityLevel:
    codes = {w.code for r in results if r.status is RatioStatus.CALCULATED for w in r.warnings}
    if WarningCode.LOW_CONFIDENCE_INPUT in codes:
        return DataQualityLevel.LOW_CONFIDENCE
    if WarningCode.MANUAL_INPUT in codes:
        return DataQualityLevel.MANUALLY_ADJUSTED
    if WarningCode.DERIVED_INPUT in codes:
        return DataQualityLevel.DERIVED_INPUTS
    return DataQualityLevel.GOOD


def _direction_and_magnitude(
    values: list[float],
) -> tuple[TrendDirection, float | None, float | None]:
    """`values` is the gap-free, sufficiently-long calculated window, in
    chronological order. Direction is always taken from `absolute_change`'s
    own sign -- never from `percent_change`'s, which (matching
    `RatioChange.percent_change`'s existing sign convention in
    `ratios/models.py`) divides by the *signed* first value and so can point
    the "wrong" way when that value is negative (e.g. a net margin moving
    from -20% to -10% is a real improvement, absolute_change=+0.10, but
    -0.10/-0.20 % change carries an apparently negative sign). `percent_change`
    is still returned, unchanged, as an auxiliary magnitude figure; only its
    absolute value is ever used to decide anything here."""
    first, last = values[0], values[-1]
    absolute_change = last - first
    percent_change = absolute_change / first if abs(first) >= NEAR_ZERO_BASELINE_EPSILON else None

    if percent_change is not None:
        is_moving = abs(percent_change) >= STABLE_MAGNITUDE_THRESHOLD
    else:
        is_moving = abs(absolute_change) >= ABSOLUTE_CHANGE_NOISE_EPSILON

    if not is_moving:
        direction = TrendDirection.STABLE
    elif absolute_change > 0:
        direction = TrendDirection.INCREASING
    else:
        direction = TrendDirection.DECREASING
    return direction, absolute_change, percent_change


def _persistence(values: list[float], direction: TrendDirection) -> int:
    if direction not in (TrendDirection.INCREASING, TrendDirection.DECREASING):
        return 0
    target = 1 if direction is TrendDirection.INCREASING else -1
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    count = 0
    for delta in reversed(deltas):
        sign = (
            1
            if delta > PERSISTENCE_DELTA_EPSILON
            else (-1 if delta < -PERSISTENCE_DELTA_EPSILON else 0)
        )
        if sign != target:
            break
        count += 1
    return count


def _baseline(
    results: tuple[RatioResult, ...],
) -> tuple[float | None, float | None]:
    """Historical median/deviation (§12) over *every* `CALCULATED` value in
    `results`, gaps or not -- unlike `direction`, a descriptive baseline does
    not need a contiguous window to be meaningful."""
    calculated_values = [
        r.value for r in results if r.status is RatioStatus.CALCULATED and r.value is not None
    ]
    if not calculated_values:
        return None, None
    latest = calculated_values[-1]
    prior = calculated_values[:-1]
    if len(prior) < MIN_PRIOR_VALUES_FOR_BASELINE:
        return None, None
    baseline_median = median(prior)
    return baseline_median, latest - baseline_median


def _unusual_movement(results: tuple[RatioResult, ...]) -> bool:
    """Robust (median/MAD) z-score flag on the latest genuinely adjacent
    period-over-period move (§13, §22). Reuses `ratio_history_changes`
    verbatim -- it already refuses to manufacture a delta across a gap, so
    every value fed into the MAD here is a real single-period move."""
    changes = ratio_history_changes(results)
    if not changes or not results or results[-1].status is not RatioStatus.CALCULATED:
        return False
    if changes[-1].to_period != results[-1].period_label:
        return False  # the latest period's own move isn't in `changes` (a gap sits right before it)
    prior = [c.absolute_change for c in changes[:-1] if c.absolute_change is not None]
    if len(prior) < UNUSUAL_MOVEMENT_MIN_PRIOR_DELTAS:
        return False
    latest_delta = changes[-1].absolute_change
    if latest_delta is None:  # pragma: no cover
        # Defensive only: `ratio_history_changes` only ever produces a
        # `RatioChange` from two `CALCULATED` results, and `CALCULATED`
        # guarantees `value is not None` (`ratios/engine.py`), so
        # `absolute_change` is never actually `None` here -- kept because
        # the field's type (`float | None`) allows it.
        return False
    center = median(prior)
    mad = median([abs(p - center) for p in prior])
    if mad > 0:
        z = 0.6745 * (latest_delta - center) / mad
        return abs(z) > UNUSUAL_MOVEMENT_Z
    return abs(latest_delta - center) > ABSOLUTE_CHANGE_NOISE_EPSILON


def compute_ratio_trend(
    ratio_id: str, results: Sequence[RatioResult], ratio_direction: RatioDirection
) -> RatioTrend:
    """One ratio's full trend analysis. `results` may be given in any order
    and may include non-`CALCULATED` periods -- both are handled explicitly,
    never assumed away."""
    sorted_results = _sorted_results(results)
    calculated = _calculated_indices(sorted_results)
    periods_available = len(calculated)
    gap_periods = _gap_periods(sorted_results, calculated)
    has_gap = bool(gap_periods)
    negative_equity = _has_negative_equity(sorted_results)
    baseline_median, deviation_from_baseline = _baseline(sorted_results)
    data_quality = _data_quality(sorted_results)
    unusual_movement = _unusual_movement(sorted_results)

    absolute_change: float | None = None
    percent_change: float | None = None
    persistence = 0
    reason: str | None = None

    if negative_equity:
        direction = TrendDirection.NOT_MEANINGFUL
        reason = (
            "A negative-equity denominator appears in this window; the conventional "
            "increasing/decreasing interpretation does not apply to this ratio here."
        )
        history_depth = (
            HistoryDepth.LIMITED
            if periods_available < MIN_CONSECUTIVE_PERIODS_FOR_TREND
            else HistoryDepth.ADEQUATE
        )
    elif periods_available == 0:
        direction = TrendDirection.INSUFFICIENT_DATA
        reason = "No period in the requested window calculated a value."
        history_depth = HistoryDepth.LIMITED
    elif has_gap:
        direction = TrendDirection.DISCONTINUOUS_HISTORY
        reason = (
            f"Not calculated for: {', '.join(gap_periods)} -- a trend is not computed across a gap."
        )
        history_depth = (
            HistoryDepth.LIMITED
            if periods_available < MIN_CONSECUTIVE_PERIODS_FOR_TREND
            else HistoryDepth.ADEQUATE
        )
    elif periods_available < MIN_CONSECUTIVE_PERIODS_FOR_TREND:
        direction = TrendDirection.INSUFFICIENT_DATA
        reason = (
            f"Only {periods_available} consecutive calculated period(s); "
            f"{MIN_CONSECUTIVE_PERIODS_FOR_TREND} are required for a trend (docs/scope.md)."
        )
        history_depth = HistoryDepth.LIMITED
    else:
        values = [sorted_results[i].value for i in calculated]
        assert all(v is not None for v in values)
        direction, absolute_change, percent_change = _direction_and_magnitude(values)  # type: ignore[arg-type]
        persistence = _persistence(values, direction)  # type: ignore[arg-type]
        history_depth = HistoryDepth.ADEQUATE

    return RatioTrend(
        ratio_id=ratio_id,
        results=sorted_results,
        direction=direction,
        economic_direction=economic_direction(direction, ratio_direction),
        periods_available=periods_available,
        history_depth=history_depth,
        has_gap=has_gap,
        gap_periods=gap_periods,
        absolute_change=absolute_change,
        percent_change=percent_change,
        persistence=persistence,
        baseline_median=baseline_median,
        deviation_from_baseline=deviation_from_baseline,
        unusual_movement=unusual_movement,
        negative_equity=negative_equity,
        data_quality=data_quality,
        reason=reason,
    )
