# Financial Health & Early-Warning Analysis — Phase 7

| | |
|---|---|
| **Status** | v1.0 — Phase 7 |
| **Date** | 2026-09-17 |
| **Related** | [D-022](decision_log.md) · [D-023](decision_log.md) · [ratios.md](ratios.md) (the Phase 6 → 7 interface) · [scope.md §2](scope.md) · [M-3](#7-m-3--real-corpus-evaluation) |

Phase 6 answers "what does the ratio equal, for one period" — a
`RatioResult`. Phase 7 answers "how is it changing, and what does that
change mean for financial health" — deterministic trend statistics and
structured early-warning signals, built entirely from `RatioResult`/
`RatioChange` objects Phase 6 already computed. Code lives in
`src/credit_risk_copilot/health/`.

Phase 7 does **not** predict default, compute a composite score, or decide
whether a company is creditworthy. That is Phase 8 onward.

## 1. The Phase 6 → 7 interface

```python
from credit_risk_copilot.health import analyze_financial_health

health = analyze_financial_health(company, ratio_history)
```

`ratio_history` is exactly what Phase 6's `ratios_for_filing`,
`ratios_from_facts` or `calculate_ratio_history` already return —
`ratio_id -> tuple[RatioResult, ...]` per period. `health/` imports only
`credit_risk_copilot.ratios` (never `financials`, `resolver`, `xbrl` or
`extraction`) — deleting every Phase 4/5 module would not break this
package, mirroring the same discipline `ratios/` holds toward Phase 5.

## 2. Health dimensions

Exactly the five Phase 6 ratio categories — derived from
`ratios/registry.py`, never redeclared, so a new ratio's category is
automatically its dimension:

| Dimension | Ratios |
|---|---|
| Liquidity | Current Ratio, Quick Ratio |
| Leverage | Debt-to-Equity, Debt-to-Assets, Liabilities-to-Assets |
| Profitability | Gross/Operating/Net Margin, ROA, ROE |
| Coverage | Interest Coverage |
| Cash flow | OCF-to-Debt, OCF-to-Revenue |

Each dimension gets a `DimensionStatus`: `IMPROVING`, `STABLE`,
`DETERIORATING`, `MIXED` (at least one ratio improving *and* at least one
deteriorating — surfaced, never netted into a false single direction) or
`INSUFFICIENT_DATA` (no ratio in the dimension reached a conclusive
direction). There is deliberately no composite score across dimensions —
a single "financial health = 63/100" number was considered and rejected
(phase brief §5, §25): it would hide exactly the information a monitoring
analyst needs (*which* dimension moved, and how much).

## 3. Economic direction: ratio direction is not universal

A rising Debt-to-Equity is weaker; a rising Current Ratio is stronger.
`health/direction.py::RATIO_DIRECTIONS` gives each of the 13 ratios an
explicit `RatioDirection` (`HIGHER_IS_STRONGER` or `LOWER_IS_STRONGER`) —
only the three leverage ratios are `LOWER_IS_STRONGER`; everything else is
`HIGHER_IS_STRONGER`. `TrendDirection` (what the number did) and
`EconomicDirection` (what that means) are kept as two separate fields on
every `RatioTrend`, never collapsed into one "risk" value — `direction`
alone can never tell a caller whether increasing is good.

This table deliberately lives in `health/`, not `ratios/registry.py`:
Phase 6 states what a ratio equals, never whether that is stronger or
weaker (`ratios.md` §1). A completeness test
(`test_health_direction.py::test_every_ratio_in_the_catalog_has_a_direction`)
checks every `RATIO_DEFINITIONS` id has an entry here, so the two catalogs
cannot silently drift apart if Phase 6's ratio catalog changes.

## 4. Trend methodology

`health/trend.py::compute_ratio_trend` takes one ratio's `RatioResult`
history (any order, any mix of statuses) and returns a `RatioTrend`.

### Direction

```
INCREASING | DECREASING | STABLE | NOT_MEANINGFUL | INSUFFICIENT_DATA | DISCONTINUOUS_HISTORY
```

Computed only over a **gap-free window of at least 3 consecutive calculated
periods** — `docs/scope.md` §2's existing MVP rule ("Trend analysis:
requires ≥ 3 consecutive fiscal years... fewer years → `insufficient_data`
for trends"), not a Phase 7 invention. A gap anywhere between the earliest
and latest calculated period in the requested window forces
`DISCONTINUOUS_HISTORY` regardless of how many calculated periods exist in
total — a missing year must never look like stability (§17), and a trend is
never computed across it.

Direction is decided by `absolute_change`'s own sign, and only fires
`INCREASING`/`DECREASING` when `|percent_change|` (first-to-last value
across the window) clears `STABLE_MAGNITUDE_THRESHOLD` (5%) — a noise
floor on the *rate of change*, never on a ratio's absolute level (the
universal-threshold pattern §11 explicitly forbids, e.g. "D/E > 2 is bad").
When the window's earliest value is within `NEAR_ZERO_BASELINE_EPSILON` of
zero, `percent_change` is undefined (matching `RatioChange.percent_change`'s
own convention) and the check falls back to a tiny absolute-change epsilon.

