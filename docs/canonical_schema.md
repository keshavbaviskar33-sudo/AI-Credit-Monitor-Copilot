# Canonical Financial Schema — Phase 5

| | |
|---|---|
| **Status** | v0.2 — Phase 5, revised after the Phase 5 audit |
| **Date** | 2026-09-16 |
| **Related** | [D-005](decision_log.md) · [D-016](decision_log.md) · [D-017](decision_log.md) · [D-018](decision_log.md) · [extraction.md](extraction.md) · [data_dictionary.md §6](data_dictionary.md) · [risks.md](risks.md) (R-09, R-11) · [product_requirements.md](product_requirements.md) (QM-01, FR-07) |

Phase 4 answers "what can we retrieve, and where from" — located but
uninterpreted text, tables and sections (`extraction/models.py`). Phase 5
answers "what does that represent financially": a typed, provenance-carrying
`CanonicalFact` per (canonical concept, fiscal period), for every filing.
Code lives in `src/credit_risk_copilot/financials/`.

## 1. The Phase 4 → 5 interface, as actually used

Phase 5 does **not** re-derive numbers from Phase 4's document tables. For US
SEC filers, XBRL is the source of record ([D-005](decision_log.md)); the
`companyfacts` JSON `SecEdgarClient.company_facts()` already fetches and
caches is the primary input, read by `financials/xbrl.py` and turned into
canonical facts by `financials/resolver.py`. Phase 4's `ExtractedDocument` is
used for one bounded, secondary purpose: `financials/reconciliation.py`
checks whether a resolved XBRL value is *also* independently visible in the
filing's own HTML tables (§7 below) — corroboration, not extraction. This is
a deliberate, documented scope decision ([D-017](decision_log.md)).

## 2. Canonical concept set

26 concepts across three statements, in `financials/concept_map.py`. The set
is the minimum needed for the ratios already committed to in the roadmap
(Phase 6): current/quick ratio, debt/equity, debt/assets, interest coverage,
net/operating margin, ROA, free cash flow. Some concepts are not ratio-final
themselves and exist only as derivation inputs: `cost_of_goods_sold` (gross
profit), `pretax_income` (EBIT), `accounts_receivable`/`inventory` (quick
ratio), and `noncontrolling_interest` (reconstructing total equity).

| Statement | Concepts |
|---|---|
| Income statement | `revenue`, `cost_of_goods_sold`, `gross_profit`, `operating_income`, `interest_expense`, `pretax_income`, `ebit`, `net_income` |
| Balance sheet | `cash`, `accounts_receivable`, `inventory`, `current_assets`, `total_assets`, `current_liabilities`, `total_liabilities`, `short_term_debt`, `long_term_debt`, `total_debt`, `shareholders_equity`, `noncontrolling_interest`, `total_equity` |
| Cash flow | `operating_cash_flow`, `capital_expenditures`, `investing_cash_flow`, `financing_cash_flow`, `free_cash_flow` |

Two equity concepts, deliberately: `shareholders_equity` is equity
attributable to the parent (the debt/equity denominator), and `total_equity`
includes noncontrolling interests (the equity side of the balance-sheet
identity). They are different measures and are never substitutes (§4).

Each `ConceptDefinition` carries a `rationale` string explaining why it is
included and how its tags relate — read the source for the per-concept
justification rather than a second copy of it here.

## 3. Tag chains with an explicit policy, and derivation

[R-11](risks.md)/[A-06](assumptions.md) measured that a single-tag lookup
fails for half the golden set: `Liabilities` 6/12, `LongTermDebt` 7/12,
`Revenues` 9/12, and the assumed `SalesRevenueNet` fallback **0/12** — it is
deprecated. Each concept therefore carries several XBRL tags. The audit (§15)
showed that an *ordered list* is not enough: the tags in a chain can relate
in three different ways, so each concept declares a `TagResolution`
([D-018](decision_log.md)):

