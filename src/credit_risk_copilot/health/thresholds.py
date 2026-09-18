"""Every tunable constant the financial-health engine uses, gathered in one
place (FR-10: "thresholds live in configuration, not hard-coded constants").

Each constant is a disclosed, documented, revisable engineering choice, not a
precision claim -- exactly like `ratios/engine.py`'s `_ZERO_TOLERANCE` and
`_INTEREST_COVERAGE_NEAR_ZERO_RATIO`. None of these are industry- or
company-specific (Phase 7 §27 defers that); they are the minimum noise floor
needed so a rule requires real magnitude/persistence/breadth before it
speaks, per the false-positive control the phase brief asks for (§38).
"""

from __future__ import annotations

#: How many of the most recent fiscal periods `analyze_financial_health`
#: considers when no explicit window is given. A trend is a claim about
#: *recent* deterioration, and `trend.py`'s direction is a first-to-last
#: comparison, so an arbitrarily old period would otherwise anchor the
#: comparison and let a two-decade secular drift present itself as a
#: monitoring signal (Phase 8 audit, D-024).
#:
#: 5 is chosen because: (a) it is the window a credit analyst conventionally
#: reads, and more than a filing itself presents (a 10-K carries 3 income-
#: statement years and 2 balance-sheet dates); (b) it leaves slack above
#: `MIN_CONSECUTIVE_PERIODS_FOR_TREND` so one missing year does not collapse
#: a trend to `INSUFFICIENT_DATA`; (c) on the real corpus it is a no-op for
#: every pre-Phase-8 caller, since a single filing never yields more than 4
#: periods -- so adopting it changed no existing result. Pass
#: `analysis_window=None` for the unbounded behaviour.
DEFAULT_ANALYSIS_WINDOW = 5

#: Minimum number of *consecutive* (gap-free) calculated periods before a
#: direction (increasing/decreasing/stable) is computed at all, matching
#: `docs/scope.md` §2's own MVP rule ("Trend analysis: requires >= 3
#: consecutive fiscal years ... fewer years -> insufficient_data"). This is
#: not a Phase 7 invention; it is an existing product decision Phase 7 must
#: honour, not rediscover.
MIN_CONSECUTIVE_PERIODS_FOR_TREND = 3

#: The minimum |percent_change| (first-to-last value across the qualifying
#: window) for a ratio to be called INCREASING/DECREASING rather than STABLE.
#: Applied to the *rate of change*, never to a ratio's absolute level (§11
#: explicitly forbids universal level thresholds like "D/E > 2 is bad") --
#: this only answers "did anything happen at all". 5% is a conservative
#: noise floor: real annual accounting figures rarely move less than this
#: without it being reporting noise rather than a real change, and a false
#: "trend" manufactured from a 1-2% wobble is exactly the false-positive risk
#: named in §38. Revisit with a company-specific volatility baseline (§27,
#: deferred) if evidence shows this is too coarse for some ratio.
STABLE_MAGNITUDE_THRESHOLD = 0.05

#: When the window's earliest value is within this of zero, `percent_change`
#: is undefined (mirrors `RatioChange.percent_change`'s own convention in
#: `ratios/models.py`) and direction falls back to comparing `absolute_change`
#: against this tiny float-noise epsilon instead of the 5% relative bar above
#: -- not a materiality threshold, just large enough to not call floating-
#: point rounding a "trend".
NEAR_ZERO_BASELINE_EPSILON = 1e-9
ABSOLUTE_CHANGE_NOISE_EPSILON = 1e-6

#: Epsilon a single period-over-period delta must exceed to count as a real
#: "increase" or "decrease" for persistence counting, as opposed to floating-
#: point noise. Deliberately much smaller than `STABLE_MAGNITUDE_THRESHOLD`:
#: persistence asks "which direction did each step go", not "was the step
#: big enough to matter" -- the cumulative magnitude check already owns that.
PERSISTENCE_DELTA_EPSILON = 1e-9

#: Robust (median/MAD) z-score above which the latest single-period move is
#: flagged UNUSUAL_MOVEMENT (§13, §22) -- an observation worth a human look,
#: never a claim about direction or cause. 3.0 is the conventional "clearly
#: outside the historical pattern" bar for a MAD-based robust z-score.
UNUSUAL_MOVEMENT_Z = 3.0

#: Minimum number of *prior* period-over-period deltas (i.e. periods_available
#: - 1, excluding the delta being tested) needed before UNUSUAL_MOVEMENT is
#: even attempted. A median/MAD computed from one or two prior deltas is not
#: a distribution (§28, §29) -- the check silently stays off below this, it
#: never fabricates significance from a tiny sample.
UNUSUAL_MOVEMENT_MIN_PRIOR_DELTAS = 3

#: MULTI_DIMENSION_DETERIORATION fires only when at least this many of the
#: five monitored dimensions (liquidity, leverage, profitability, coverage,
#: cash_flow) are independently DETERIORATING for the same report. Set to a
#: majority (3 of 5) rather than "any 2" so two dimensions moving together by
#: coincidence -- plausible given real ratios share inputs (e.g. leverage and
#: coverage both use debt-adjacent concepts) -- does not by itself manufacture
#: a cross-dimension alarm; only a genuinely broad-based move does (§38).
MULTI_DIMENSION_MIN_DIMENSIONS = 3

#: Minimum number of prior (non-latest) calculated values needed before a
#: historical baseline (median) is reported at all (§12). A "median" of one
#: value is just that value -- not a baseline to deviate from.
MIN_PRIOR_VALUES_FOR_BASELINE = 2