**A note on `percent_change`'s sign.** It divides by the *signed* earliest
value, exactly like `RatioChange.percent_change` already does — so on a
ratio whose baseline is negative (a net margin recovering from -481% to
-50%, for instance) its sign can disagree with `absolute_change`'s.
`direction` is always taken from `absolute_change`, never from
`percent_change`'s sign, and `RatioTrend.explain()` omits the percentage
from its printed line whenever the two signs disagree, rather than printing
a self-contradictory `"Change: -5.954 (+6988.0%)"` — found by manually
inspecting the real corpus (SandRidge FY2015 operating margin) during this
phase's own real-corpus evaluation step, see §7.

### Magnitude and persistence

`absolute_change`/`percent_change` are first-to-last across the qualifying
window (matches the phase brief's own worked example almost to the decimal:
Debt-to-Equity 1.02x → 1.34x → 1.72x, "+68.6%"). `persistence` counts
consecutive same-direction period-over-period moves ending at the latest
period — distinguishes `0.8 → 1.0 → 1.3 → 1.7` (persistence 3) from
`0.9 → 1.2 → 1.0 → 1.1` (net move still up, but persistence 1: only the
trailing increase counts).

### Baseline

`baseline_median`/`deviation_from_baseline` (§12): the median of every
*other* calculated value in the ratio's full history (gaps or not — a
descriptive statistic does not need a contiguous window the way a trend
claim does) versus the latest value. `None` below 2 prior values — a
median of one value is not a baseline.

### Unusual movement

A robust (median/MAD) z-score on the latest genuinely adjacent
period-over-period move, reusing `ratios.ratio_history_changes` verbatim so
every delta fed into the statistic is a real single-period move, never one
manufactured across a gap. Requires at least 3 prior deltas (5 total
periods) before it is even attempted (§28/§29: a MAD from one or two prior
deltas is not a distribution) — on this corpus (typically 3-4 periods per
filing) it rarely has enough history to fire; see §7.

### History depth

`LIMITED` (fewer than 3 gap-free calculated periods) or `ADEQUATE`
(3 or more) — named `history_depth`, not `confidence`: it is a fact about
sample size, not a statistical confidence claim this engine can make (§29).

## 5. Negative equity and other pathological ratios (§20, §21)

Debt-to-Equity and ROE are calculated (with a `NEGATIVE_EQUITY` warning)
even when equity is negative — Phase 6's own decision (D-019). But a D/E
series that crosses or sits at negative equity cannot be read with the
ordinary "lower is stronger" convention: `-6x → -5x → -4x` is numerically
increasing, not a leverage improvement. Whenever a `NEGATIVE_EQUITY`
warning appears **anywhere** in the analyzed window, `direction` is forced
to `NOT_MEANINGFUL` for that ratio — mirroring
`docs/product_requirements.md` §6.1's own `not_meaningful` ratio status —
and a dedicated `NEGATIVE_EQUITY` signal carries the raw fact instead of a
fabricated direction claim.