| Policy | Meaning | Examples |
|---|---|---|
| `ALTERNATES` | True synonyms. First present wins; a disagreement (beyond 0.1%) is `CONFLICTING` | `total_assets`, `inventory`, `capital_expenditures` |
| `PREFERRED_SCOPE` | Differently-scoped versions of one idea. The preferred tag wins; every differently-valued alternative is kept in `candidates` | `net_income` (parent vs. incl. NCI), `revenue` (net vs. gross of assessed tax), `long_term_debt` (noncurrent vs. total), the three cash-flow totals (total vs. continuing operations), `interest_expense` |
| `COMPONENTS` | Additive parts. The filer's own total tag wins; otherwise each component group contributes its first tagged alternative, and those are summed | `short_term_debt` |

`short_term_debt` has two component groups — the current portion of
long-term debt (tagged with or without finance leases), and short-term
borrowings (tagged as a total, or as commercial paper plus other borrowings,
or as current notes). Alternatives *within* a group are never added together,
which is what prevents double counting one component under two names.

Concepts with no reliable direct tag carry **derivation rules**
(`total_liabilities = total_assets - total_equity`; `total_equity =
shareholders_equity + noncontrolling_interest`; `total_debt = short_term_debt
+ long_term_debt`; `gross_profit`, `ebit`, `free_cash_flow`). A concept may
have several rules, tried in order. Derivation runs **to a fixpoint**, so a
derived input (`total_equity` feeding `total_liabilities`) resolves no matter
where either concept is declared.

Every fact also passes three filters before it is a candidate at all: the unit
must be `USD` (anything else is excluded, never converted), the period must be
the filing's own annual period (§4), and one tag carrying two different
values for one period is `CONFLICTING` rather than "first one wins".

## 4. Period bugs found by evaluation

Both were found by running QM-01 against the actual golden set, not by
inspection, and both are now regression tests.

**Instant vs. duration periods sharing a label.** A period's identifier is
`FY{end.year}` (§5), and both an instant balance ("December 31, 2025") and a
duration flow ("year ended December 31, 2025") can carry that same label —
intentionally, since that is what lets `validation.py` join a balance-sheet
fact with a cash-flow fact for the same fiscal year. But a cache keyed only
by that label, shared across *different concepts of different natures*,
could hand an instant concept a duration-typed `Period` object depending on
resolution order. Fixed by keying the resolver's period cache on
`(PeriodType, label)`, not `label` alone (`resolver._resolve_direct_tags`).

**A "selected quarterly financial data" footnote under the same tag and
accession.** iHeartMedia's 2016 10-K tags `Revenues` for 2015-Q1, Q2, Q3, Q4
*and* full-year 2015 — five entries, one concept, one accession. Keying a
period by `end.year` alone folds a quarter's revenue into the same bucket as
the annual figure (Q1–Q3 collide by coincidence of calendar year; Q4 collides
outright, since its `end` **is** the fiscal year end). `periods.is_annual_period`
now requires both: the `end` date must fall within 10 days of the filing's
own declared fiscal year end (rejects Q1–Q3), and a duration must span
350–380 days (rejects Q4, whose span is ~92 days). The 10-day tolerance is
deliberate, not arbitrary slack: it absorbs a 52/53-week fiscal calendar's
few days of year-to-year drift without coming close to admitting a quarter.

## 5. Period model

`Period` (in `models.py`) is identified by its actual `end` date (and
`start` for durations) — not by the XBRL `fy`/`fp` fields, which
[golden_set.md §2](golden_set.md) documents as describing the *filing's*
declared fiscal context, not each comparative column's own period (several
rows in one filing legitimately share one `fy` while their `end` dates span
different years). `Period.label` (`"FY2025"`) is what facts are keyed and
joined by; `fiscal_year` is read off `end.year`. Scope is annual-only
(D-007) — `fiscal_period` defaults to `"FY"`; a quarterly extension would
need `periods.is_annual_period`'s tolerance windows revisited, not the label
scheme itself.

