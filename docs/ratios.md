# Financial Ratio Engine — Phase 6

| | |
|---|---|
| **Status** | v1.1 — Phase 6, audited (§8) |
| **Date** | 2026-09-16 |
| **Related** | [D-019](decision_log.md) · [D-020](decision_log.md) · [D-021](decision_log.md) · [canonical_schema.md](canonical_schema.md) (the Phase 5 → 6 interface) · [QM-02](#6-qm-02--real-corpus-evaluation) |

Phase 5 answers "what does the filing's XBRL represent financially" — a
typed, provenance-carrying `CanonicalFact` per (concept, period). Phase 6
answers "given those facts, what do the ratios equal" — deterministic
arithmetic, explicit status for every failure mode, and complete provenance
back to the canonical facts consumed. Code lives in
`src/credit_risk_copilot/ratios/`.

Phase 6 does **not** decide whether a ratio value is good, bad, or a warning
sign. That is Phase 7.

## 1. The Phase 5 → 6 interface, as actually used

`ratios/engine.py` takes a plain `(concept: str, period_label: str) ->
CanonicalFact | None` callable — nothing Phase-5-specific. Two concrete
sources satisfy it without any adaptation code:

- `ratios_for_filing(filing)` — one `CanonicalFilingFacts.get`, covering
  every comparative period a single accession's XBRL reports (often three to
  four fiscal years from one 10-K; see §5).
- `ratios_from_facts(facts, periods)` — the plain dict
  `CompanyFinancials.as_of(cutoff)` already returns, for the point-in-time,
  as-filed, multi-filing view (D-008).

`ratios/models.py` and `ratios/registry.py` import only
`credit_risk_copilot.financials.models` — never `resolver`, `xbrl`,
`extraction`, or `concept_map`. Deleting every PDF/XBRL/HTML module from the
project would not break this package; it only needs `CanonicalFact` objects,
however they were produced.

## 2. The ratio catalog

13 ratios across five categories, in `ratios/registry.py`. Each is a
`RatioDefinition`: its inputs (canonical concept ids, in formula order), a
machine formula and a human-readable one, its denominator concept, and a
`compute` callable. Adding a ratio is one new `RatioDefinition`, never a new
branch in `engine.py`.

| Category | Ratio | Formula | Unit |
|---|---|---|---|
| Liquidity | Current Ratio | current_assets / current_liabilities | x |
| Liquidity | Quick Ratio | (cash + accounts_receivable) / current_liabilities | x |
| Leverage | Debt-to-Equity | total_debt / shareholders_equity | x |
| Leverage | Debt-to-Assets | total_debt / total_assets | % |
| Leverage | Liabilities-to-Assets | total_liabilities / total_assets | % |
| Profitability | Gross Margin | gross_profit / revenue | % |
| Profitability | Operating Margin | operating_income / revenue | % |
| Profitability | Net Profit Margin | net_income / revenue | % |
| Profitability | Return on Assets | net_income / total_assets | % |
| Profitability | Return on Equity | net_income / shareholders_equity | % |
| Coverage | Interest Coverage | ebit / interest_expense | x |
| Cash flow | OCF-to-Debt | operating_cash_flow / total_debt | % |
| Cash flow | OCF-to-Revenue | operating_cash_flow / revenue | % |

### What was deliberately left out, and why

- **Free-cash-flow-based ratios.** `free_cash_flow`'s `capital_expenditures`
  input is left `CONFLICTING` by design for filers whose PP&E and
  capital-improvement tags overlap (Pyxus, Expand — canonical_schema.md
  §15). An FCF ratio would be unavailable exactly for the filers where debt
  coverage matters most, and `operating_cash_flow` already has no such gap.
  `free_cash_flow` itself remains available as a canonical amount for
  trending without a Phase 6 ratio wrapper.
- **EBITDA / EBITDA-based coverage.** The canonical schema has no
  depreciation/amortisation concept (Phase 5 was not asked to add one for a
  Phase 6 that had not started yet). Interest coverage uses EBIT.
- **Any ratio needing average (beginning + ending)/2 balances.** See §4.
- **Cash ratio (cash / current liabilities alone).** Redundant with the
  Quick Ratio given the schema's inputs — both numerators reduce to "cash
  plus what the schema can additionally resolve," and Quick Ratio is the
  more standard name for that comparison.
- **Working capital (a dollar amount, not a ratio).** Out of scope for a
  ratio catalog; trivially `current_assets - current_liabilities` if a
  future phase wants it.

## 3. Result model