## 6. Signal catalog

| `SignalCode` | Fires when |
|---|---|
| `LIQUIDITY_DETERIORATION` | Current Ratio or Quick Ratio `DETERIORATING` |
| `LEVERAGE_DETERIORATION` | Debt-to-Equity, Debt-to-Assets or Liabilities-to-Assets `DETERIORATING` |
| `MARGIN_COMPRESSION` | Gross, Operating or Net Margin `DETERIORATING` |
| `PROFITABILITY_DETERIORATION` | ROA or ROE `DETERIORATING` — kept apart from `MARGIN_COMPRESSION`: a return ratio can deteriorate from an asset/equity-base change with margins flat |
| `INTEREST_COVERAGE_DECLINE` | Interest Coverage `DETERIORATING` |
| `CASH_FLOW_WEAKENING` | OCF-to-Debt or OCF-to-Revenue `DETERIORATING` |
| `NEGATIVE_EQUITY` | A `NEGATIVE_EQUITY` `RatioWarning` anywhere in the window (§5 above) |
| `UNUSUAL_MOVEMENT` | Robust z-score outlier on the latest single-period move (§4, §22) — an observation, never a claim about direction or cause |
| `MULTI_DIMENSION_DETERIORATION` | At least `MULTI_DIMENSION_MIN_DIMENSIONS` (3 of 5) dimensions independently `DETERIORATING` for the same report |

Persistence (how many consecutive periods) is a *field* on the signal, not
a separate code per persistence level — a second taxonomy axis would be
exactly the "giant taxonomy" the phase brief warns against (§10). Every
signal carries its `RatioTrend` (or, for `MULTI_DIMENSION_DETERIORATION`,
the affected dimension names) as evidence — nothing is asserted without a
traceable ratio, period and value.

### Why `MULTI_DIMENSION_MIN_DIMENSIONS = 3`

A majority (3 of 5), not "any 2": two dimensions moving together by
coincidence is plausible given real ratios share inputs (leverage and
coverage both use debt-adjacent concepts), so requiring a majority avoids
manufacturing a cross-dimension alarm from what could be two correlated
ratios rather than a genuinely broad-based move (§38's false-positive
control).

## 7. M-3 — real-corpus evaluation

`scripts/evaluate_financial_health.py` runs `analyze_financial_health` over
all 12 golden-set filings (156 ratio-trend slots: 12 filings × 13 ratios),
entirely from cache, and writes `qm03_ratio_trends.csv`, `qm03_signals.csv`,
`qm03_dimensions.csv` and `qm03_summary.json` to
`data/processed/golden_set/` (gitignored, rerun the script to reproduce).

```
filings: 12
ratio_trend_slots: 156
conclusive_direction_rate: 40.4%   (increasing 26, decreasing 26, stable 11)
insufficient_data_count: 87        (55.8% of all slots)
discontinuous_history_count: 0
not_meaningful_count: 6            (all negative-equity D/E or ROE)
adequate_history_rate: 40.4%
total_signals: 37
```

**The dominant finding is `INSUFFICIENT_DATA`, not a signal count, and that
is expected, not a defect.** `ratios.md` §6 already measured that
comparative-year coverage per ratio ranges 35-71% on this same corpus, with
liquidity/leverage ratios (needing `total_debt`/`current_assets`/
`current_liabilities`) at the low end. `ratios_for_filing` gives each
filing only its own XBRL comparative columns (2-4 fiscal years per filing,
not a multi-filing company history), so most ratios in most filings never
reach the 3 consecutive calculated periods `docs/scope.md` requires for a
trend. Concretely: **every one of the 12 filings has `INSUFFICIENT_DATA`
liquidity** — verified by hand (Walmart: Current Ratio calculated only for
its 2 most recent periods, 2 short of the 3-period bar) — not a bug, the
same Phase 5 tag-completeness gap `ratios.md` §6 already named. Phase 8+
should expect this same shape: short, filer-dependent trend histories from
single-filing analysis, materially thinner for leverage/liquidity than for
margin ratios.