`periods.parse_period_label` is a small, deliberately bounded regex reader
for table-header text ("Year Ended December 31, 2025" vs. a bare date) for
the no-XBRL upload path (FR-04). It is not wired into an automatic
table-column-to-period aligner: for SEC filers, XBRL already solves this
exactly (D-005/D-014), so building full alignment for uploaded PDFs — a
harder, lower-value problem for this product's primary case — is a
documented limitation (§11), not attempted here.

## 6. Status, confidence and origin

Six states (`FactStatus`), chosen to be the smallest set each state's caller
actually needs to branch on:

| Status | Meaning |
|---|---|
| `FOUND` | Resolved directly from one XBRL tag |
| `DERIVED` | Computed from other canonical facts; `formula` explains how |
| `MISSING` | No sufficiently reliable source; `value=None`, never a fabricated 0 |
| `CONFLICTING` | Two-plus tags disagree beyond rounding; `candidates` holds all of them, `value=None` |
| `REQUIRES_REVIEW` | Reserved for validation-driven review flags (not yet raised by the resolver itself) |
| `MANUALLY_CORRECTED` | An analyst overrode the value; original preserved in `correction.previous_value` |

`Confidence` is `HIGH`/`MEDIUM`/`LOW`, not a float — a manufactured `0.87`
would look like evidence without being any. `HIGH` is the first-priority tag
from a standard taxonomy; `MEDIUM` is a fallback tag or a derivation;
`LOW` is an extension concept, a conflict, or a missing fact.
`CanonicalFact.effective_value` is the one property downstream ratio code
should read: the manual correction if one exists, otherwise the value —
`None` for anything not `FOUND`/`DERIVED`/`MANUALLY_CORRECTED`.

## 7. Reconciliation, deliberately small