`RatioResult` (frozen, `ratios/models.py`):

```text
ratio_id, name, category, period_label
value, unit, status
formula (machine), formula_display (human)
inputs: dict[concept -> CanonicalFact | None]
warnings: tuple[RatioWarning, ...]      # code, concept, message — see below
reason: str | None                       # populated when status != CALCULATED
calculation_method: str | None           # e.g. "ending_balance" on roa/roe (D-020); None elsewhere
```

Two read-only properties compute the machine-readable form of `reason`
without parsing it: `missing_concepts` (populated only when
`status is MISSING_INPUT`) and `conflicting_concepts` (only when
`status is CONFLICTING_INPUT`) — both read straight off `inputs`, so they
cost nothing to keep in sync (Phase 6 audit §13, 2026-09-16).

`inputs` references the actual `CanonicalFact` objects consumed rather than
re-deriving a parallel set of fields — full provenance (XBRL tag, accession,
derivation formula, candidates) is already on those objects (§16 of the
phase brief: "do not copy huge source documents into the ratio object;
reference the canonical facts where possible"). `explain()` produces a
deterministic, purely factual explanation: the formula, each input's value
and status, and any warnings — never an interpretation of what the number
means.

### Status — four states, not more

| Status | Meaning |
|---|---|
| `CALCULATED` | Every required input resolved; the denominator was usable |
| `MISSING_INPUT` | At least one required concept has no resolvable value for this period (absent from the filing, or a Phase 5 `MISSING` fact — both mean "no value" per canonical_schema.md §16) |
| `INVALID_DENOMINATOR` | The denominator is zero (within $1) or, for a ratio whose denominator is conventionally non-negative, negative |
| `CONFLICTING_INPUT` | At least one required concept is a Phase 5 `CONFLICTING` fact — a value exists but disagreeing sources were never resolved to one number |

`REQUIRES_REVIEW`, `LOW_CONFIDENCE` and `NOT_APPLICABLE` were considered and
dropped: everything they would flag is already visible either on the
underlying `CanonicalFact` (`status`, `confidence`) or as a `warnings` entry
on an otherwise `CALCULATED` result. A fifth or sixth status would encode a
caveat as if it blocked calculation, when it does not (§9's own instruction
to choose the minimum useful set).

**Priority when a ratio has more than one problem input:** `CONFLICTING`
beats `MISSING` beats a bad denominator — a conflicting value is a stronger
claim ("we have disagreeing evidence") than a merely absent one, so it is
surfaced first.

### Warnings — caveats on a value that was still computed

Each `RatioWarning` is `{code, concept, message}` — a `WarningCode` enum, not
only a string, so a caller can branch on it without substring-matching
`message` (Phase 6 audit §17, 2026-09-16: with `total_debt` and `ebit`
resolving as `DERIVED` for nearly every filer — see §6 — a majority of
`CALCULATED` results carry at least one warning, and Phase 7 needs to filter
"routine derivation" from "a real caveat" without parsing prose).

| `WarningCode` | Fires when |
|---|---|
| `DERIVED_INPUT` | An input is `DERIVED` rather than directly tagged (`message` includes its `formula`) |
| `LOW_CONFIDENCE_INPUT` | An input has `Confidence.LOW` |
| `MANUAL_INPUT` | An input was `MANUALLY_CORRECTED` (original and corrected value both named) |
| `NEGATIVE_EQUITY` | The denominator is negative on a ratio where that is legitimate (`debt_to_equity`, `roe` — negative equity is common among distressed filers and is exactly the signal a monitoring product must not hide; see §10 of the phase brief) |
| `NEAR_ZERO_DENOMINATOR` | `interest_coverage` only: `interest_expense` is present, nonzero, but under 2% of `\|ebit\|` — the ratio is real but dominated by noise in the smaller figure, a quality flag the phase brief names explicitly (§20), not a judgement about whether coverage is adequate. Verified against the real corpus: fires for Tesla FY2023 (interest_expense $156M, 1.5% of EBIT $10.1B, coverage 64.9x) and correctly stays silent for FY2024/FY2025 once the ratio crosses 2% |

Considered and **not** generalized: a relative near-zero-denominator warning
for every ratio (equity, revenue, total_assets), not just
`interest_coverage`. Checked against all 362 `CALCULATED` results in the
real corpus (§6) — every extreme value found (SandRidge's -481% net margin,
Frontier's -3.94x D/E) traces to a real, materially-sized denominator and a
genuinely extreme numerator (an impairment, a real equity deficit), not a
near-zero-denominator artifact. Generalizing the warning would be solving a
problem not observed in this corpus; deferred pending evidence it recurs
elsewhere (Phase 6 audit §5, classified B — investigate if it appears).

## 4. Formula decisions

- **ROA / ROE use ending-period balances, not average(beginning, ending)**
  (D-020). A rigorous treatment would average `total_assets` /
  `shareholders_equity` across the period — considered, and rejected for
  this MVP: it would make one period's ratio depend on another period's data
  availability, breaking the "each period is an independent calculation"
  model every other ratio in this catalog follows, for a refinement whose
  benefit (removing one year's balance-sheet timing noise) is real but
  secondary to shipping a clean, always-single-period foundation. The
  decision is deliberately visible, not silent: nothing in the result model
  claims to be an average, and a future average-balance variant is additive
  (a new `RatioDefinition`, e.g. `roa_avg`) rather than a breaking change.
- **Interest coverage uses EBIT, not EBITDA** — no depreciation/amortisation
  canonical concept exists (§2).
- **Debt-to-Equity uses `shareholders_equity` (parent), not `total_equity`**
  (including noncontrolling interests) — matching canonical_schema.md §16's
  explicit guidance to use the shareholder-level concept for
  shareholder-facing ratios, and D/E is conventionally a shareholder-facing
  measure.
- **`total_debt` is Phase 5's own definition**: short-term debt (current
  portion of long-term debt + short-term borrowings, summed as components,
  never picked as alternatives) plus noncurrent long-term debt. This
  includes finance leases where a filer tags them as part of debt, and
  excludes operating leases (no canonical operating-lease-liability
  concept). Phase 6 inherits this definition rather than declaring its own
  — a ratio engine second-guessing Phase 5's accounting-semantic choices
  would be exactly the risk §26 warns about.
- **Interest expense is a positive magnitude** under the schema's sign
  convention (canonical_schema.md §14), so `ebit / interest_expense` is
  never divided by a signed value; a negative `interest_expense` fact would
  already be flagged by Phase 5's `sign_sanity` validation before it reaches
  Phase 6.

## 5. Multi-year support

`ratios_for_filing(filing)` defaults `periods` to `filing.period_labels` —
every annual period the filing's own XBRL reports, which for a typical 10-K
is two to four fiscal years from one accession (three for the income
statement and cash flow, two to three for the balance sheet) with **no
extra work**: Phase 5's `resolve_filing` already resolves every comparative
column in one call. Each period is calculated completely independently; a
missing or invalid input in one year never affects another year's result.

`ratio_history_changes(results)` computes deterministic period-over-period
deltas (absolute and percent) for one ratio's chronological series — pure
arithmetic, no threshold, no "improving"/"worsening" label. That
interpretation is Phase 7's. A change is only produced when both periods
`CALCULATED`; `percent_change` is `None` rather than a manufactured infinity
when the prior value is (numerically) zero.

For monitoring across multiple *filings* (not just one filing's own
comparative columns) — the case where a company is followed 10-K to 10-K
over years — `ratios_from_facts` combined with `CompanyFinancials.as_of()`
gives the same result model over Phase 5's D-008 as-filed, point-in-time
view. Not exercised against the real corpus (the golden set has one filing
per company); unit-tested with a synthetic fixture, matching how Phase 5
tested `CompanyFinancials` itself.

## 6. QM-02 — real-corpus evaluation

`scripts/evaluate_ratios.py` runs every ratio over every comparative period
of all 12 golden-set filings — 598 (ratio, period) calculations, entirely
from cache.

**Primary-period coverage** (each filing's own most-recent fiscal year —
the period Phase 5's own QM-01 measured against):

| Ratio | Calculated | Ratio | Calculated |
|---|---:|---|---:|
| Current Ratio | 12/12 | Return on Assets | 12/12 |
| Debt-to-Equity | 12/12 | Return on Equity | 12/12 |
| Debt-to-Assets | 12/12 | OCF-to-Debt | 12/12 |
| Liabilities-to-Assets | 12/12 | OCF-to-Revenue | 12/12 |
| Net Profit Margin | 12/12 | Operating Margin | 11/12 |
| Quick Ratio | 11/12 | Interest Coverage | 11/12 |
| Gross Margin | 8/12 | | |

11 of 13 ratios reach 92-100% on the primary period. **Gross Margin (8/12)**
is the one real gap, and it is not a Phase 6 defect: `cost_of_goods_sold` is
genuinely absent for filers presenting operating costs by nature rather than
by function (energy, telecom, media — the same gap canonical_schema.md §12
already documents for the underlying concept). Quick Ratio and Interest
Coverage each miss one filer for a documented reason (`accounts_receivable`
not presented; `interest_expense` untagged by Apple — both named in
canonical_schema.md §12).

**Full multi-year coverage** (every comparative period, not just the
primary one) is materially lower — 213/442 (48.2%) on comparative years vs.
149/156 (95.5%) on primary years. This is the phase's one substantive
finding about Phase 5, not about the ratio engine's own logic:

> Phase 5's tag-chain policies were measured (QM-01) only against each
> filing's primary period. Older comparative columns in the same accession
> resolve materially less completely — most visibly `total_debt`, whose
> `COMPONENTS` resolution depends on tags (`CommercialPaper`,
> `LongTermDebtAndCapitalLeaseObligationsCurrent`, etc.) that are tagged
> less consistently, or not at all, in a filer's older XBRL. This is not a
> Phase 6 bug: the ratio engine correctly reports `MISSING_INPUT` for
> exactly the periods where Phase 5 could not resolve an input. It is a real
> constraint on how far back a ratio history can usefully go for a given
> filer, and Phase 7's trend analysis should expect shorter, and
> filer-dependent, series lengths rather than a uniform N years.

**Per-ratio comparative-year coverage** (Phase 6 audit, 2026-09-16), broken
out because the drop in §6 is not uniform across ratios — this is what Phase
7 should actually expect per ratio, not one blended number:

| Ratio | Comparative-year coverage | Ratio | Comparative-year coverage |
|---|---:|---|---:|
| Current Ratio | 12/34 (35%) | ROA | 16/34 (47%) |
| Quick Ratio | 12/34 (35%) | ROE | 13/34 (38%) |
| Debt-to-Equity | 12/34 (35%) | Interest Coverage | 22/34 (65%) |
| Debt-to-Assets | 12/34 (35%) | OCF-to-Debt | 12/34 (35%) |
| Liabilities-to-Assets | 16/34 (47%) | OCF-to-Revenue | 24/34 (71%) |
| Gross Margin | 16/34 (47%) | Net Profit Margin | 24/34 (71%) |
| Operating Margin | 22/34 (65%) | | |

The pattern is consistent with the cause named above: ratios needing
`total_debt` or `current_liabilities`/`current_assets` (Current Ratio, Quick
Ratio, D/E, Debt-to-Assets, OCF-to-Debt) sit at the low end (35%); pure
income-statement ratios (Net Profit Margin, OCF-to-Revenue) sit at the high
end (71%), because `revenue` and `net_income` are tagged far more
consistently across historical years than balance-sheet debt/liability
components. **Phase 7 should expect materially shorter usable history for
leverage and liquidity ratios than for margin ratios**, for the same filer.

Full per-(ratio, period) results and the coverage matrix are written to
`data/processed/golden_set/qm02_*.csv` and `qm02_summary.json` (gitignored,
like all of `data/` — rerun the script to reproduce).

## 7. Deferred ideas

- An average-balance variant of ROA/ROE (`roa_avg`, `roe_avg`), additive to
  the current ending-balance ratios once there is a concrete reason to need
  it (§4).
- A `debt_components_tie`-style cross-check between comparative-year
  `total_debt` values within one filing, to help distinguish "the filer
  restated its debt" from "the older year was simply undertagged" — useful
  once Phase 7 needs to trust or discount a short historical series.
- Widening Phase 5's tag chains against older filing years specifically
  (this phase's §6 finding) — Phase 5's own scope, not Phase 6's.
- Industry-specific ratio variants (e.g. a financial-sector leverage
  measure) — explicitly deferred; the phase brief flags industry-aware
  hooks as Phase 7 territory (roadmap.md).
- A relative near-zero-denominator warning generalized beyond
  `interest_coverage` (§3) — no evidence in the real corpus that it is
  needed elsewhere; revisit if a future filer shows the pattern.
- A `debt_service_coverage`-style ratio using `interest_expense` plus a
  current-debt-maturities component — considered during the Phase 6 audit
  and deferred: the canonical schema does not separately expose "scheduled
  principal due next year" from `short_term_debt` (which already mixes
  current LTD maturities with short-term borrowings that are not
  amortization), so this would either misstate the concept or need a new
  Phase 5 concept — out of Phase 6's scope to add unilaterally.

## 8. Phase 6 audit (2026-09-16)

A deep audit was run before starting Phase 7, per its own brief: inspect
every ratio's formula and inputs, stress-test against the real corpus
(including the distressed-filer cohort — SandRidge, Peabody, iHeartMedia,
Frontier, Expand Energy), and fix only what real evidence justified.

**Verdict: ready for Phase 7 after the improvements below.** No formula was
found to be wrong; no accounting-semantic error was found; no circularity
was found (every `compute` reads only canonical concepts, never another
ratio's result — verified by a registry test that calls each `compute` with
nothing else available). The debt/equity/EBIT/cash/OCF definitions Phase 6
inherited from Phase 5 are consistent across every ratio that uses them,
because every ratio references the same canonical concept rather than
declaring its own — cross-checked on real data: `debt_to_assets` never
exceeded `liabilities_to_assets` across all 362 `CALCULATED` real-corpus
results, the arithmetic invariant that must hold given `total_debt` is a
subset of `total_liabilities`.

**Real-data stress test, specific findings:**

- SandRidge Energy FY2015: Net Profit Margin -481%, Operating Margin -604%,
  Interest Coverage -12.4x. Traced to source: a $4.64B operating-income
  impairment against $769M revenue during the 2015 oil-price collapse — a
  real, correctly-represented accounting event, not a ratio-engine defect.
  Confirms the engine reports what happened rather than smoothing it.
- Tesla FY2023-2025 Interest Coverage: 64.9x -> 26.7x -> 16.6x — a large
  swing that could look like a data error. Traced to source: Tesla's
  `interest_expense` genuinely is tiny ($156M-$338M) relative to its EBIT
  ($5.6B-$10.1B); the `NEAR_ZERO_DENOMINATOR` warning correctly fires only
  on FY2023 (1.5% of EBIT), not FY2024/FY2025 (3.8%/6.0%) — the 2%
  threshold is doing its job on a real case, not a synthetic one.
- No `CONFLICTING_INPUT` or `INVALID_DENOMINATOR` result occurred anywhere
  in the 598-slot real corpus. Both paths remain synthetic-tested only.
  This is expected, not a gap to close: `CONFLICTING` in Phase 5 is
  currently raised only for `capital_expenditures`, which no Phase 6 ratio
  uses (a deliberate choice — §2) — real invalid-denominator/conflicting
  cases would need either a distressed filer with literal zero equity/debt
  or a filer with disagreeing capex tags feeding a ratio, neither of which
  is in this corpus.

**Improvements implemented** (classification A — small effort, materially
improves auditability/downstream safety, matching §30's implementation
rule):

1. **Structured warnings** (`RatioWarning{code, concept, message}` replacing
   `tuple[str, ...]`). Motivated by real-data evidence: `total_debt` and
   `ebit` have no direct XBRL tag at all (concept_map.py) and so are
   `DERIVED` for nearly every filer, meaning a majority of `CALCULATED`
   results already carry at least one warning — a downstream consumer
   needs to filter "routine derivation" from "negative equity" without
   regexing English sentences. See §3.
2. **`RatioResult.missing_concepts` / `.conflicting_concepts`** computed
   properties — machine-readable equivalents of `reason`, requested
   explicitly by the phase brief §13.
3. **`RatioDefinition.calculation_method` / `RatioResult.calculation_method`**
   (`"ending_balance"` on `roa`/`roe`, `None` elsewhere) — makes D-020's
   MVP simplification machine-readable on every result, not only
   documented in prose, so a future average-balance variant can never be
   silently confused with the current one.

All three changes are additive to the data model (new fields/properties);
no ratio's formula, status logic, or numeric behavior changed. Verified:
`scripts/evaluate_ratios.py` produces byte-identical coverage numbers
before and after (598 slots, 362 calculated, 0 conflicting, 0 invalid
denominator). 246/246 project tests pass (up from 244; 6 new/updated
regression tests), 100% coverage maintained on `ratios/`.

**Improvements investigated and deferred** (classification B/C — see §7 for
the deferred-ideas list; the near-zero-denominator generalization and
`debt_service_coverage` above are the two considered here).

**Ideas rejected outright** (classification D — no evidence of a problem):
rewriting the debt/EBIT/cash definitions (already consistent, per the
stress test above); adding average-balance ROA/ROE now (D-020 stands,
confirmed after re-review — see §4); expanding the ratio catalog past 13 to
add cash-to-debt or similar (redundant with existing leverage/coverage
ratios given this schema's inputs, not a distinct signal); an
industry-applicability metadata field (no product decision yet on
non-corporate filers to attach it to — premature).