`discontinuous_history_count = 0` on this corpus: gaps in Phase 5's
comparative-year resolution apparently occur at the *edge* of a filing's
reported window (older years simply absent) rather than in the *middle* of
an otherwise-resolved run, on these 12 filings — `DISCONTINUOUS_HISTORY`'s
logic is unit-tested (a synthetic missing middle year) but not yet observed
on this real corpus; worth re-checking as the corpus grows.

**Manual inspection (§8/§9 of the phase brief) across all 12 filings found
no false positives:**

- Peabody Energy and Frontier Communications (the corpus's distressed
  cohort) show deterioration across 4-5 of 5 dimensions, with
  `MULTI_DIMENSION_DETERIORATION` firing — matches their known real-world
  distress.
- Walmart and Pfizer show 0 signals, every conclusive dimension
  `IMPROVING`/`STABLE` — matches their known stability over this window.
- UPS's 5 signals (margin compression, interest coverage decline, cash
  flow weakening, `MULTI_DIMENSION_DETERIORATION`) are each backed by a
  real 11-32% multi-period move with persistence ≥ 2 — a genuine freight
  slowdown, not noise crossing the 5% threshold by chance.
- SandRidge Energy FY2015 (the same real impairment event `ratios.md` §8
  stress-tested) correctly produces `NEGATIVE_EQUITY` on both
  Debt-to-Equity and ROE rather than a fabricated "leverage improved"
  claim, and `MARGIN_COMPRESSION`/`INTEREST_COVERAGE_DECLINE` from the real
  impairment — this inspection is also what surfaced the `percent_change`
  sign-display bug fixed in §4 above.

`UNUSUAL_MOVEMENT` never fired on this corpus (needs 5 consecutive
calculated periods; the corpus's own comparative-year coverage rarely
reaches that for any one ratio) — expected given §4's own caveat, not a
gap to close without more history.

## 7a. M-4 — the same corpus on the multi-filing path (M-4)

§7's numbers describe **one accession per company**. The Phase 1-7
architecture audit found that the multi-filing, point-in-time path
(`CompanyFinancials.as_of()`) — which [D-001](decision_log.md) monitoring and
[D-008](decision_log.md) as-filed both depend on — had never been run on real
data, and that §7's dominant `INSUFFICIENT_DATA` finding was therefore
measuring the harness as much as the data.

`scripts/evaluate_multi_filing.py` runs both paths over the same 12 companies
and the same cutoff dates. **The single-filing column reproduces §7 and
`ratios.md` §6 exactly, which is what validates the harness:**

| | Single filing (§7) | Multi-filing (`as_of`) |
|---|---:|---:|
| Filings resolved | 12 | **153** (116 skipped: 112 carry no XBRL facts, 4 resolve no annual period) |
| Ratio slots calculated | 362 / 598 — 60.5% | 1,953 / 2,405 — **81.2%** |
| Conclusive trend directions | 63 / 156 — 40.4% | 143 / 156 — **91.7%** |
| `INSUFFICIENT_DATA` dimensions | 21 / 60 | **0 / 60** |
| Signals fired | 37 | **153** |

So §7's "every one of the 12 filings has `INSUFFICIENT_DATA` liquidity" is
**not a property of SEC data**. It is what happens when the engine is handed a
single accession's 2-4 comparative columns. Given a company's own filing
history it disappears completely.

Two things this does **not** license. First, the analysis window
([D-024](decision_log.md)) is now load-bearing rather than cosmetic: with 9-20
periods available, "the trend" is meaningless until the span is stated. Second,
§7's false-positive claim covered 37 signals and does not transfer to 153 — so
it was redone, below.

### 7a.1 False-positive re-inspection

`scripts/validate_multi_filing.py` dumps every signal with its series,
magnitude, persistence and evidence (`m4_signal_inspection.csv`), tagged by the
golden set's own `distressed` / `healthy` cohort labels. A signal on a
distressed filing (each is that company's last annual report before a real
bankruptcy petition) is expected; a signal on a healthy one is a
**false-positive candidate** that has to be read against the numbers — a
healthy company can still genuinely deteriorate in one dimension.