[§13's warning against a large reconciliation framework] is taken literally:
`reconciliation.corroborate_filing` is one function, one direction (does the
document confirm the XBRL value?), reusing Phase 4's already-extracted
tables and `numeric.render_candidates`'s scale/format search adapted from the
Phase 4 R-19 spike (`table_extraction_spike.py`). Two outcomes only:

- **Found:** an extra HTML provenance entry is appended and confidence rises
  to `HIGH` — two independent sources agreeing is real evidence.
- **Not found:** nothing changes. HTML recall on this same golden set
  measured 85.1%, not 100% ([golden_set.md §3](golden_set.md)), so absence
  from the document tables is at least as likely to mean "the extractor
  missed it" as "the number is wrong" — treating it as a conflict would
  manufacture distrust the data does not support.

## 8. Validation

`validation.py` runs three checks, each a flag, never a rejection:

- **`balance_sheet_equation`** — Assets ≈ Liabilities + **total** equity
  (including noncontrolling interests), 1% tolerance. It is **not reported**
  when liabilities were derived from this same identity: such a check passes
  by construction and proves nothing. The first version scored 11 of its 19
  "passes" that way, each with a difference of exactly zero (§15).
  On XBRL inputs this check has limited power even when independent — XBRL
  calculation linkbases already force reported totals to tie, so 10 of the 12
  independent checks show a difference of exactly zero. It earns its keep
  catching a wrong tag choice (Tesla's 58M residual is its redeemable,
  mezzanine noncontrolling interest) and, later, document-sourced figures.
- **`cash_tie_out`** — prior cash + CFO + CFI + CFF ≈ ending cash, 5%
  tolerance. Generous on purpose: this identity ignores FX-translation effects
  on cash, which real filings often report as a line this schema does not
  carry. The one failure in the golden set, Coca-Cola FY2024 (−957M), is
  exactly that — a heavily international filer — not an extraction error.
- **`sign_sanity`** — flags a negative value for a concept that is
  non-negative by construction, and a part exceeding its whole (§14).
  Equity, net income and the net cash flows are excluded: their sign carries
  meaning, and negative equity is common among distressed filers.

Every check only fires when its inputs are actually resolved; a missing
input produces no result, never a false failure.

## 9. Provenance and the derived/reported distinction

Every resolved `CanonicalFact` carries `provenance: tuple[Provenance, ...]`
(concept, namespace, accession, form, filed date, original value), and every
`MISSING` fact carries a `reason`. A `DERIVED` fact records its inputs twice
over: `derived_from` names the canonical concepts it consumed, in formula
order, and `provenance` is the union of those inputs' own provenance, so
`total_liabilities` traces to `total_assets` and `total_equity`, and from
there to the `Assets` and `StockholdersEquityIncludingPortion...` XBRL facts.
`formula` states the relationship in plain terms, and `origin=DERIVED` means a
derived value can never be mistaken for one the filer reported.
`candidates` preserves every disagreeing value on a `CONFLICTING` fact and
every differently-scoped alternative on a `PREFERRED_SCOPE` fact.
`ManualCorrection` preserves the pre-correction value and status rather than
overwriting them.

## 10. Multi-filing, point-in-time aggregation

`company.CompanyFinancials` holds every filing processed for one company.
`as_of(cutoff)` returns, per (concept, period), the value from the
**earliest** filing filed on or before `cutoff` — the as-filed rule
([D-008](decision_log.md)): a later filing's comparative column for the same
period is a restatement, and D-008 says an "as of T" assessment uses the
value as originally filed, not a later restatement, unless an analyst
explicitly chooses otherwise. `restatements()` surfaces every case where a
later filing disagreed, rather than silently preferring one value — restated
figures are real information for a monitoring product, not noise to hide.
The golden set has one filing per company, so this path is unit-tested with
a synthetic multi-filing fixture (`tests/test_financials_company.py`), not
exercised end-to-end against the corpus yet.

## 11. What deliberately stayed out of Phase 5

- **Ratios, scores and thresholds** — Phase 6/7. `free_cash_flow` is the one
  exception: it is included as a derivation because it is a settled,
  unambiguous industry definition (`operating_cash_flow - capital_expenditures`),
  not a scored ratio — the same reasoning that keeps `debt/equity` out.
- **Full table-to-period alignment for uploaded PDFs** — `periods.py`
  provides the header-parsing primitive; wiring it into an automatic
  column-to-fiscal-year aligner for FR-04 uploads is deferred, because XBRL
  already solves the primary case (SEC filers) exactly, and building the
  harder problem for the secondary case was not the highest-value use of
  this phase's time.
- **An LLM anywhere in this pipeline.** Every decision above is a rule, a
  tag-priority list, or a documented tolerance window. No ambiguity
  encountered while building this justified reaching for one.
- **A general N-way reconciliation framework** across XBRL/HTML/PDF — see §7.

## 12. QM-01 — evaluation against the golden set

`scripts/evaluate_canonicalization.py` reuses the Phase 4 golden set
entirely from cache — no SEC requests, no PDF re-extraction, no re-rendering.
Dimensions are kept separate rather than collapsed into one number.

| Dimension | Before audit | After audit | Note |
|---|---:|---:|---|
| Value/period accuracy | 221/254 — 87.0% | **247/254 — 97.2%** | Against `reference_values.csv`; 88 non-annual reference rows excluded (§4) |
| Mismatch causes | 32 conflict, 1 other | **7 scope preference, 0 wrong values** | See below |
| Mean per-concept completeness | 68.7% | **88.8%** | Denominator changed too: roll-forward phantom periods removed (§15) |
| `total_debt` completeness | 25% | **86%** | |
| `interest_expense` completeness | 75% | **92%** | The 3 left are Apple, which tags no interest element |
| `CONFLICTING` facts, whole corpus | 50 | **3** | All capital expenditures, deliberately (§15) |
| `balance_sheet_equation` | 19/19 (11 circular) | **12/12 independent**, 16 suppressed | §8 |
| `cash_tie_out` | 17/18 | **20/21** | More computable after cash-flow conflicts cleared |
| Document corroboration | 75.9% | **73.6%** | Falls because summed debt figures appear in no single table cell |
| Sign-convention violations | not checked | **0** | §14 |

Full per-concept coverage, per-row mismatches with their cause category, and
the statement-classification mix are written to
`data/processed/golden_set/qm01_*.csv` and `qm01_summary.json` (gitignored,
like all of `data/` — rerun the script to reproduce).

**What the 7 remaining mismatches are.** All are the golden set's `LongTermDebt`
reference rows (iHeartMedia, Apple, Walmart, UPS), where the schema
deliberately resolves *noncurrent* long-term debt and the filer's
`LongTermDebt` is the total including the current portion (Apple FY2025:
90,678M = 78,328M noncurrent + 12,350M current). The reference value is
present on each fact as a `candidate`. This is a definition difference in the
ground truth, not a wrong value; counting it as such, value accuracy is 254/254.

**Independent confirmation of debt.** Resolved `total_debt` for the primary
period matches a separate total the filer tags elsewhere: iHeartMedia 20,655M
(`DebtLongtermAndShorttermCombinedAmount`), UPS 24,127M
(`DebtAndCapitalLeaseObligations`), Pyxus 1,328M
(`DebtInstrumentCarryingAmount`), Coca-Cola 45,492M (debt incl. current
maturities 43,941M + loans and notes payable 1,551M), Apple 98,657M (term debt
90,678M + commercial paper 7,979M).

**What is still missing, and why** (109 `MISSING` facts across the corpus):

| Cause | Concepts | Mapping gap? |
|---|---|---|
| Not presented by that business model | `inventory` (energy, telecom, media, retail-by-segment), `cost_of_goods_sold`/`gross_profit` (filers presenting costs by nature) | No — genuinely not applicable |
| Thin oldest comparative year (income statement plus total assets and equity from a note, no full balance sheet) | current items, debt, parent equity | No — not reported |
| No noncontrolling interest tagged | `noncontrolling_interest` | No — usually none exists; never assumed zero |
| No interest element at all | `interest_expense` (Apple) | No |
| Capex tags conflict | `free_cash_flow` (Pyxus, Expand) | Deliberate — see §15 |

## 13. Deferred ideas

- A `debt_components_tie` validation comparing summed `total_debt` with the
  filer's own total tags where present — the §12 cross-checks show it would
  work; deferred because it adds tags for a check this corpus already passes.
- Model the FX effect on cash (`EffectOfExchangeRateOn...`, tagged by 6/12
  filers) so `cash_tie_out` can tighten its 5% tolerance.
- `REQUIRES_REVIEW` is modelled but never raised; routing a validation failure
  onto the facts it implicates is the natural next step.
- Widen tag chains against a larger filer sample than 12 filings.
- Amended filings (10-K/A): none in the corpus. Each amendment is its own
  accession, so values cannot collide inside `resolve_filing`, but
  `CompanyFinancials.as_of` prefers the *earliest* filing, which means an
  original superseded by a correcting 10-K/A still wins. That follows D-008's
  as-filed wording but deserves an explicit decision before historical replay.
- Extension concepts: `companyfacts` exposes none for these 12 filers, so
  label-based extension matching could not be measured; it needs filing-level
  XBRL instances, not this API.
- Wire `periods.parse_period_label` into a table-column aligner for the FR-04
  upload path once that path has an accuracy requirement.

## 14. Units and sign convention

- **Unit.** Every canonical value is in whole US dollars, exactly as XBRL
  reports it — never pre-scaled to thousands or millions. `currency` records
  `USD`; a fact in any other unit is excluded, never converted. Phase 6 can
  divide any two canonical values without scale adjustment.
- **Signs** follow the XBRL balance-type convention, unchanged:
  - Balances, expenses and payments are **positive magnitudes**: assets,
    liabilities, debt, `cost_of_goods_sold`, `interest_expense`,
    `capital_expenditures`. So `free_cash_flow = operating_cash_flow -
    capital_expenditures`, and a negative capex is flagged by `sign_sanity`.
  - Results and net flows are **signed**: `net_income`, `operating_income`,
    `pretax_income`, `ebit` (negative = loss); the three net cash flows and
    `free_cash_flow` (negative = net outflow); equity (negative = deficit).
  - Verified across the golden set: every negative value occurs in a signed
    concept, and there are zero sign-convention violations.

## 15. The Phase 5 audit

A skeptical re-audit, run against the golden set rather than by inspection,
found plausible-looking values that were subtly wrong. Each is now fixed and
has a regression test built from the filing's real figures
(`tests/test_financials_audit_regressions.py`).

1. **Circular validation.** 11 of 19 balance-sheet "passes" validated a
   liabilities figure derived from the same identity. Now suppressed (§8).
2. **Derived liabilities overstated by the noncontrolling interest.** The
   derivation subtracted parent-only equity. Tesla FY2025: 55,669M derived vs
   54,941M reported. Equity is now split into parent, NCI and total, and the
   identity uses total equity.
3. **Scope differences read as conflicts.** 32 good values discarded
   (`net_income` 13, equity 9, `revenue` 5, `operating_cash_flow` 3).
   Fixed by `PREFERRED_SCOPE`.
4. **Debt components read as alternatives.** Short-term debt was one tag:
   Apple's omitted 7,979M of commercial paper (a 39% understatement returned as
   a confident `FOUND`); Walmart's omitted 6,596M of borrowings; Coca-Cola and
   Peabody, which tag debt together with finance leases, had no debt figure at
   all — Peabody, bankrupt months later, with 5,930M reclassified as current.
   Fixed by `COMPONENTS` groups and the leases elements.