**Distribution:** 97 signals on the 6 distressed companies (Peabody 20,
SandRidge 20, Frontier 19, iHeartMedia 16, Pyxus 12, Expand 10), 56 on the 6
healthy ones. 63 of the 153 are `UNUSUAL_MOVEMENT` or `NEGATIVE_EQUITY`, which
are statements of fact rather than trend judgements — they either hold over the
window or they do not, so they cannot be false positives in the threshold
sense and are counted separately.

**All 56 healthy-cohort signals were read individually.** The large majority
are true positives with real economic content, and several are ones the
single-filing path missed entirely:

- **Pfizer: 0 signals single-filing → 10 multi-filing, every one real.** Net
  margin 27.0% → 3.6% (FY2023) → 12.4%, ROA 12.1% → 0.9% → 3.7%, interest
  coverage 19.8× → 1.5× → 3.8×, debt/assets 0.21 → 0.31. That is the post-COVID
  revenue collapse plus the Seagen acquisition, and §7 reporting "0 signals,
  every dimension improving/stable" for Pfizer was a **false negative** the
  multi-filing path corrects.
- **UPS (11) and Tesla (12)** show multi-year margin and return compression
  with persistence 3-4 — UPS operating margin 13.2% → 8.9%, Tesla operating
  margin 12.1% → 4.6%. Both are real and well documented.
- **Coca-Cola's two cash-flow signals** (OCF/revenue 32.7% → 15.5%) are real.
- **Walmart's and Apple's liquidity signals** are arithmetically correct
  declines of low credit materiality — which is the intended behaviour, since
  [D-022](decision_log.md) deliberately gives signals no severity and no score.

**Three signals, all healthy-cohort, are endpoint artefacts** — the only
genuine weakness found:

| Company | Signal | Series | Change | Fitted slope |
|---|---|---|---:|---:|
| Walmart | `MARGIN_COMPRESSION` on operating margin | 4.53, 3.34, 4.17, 4.31, 4.18% | −7.7% | **+0.007** |
| Apple | `LIQUIDITY_DETERIORATION` on quick ratio | 0.488, 0.337, 0.409, 0.359, 0.457 | −6.3% | −0.010 |
| Coca-Cola | `LIQUIDITY_DETERIORATION` on quick ratio | 0.662, 0.659, 0.542, 0.570, 0.625 | −5.5% | −0.026 |

All three clear the 5% `STABLE_MAGNITUDE_THRESHOLD` only because the window's
**first** period happened to be its peak, and in all three the latest value is
*not* the window's extreme. Walmart's is the clearest: a least-squares slope
over the same five points is **positive** — the margin has recovered since
FY2023 — while the signal says compression. That is [D-024](decision_log.md)'s
first-to-last comparison showing its residual weakness: the window bounds how
far back the anchor can sit, but does not make the direction robust to *where*
inside the window the anchor falls.

**Rate: 3 of 90 trend-based signals (3.3%), 0 of 97 on the distressed cohort.**
The diagnostic that finds them (`_shape_checks`, using
`statistics.linear_regression` — no new dependency) lives in the validation
script, not the engine: this is evidence for reopening the slope-fit deferral
below, not a change made mid-phase.

### 7a.2 Pre-phase-in filings degrade gracefully

The audit's third condition. Ratio coverage by the vintage of the filing that
first reported each period (`m4_coverage_by_vintage.csv`, 185 periods):

| Filing year | 2009 | 2010 | 2011 | 2012 | 2013 | 2014-16 | 2017+ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mean ratio coverage | 21% | 51% | 72% | 65% | 90% | 88-94% | 96-97% |

Coverage rises steeply across the XBRL phase-in and plateaus above 96% from
2017. The important part is that this thinness is **reported, not hidden**: a
2009-vintage period yields `MISSING_INPUT` ratios, which yield
`INSUFFICIENT_DATA` trends, which raise no signal. No endpoint artefact in
§7a.1 involves a pre-2013 period, and none of the 97 distressed-cohort signals
does either. Thin old periods lower coverage; they do not manufacture trends.

### 7a.3 Restatements verified against the raw source

`qm04_restatements.csv` classifies all **453** restatements the multi-filing
path surfaces across the 12 companies, by cause, from canonical-fact
provenance: 270 `same_tag_restatement`, 110 `immaterial`, 52 `amendment`, 21
`tag_change`, 0 `origin_change`. Genuine restatements are mostly small (median
1.5%, p75 5.2%, 16% exceed 10%) with a real tail — Expand Energy's FY2017 net
income moves from +949M to −505M across filings.

Because that classification was produced *from* the canonical facts, a
stratified sample of 8 per category was re-derived straight from the raw
`companyfacts` JSON (`m4_restatement_verification.csv`): **32 of 32 confirmed.**

One "restatement" is not one. Tesla's own FY2016 10-K tags `DebtCurrent` as
1,114,652 where every later filing reports 1,114,652,000 — a 1000× scale error
by the filer, which [D-008](decision_log.md)'s as-filed rule faithfully
preserves. Scanning all 453 for near-exact powers of ten finds **exactly one**
such case, which is why it is documented rather than answered with a
scale-detection heuristic.

## 8. What Phase 7 deliberately does not do

- No composite/overall health score (§5, §25, §46).
- No credit decision, rating, or default prediction (§1, §31, §46).
- No LLM call, no natural-language cause inference (§31, §32, §46) — every
  signal's `evidence` field is deterministic prose over already-computed
  numbers, never a generated explanation.
- No industry-relative thresholds or benchmarks (§27) — every threshold in
  `health/thresholds.py` is either a fixed, disclosed noise floor or a
  company-own-history baseline (§12); industry normalization is named as a
  deferred idea below, matching `docs/scope.md` §4's own "later" list.

## 9. Deferred ideas

- **Industry-relative baselines/thresholds** (§27) — the architecture
  leaves room for it (nothing here assumes a universal threshold), but no
  industry benchmark data source has been chosen; `docs/scope.md` already
  lists this as a post-MVP candidate.
- ~~**Cross-filing (multi-year, multi-accession) trend analysis**~~ —
  **done in Phase 8 (M-4), measured in §7a.** The premise of this deferral was
  wrong: the corpus it was waiting for already existed in the `companyfacts`
  cache. Running it raised conclusive trends from 40.4% to 91.7% and removed
  every `INSUFFICIENT_DATA` dimension.
- **A CAGR or multi-point slope-fit trend method** (§7, §28) — **the reason
  for this deferral no longer holds, and there is now evidence for it.** It was
  deferred because "typically 2-4 usable periods per filing" made a regression
  slope no more informative than a first-to-last comparison. On the
  multi-filing path a window carries 5 periods by default and up to 20 are
  available, and §7a.1 shows the first-to-last comparison producing 3 endpoint
  artefacts that a least-squares slope over the same points identifies — in
  Walmart's case with the opposite sign. The counter-argument is that a slope
  is less legible to an analyst than "it fell 7.7% over five years", so the
  likely answer is to report both and let the *disagreement* be the signal,
  rather than to replace one with the other. Still deferred, now with a
  concrete design question and measured evidence rather than a sample-size
  objection. `statistics.linear_regression` covers it; no dependency needed.
- **A generalized volatility/standard-deviation metric per ratio** (§7) —
  `unusual_movement`'s robust z-score already answers "was the latest move
  unusual"; a separate always-on volatility figure was considered and
  deferred pending a concrete downstream use (e.g. a future Phase 8
  feature) that would need it.
- **Signal severity (`INFO`/`WATCH`/`ALERT`)** (§30) — considered and
  deliberately omitted. A severity label is one step from a hidden
  credit-risk score, and every signal already carries `persistence` and
  the dimension's breadth (via `MULTI_DIMENSION_DETERIORATION`) as
  structured, un-collapsed facts a downstream consumer (Phase 12) can
  weight itself.