5. **A deprecated interest element.** Tesla and UPS tag only
   `InterestExpenseNonoperating`; interest coverage was uncomputable for both.
6. **A 1% agreement tolerance** let iHeartMedia's 181M (0.9%) gap between
   total and noncurrent long-term debt count as "the same number". Now 0.1%.
7. **Phantom periods.** Roll-forward opening balances (equity three years
   back, prior-year cash) spawned full columns of `MISSING` balance-sheet rows
   for statements never presented — 17 of 45 balance-sheet slots.
8. **Latent guards added where the corpus showed no failure yet:** unit
   filtering, same-tag duplicate values as a conflict, derivation to a
   fixpoint, and sign checks on debt, expenses and capex.

**Checked and deliberately left alone.** Capital expenditures stays strict
`ALTERNATES`: Pyxus tags PP&E 48M and capital improvements 53M, and the data
cannot tell "additive" from "overlapping", so a visible conflict is safer than
a free-cash-flow figure that might double count. The Coca-Cola cash tie-out
miss is a real FX effect, so the tolerance was not loosened to hide it.

## 16. Phase 6 readiness

Phase 6 can call `financials.resolve_filing(...)` and ask
`filing.get("total_debt", "FY2025")` without knowing anything about PDFs, HTML,
XBRL tags, units, table layouts or extraction. The contract:

- Read `effective_value`. `None` means "cannot compute this input" — never 0.
- `get(...)` returning `None` means the filing did not present that statement
  for that period; a fact with `status=MISSING` means it presented the
  statement but this line could not be resolved. Both mean "no value".
- Values are whole USD with the sign convention in §14.
- Use `shareholders_equity` for shareholder-level ratios and `total_equity`
  when the ratio must match the balance-sheet identity; state which.
- `status`, `confidence`, `origin` and `candidates` are there for display and
  for choosing to warn — Phase 6 should surface a `DERIVED` or
  `MEDIUM`-confidence input, not re-resolve it.
- Phase 5 computes no ratios, scores or trends.
