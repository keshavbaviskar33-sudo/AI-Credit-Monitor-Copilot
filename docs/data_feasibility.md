# Data Feasibility — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | v0.2 — Phase 1 desk research, plus the Phase 3 decision gate ([D-013](decision_log.md)) run live against real sources |
| **Date** | 2026-09-13 (desk research); 2026-09-14 (decision gate, §6) |
| **Related** | [assumptions.md](assumptions.md) (A-04 – A-09, A-11, A-13, A-21) · [risks.md](risks.md) (R-01 – R-05, R-12) |

**Purpose.** Decide early whether the ML layer is feasible for a *US corporate
monitoring* product, and what must be settled in Phase 3. Facts are marked
**verified** (checked at the linked source) or **unverified** (believed but
not yet confirmed — must be checked before relying on it). §1–§5 are the
original Phase 1 desk research (2026-09-13); §6 records the Phase 3 decision
gate run against live sources on 2026-09-14.

---

## 1. Why this matters now

The ML model can only use features that the rest of the system can compute from
real company filings. If the training data uses variables, definitions,
companies or labels that the product cannot reproduce, the model's output is
meaningless in the UI — however good its test metrics look. The dataset choice
therefore constrains the canonical financial schema (Phase 5) and ratio engine
(Phase 6), so it must be considered before them.

## 2. Requirements for training data

| # | Requirement | Reason |
|---|---|---|
| DR-1 | **Unit of observation is a company-period** (firm-year), not a loan or a consumer | Product assesses companies |
| DR-2 | **US companies**, ideally SEC filers | Matches scope ([D-002](decision_log.md)) |
| DR-3 | **Features derivable from financial statements** available via SEC XBRL | Avoid training/serving skew (R-02) |
| DR-4 | **A clearly defined distress label with a known horizon** | Defines what the probability means (A-11) |
| DR-5 | **Temporal information** (fiscal year, ideally filing date) | Out-of-time evaluation; point-in-time correctness (R-03, R-04) |
| DR-6 | **Enough positive events** for an out-of-time test | Metric reliability (A-13) |
| DR-7 | **Licence permits use in a public portfolio repository** | R-12 |
| DR-8 | **Industry information** (or linkable identifiers) | Scope exclusions; future industry benchmarks |

## 3. Candidates

### 3.1 Rejected category — consumer credit datasets

Examples: Lending Club, German Credit, Home Credit, "Give Me Some Credit".
**Rejected:** the unit of observation is an individual borrower or loan, with no
company financial statements (fails DR-1, DR-3). Popular, but wrong for this product.

### 3.2 Candidate A — US bankruptcy prediction dataset (NYSE/NASDAQ, 1999–2018)

Sources: [GitHub: sowide/bankruptcy_dataset](https://github.com/sowide/bankruptcy_dataset) · [Kaggle mirror](https://www.kaggle.com/datasets/utkarshx27/american-companies-bankruptcy-prediction-dataset) · paper: *Machine Learning for Bankruptcy Prediction in the American Stock Market: Dataset and Benchmarks*, Future Internet (MDPI), 2022.

| Aspect | Finding | Verified? |
|---|---|---|
| Coverage | 8,262 companies, 78,682 firm-year observations, 1999–2018, NYSE and NASDAQ | Verified |
| Label | Fiscal year before a Chapter 11 or Chapter 7 filing labelled 1; otherwise 0 | Verified |
| Suggested split | Train 1999–2011, validation 2012–2014, test 2015–2018 (out-of-time) | Verified |
| Missing values | Authors state none | Verified (as claimed by authors) |
| Identifiers | **Anonymised**; authors state a non-anonymised version cannot be released due to the licence under which data was retrieved | Verified |
| Features | 18 raw accounting variables, X1–X18. Confirmed X1–X13 from the Kaggle data card: X1 current assets, X2 cost of goods sold, X3 depreciation & amortisation, X4 EBITDA, X5 inventory, X6 net income, X7 total receivables, X8 market value (market capitalisation), X9 net sales, X10 total assets, X11 total long-term debt, X12 EBIT, X13 gross profit. X14–X18 not confirmed (source page truncates after X13) | **Partially verified** (X1–X13) |
| Industry field | `Division` (SIC division letter) and `MajorGroup` (2-digit SIC major group) present per firm-year | Verified (inspected raw CSV, 2026-09-14) |
| Licence for reuse | GitHub repo: **CC-BY-4.0** (`LICENSE.md`). Kaggle mirror's own metadata claims **CC0 (public domain)** instead — the two distribution channels disagree. Treat as **CC-BY-4.0** (the more restrictive, and the source repo's own claim) and follow its citation request | Verified (2026-09-14), with a noted discrepancy |
| Class balance | 78,682 firm-years: 73,462 `alive`, 5,220 `failed` (≈6.6% failure rate) | Verified (inspected raw CSV, 2026-09-14) |

**Fit:** best readily available match for DR-1, DR-2, DR-4, DR-5.
**Concerns:**
- Anonymised → labels cannot be audited, companies cannot be linked to SEC filings, and demo companies cannot be excluded with certainty (R-13).
- Underlying source probably a commercial database with standardised definitions → **likely skew** against as-reported XBRL values (R-02, A-09).
- Features include market value (if confirmed), which is not in financial statements and would need a separate market-data source at inference.
- Some public notebooks on this dataset report near-perfect accuracy — a strong signal of leakage-prone evaluation (random splits across a company's years), not of an easy problem (R-04).

### 3.3 Candidate B — Self-built: SEC XBRL financials + public bankruptcy records

Sources: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [SEC developer resources](https://www.sec.gov/about/developer-resources) · [Florida-UCLA-LoPucki Bankruptcy Research Database](https://lopucki.law.ufl.edu/).

| Aspect | Finding | Verified? |
|---|---|---|
| SEC APIs | `submissions`, `companyconcept`, `companyfacts`, `frames` on data.sec.gov; no authentication or API key | Verified |
| Access rules | ≤ 10 requests/second per user; unclassified bots not permitted (declared User-Agent expected) | Verified |
| Bulk data | Nightly `companyfacts.zip` and `submissions.zip` | Verified |
| Per-fact filing metadata | Accession number, form, fiscal year/period and filing date per fact | Verified — `companyfacts` JSON carries `accn`, `form`, `fy`, `fp`, `filed`, `end` on every datapoint (checked 4 sample companies, 2026-09-14) |
| XBRL history | Structured financial data for US operating companies from roughly 2009–2011 onward (phased by filer size) | Verified for the 4 sampled companies — earliest 10-K datapoints filed 2012 for FY2010/2011; consistent with the phase-in date |
| Bankruptcy labels (BRD) | Over 1,000 large public-company bankruptcies filed since Oct 1979; cases table free to download; **no longer updated after the December 2022 update** | Verified |
| BRD inclusion criteria | "Large" = ≥ $100M assets in 1980 dollars; "public" = filed a 10-K within ~3 years before bankruptcy | Verified (via library/search summary) |
| BRD use conditions | The User's Manual states: "We license the Cases table for both commercial and academic use." `conditions_of_use.php` additionally requires citing "Florida-UCLA-LoPucki Bankruptcy Research Database" as the data source, and asks academic users to post a 2–10 word project description. No redistribution clause found for the raw table itself — treat as: derive from it, don't republish it verbatim | Verified (read User's Manual + conditions_of_use page, 2026-09-14) — resolves A-21 |
| BRD ↔ SEC linking | Whether BRD includes CIK or another reliable identifier | **Verified — yes.** The Cases table has a `CikBefore` field (and `CikEmerging`, `GvkeyBefore`, `Cusip6`/`Cusip9`). Of 1,218 cases, 992 have a non-null `CikBefore` |
| BRD industry field | (new) `SICPrimary` / `SICDescription` per case | Verified — present |
| Linkable events (rough count) | Of 1,218 BRD cases: 426 filed 2009+ with a `CikBefore`; 299 filed 2011+ with a `CikBefore` — both comfortably above the "100+" heuristic in §5 | Verified count from the downloaded Cases table (2026-09-14); **not yet** verified that all of them have ≥2 prior annual XBRL periods — see spot-check below |
| ≥2 prior annual periods per case | Spot-checked 4 companies (21st Century Oncology, AAC Holdings, A123 Systems, A.M. Castle) against `companyfacts`: 3 of 4 had 14–23 pre-bankruptcy 10-K datapoints for `Assets` across multiple fiscal years; A123 Systems had only 1 pre-bankruptcy 10-K filing, but that filing itself reports 2 fiscal years (FY2010, FY2011) of comparatives | Verified for n=4 only — a full count across all ~300–426 linkable cases is Phase 3 implementation work, not yet done |

**Fit:** strongest on DR-3 (training and inference use the *same* source → no
definitional skew), DR-5 (true filing dates → point-in-time), DR-8 (SIC codes
from SEC). Fully auditable and non-anonymised.
**Concerns:**
- **Few events.** Only large public-company bankruptcies, and only those in the XBRL era (≈2009–2022) → possibly too few for a reliable out-of-time test (DR-6).
- **Label noise.** Smaller public companies that went bankrupt are not in BRD and would be wrongly labelled 0 unless handled (e.g. restricting the population to BRD's "large" definition).
- Significant data engineering (entity linking, concept mapping, point-in-time selection) — but that engineering is itself the product's data layer, so it is not wasted.

### 3.4 Candidate C — Polish companies bankruptcy data (UCI)

Source: [UCI Machine Learning Repository #365](https://archive.ics.uci.edu/dataset/365/polish+companies+bankruptcy+data).

| Aspect | Finding | Verified? |
|---|---|---|
| Coverage | Polish companies; bankrupt firms analysed 2000–2012, operating firms 2007–2013; source EMIS | Verified |
| Features | 64 financial ratios (e.g. net profit/total assets, total liabilities/total assets, working capital/total assets) | Verified |
| Label | Five files by horizon: bankruptcy status after 1–5 years (e.g. 5th-year file: 5,910 instances, 410 bankrupt) | Verified |
| Missing values | Present | Verified |
| Licence | CC BY 4.0 | Verified |

**Fit:** clean licence, ratio-based, multiple horizons.
**Concerns:** wrong geography and accounting regime for a US product (fails
DR-2); no reliable time split within files. **Use at most as a secondary
methodology benchmark**, never as the production model's training data.

### 3.5 Not accessible — commercial sources

Compustat/CRSP (via WRDS), Moody's Default & Recovery Database, S&P rating
histories and audit-opinion databases would be ideal (richer labels such as
defaults and downgrades) but require paid/institutional access. Out of scope
unless access becomes available.

## 4. Comparison

| Requirement | A: US bankruptcy dataset | B: Self-built SEC + BRD | C: Polish UCI |
|---|---|---|---|
| DR-1 Company-period | ✅ | ✅ | ✅ |
| DR-2 US | ✅ | ✅ | ❌ |
| DR-3 Same features as inference | ⚠️ likely skew | ✅ | ❌ |
| DR-4 Defined label | ✅ bankruptcy next year | ✅ bankruptcy (large firms) | ✅ multiple horizons |
| DR-5 Temporal / point-in-time | ⚠️ fiscal year only | ✅ filing dates | ⚠️ limited |
| DR-6 Enough events | ✅ likely | ✅ 178 usable, full-scale audit (2026-09-14) | ✅ |
| DR-7 Licence | ✅ CC-BY-4.0 (GitHub repo; Kaggle mirror disagrees, claims CC0) | ✅ BRD: commercial+academic use, attribution required · ✅ SEC public | ✅ CC BY 4.0 |
| DR-8 Industry | ✅ `Division`/`MajorGroup` (SIC) | ✅ SIC | ❌ |
| Effort | Low | High | Low |

## 5. Preliminary recommendation and Phase 3 decision gate

No dataset is a clean fit. The recommendation is a **time-boxed gate at the
start of Phase 3**, not a choice made now on unverified details:

1. **Check licences first** (A and BRD). A dataset that cannot be used publicly is out.
2. **Feasibility spike on Candidate B:** download the BRD cases table and
   SEC bulk data, and count bankruptcy events that can be linked to a CIK with
   at least two prior annual XBRL periods.
3. **Inspect Candidate A:** confirm feature list, industry field, class balance
   per year; map each feature to XBRL concepts and mark mapping quality.
4. **Decide:**
   - If B yields enough linkable events for a meaningful out-of-time test
     (working heuristic: on the order of 100+, to be finalised with the
     statistical reasoning in Phase 3) → **use B as primary**; optionally use A
     as an external comparison.
   - Otherwise → **use A as primary**, with a documented feature mapping,
     quantified skew checks on overlapping years, and prominent applicability
     warnings; use B-derived companies for the demo and serving-side validation.
5. Record the choice and its reasoning as a decision-log entry, and write the
   data dictionary for the chosen dataset.

**Gate result (2026-09-14): both licences clear, and B clears the event-count
heuristic (178 usable cases, confirmed at full scale, against a 100+ bar) →
Candidate B is the primary training source, with Candidate A kept as an
external comparison.** Recorded as [D-013](decision_log.md). Full details
in §7.

## 6. Phase 3 decision gate — findings (2026-09-14)

This section records what the gate steps in §5 actually found, run against
live sources rather than the desk research above.

**Step 1 — licence checks.**
- **Candidate A:** the source GitHub repo (`sowide/bankruptcy_dataset`) is
  CC-BY-4.0 (its `LICENSE.md`). Its Kaggle mirror's own page metadata claims
  CC0 instead — the two disagree. Following the more conservative and
  authoritative source, this project treats Candidate A as CC-BY-4.0 and
  follows the GitHub README's citation request (Pellegrino et al. 2024;
  Lombardo et al., *Future Internet* 2022) wherever it is used.
- **BRD:** the User's Manual states the Cases table is licensed "for both
  commercial and academic use," free of charge. `conditions_of_use.php`
  requires citing "Florida-UCLA-LoPucki Bankruptcy Research Database" as the
  source and (for academic users) posting a short project description. No
  clause restricting non-commercial reuse or redistribution of derived
  results was found. **Conclusion: clear to use, with attribution — resolves
  A-21.** This project will derive from the Cases table (link to CIKs, use
  dates/labels) rather than republish it verbatim.
- **SEC EDGAR:** confirmed public-domain / open-reuse policy, 10 req/s limit,
  descriptive `User-Agent` required — already reflected in
  `SEC_USER_AGENT` (`.env.example`) and `sec_max_requests_per_second` (set to
  8, below the limit) in `src/credit_risk_copilot/config.py`.

**Step 2 — feasibility spike on Candidate B.** Downloaded the live BRD Cases
table (`Florida-UCLA-LoPucki Bankruptcy Research Database 1-12-2023.zip`,
1,218 cases, 217 fields).
- 992 of 1,218 cases carry a non-null `CikBefore`.
- Initial 4-company spot-check (21st Century Oncology, AAC Holdings, A123
  Systems, A.M. Castle & Co.): all resolved with real XBRL data; per-fact
  metadata (`accn`, `form`, `fy`, `fp`, `filed`, `end`) is present exactly as
  needed for the point-in-time rule ([D-008](decision_log.md)); 3 of 4 had
  ample pre-bankruptcy annual history, 1 had only its single pre-bankruptcy
  10-K.
- **Full-scale run** (`scripts/phase3_data_audit.py`, all 992 cases with a
  CIK, cached under `data/raw/`): 527 predate the XBRL era (bankruptcy filed
  before 2008) and were skipped; of the remaining 465, 144 returned no XBRL
  data at all (`companyfacts` 404 — concentrated in 2008–2011, matching
  XBRL's staggered phase-in by filer size, not a data bug); 321 returned
  real data, of which **178 have ≥2 pre-bankruptcy annual XBRL periods**.
  Full breakdown in [data_dictionary.md §5](data_dictionary.md).
- **178 usable positive events** clears the "100+" heuristic, but is well
  below the earlier rough estimate of 299–426 "linkable" cases — that
  estimate only checked for a CIK + a plausible year, not for actual usable
  pre-filing history. 178 events spread across a ~2009–2022 out-of-time
  design is a real statistical-power constraint for Phase 8/9, not just a
  headline number to clear a bar.
- **Negative-class universe (rough):** of 8,020 SEC filers with a ticker,
  939 unique CIKs have ever appeared in BRD at all, leaving ~7,973
  candidates — comfortably large, but unfiltered by SIC/history requirements
  (see [data_dictionary.md §5](data_dictionary.md)).
- **Not yet done:** applying the D-006 financial-sector SIC exclusions to
  the negative universe, and investigating the 144 "no XBRL" cases enough to
  decide whether any are recoverable (e.g. a stale `CikBefore` that should
  map to a successor CIK). Both are Phase 5 work.

**Step 3 — inspect Candidate A.** Downloaded the live CSV
(`american_bankruptcy_dataset.csv`, 78,682 rows × 23 columns).
- Confirmed columns: `company_name` (anonymised, e.g. `C_1`), `fyear`,
  `status_label` (`alive`/`failed`), `X1`–`X18`, `Division`, `MajorGroup`.
- Class balance: 73,462 `alive` vs 5,220 `failed` (≈6.6% failure rate).
- Feature definitions X1–X13 confirmed from the Kaggle data card (see §3.2
  table); X14–X18 remain unconfirmed (the source page truncates) — mapping
  the full feature list to XBRL/ratio-engine concepts is Phase 3/6 work once
  X14–X18 are pinned down (e.g. from the cited paper, if it becomes
  accessible, or by correlating against Candidate B's own computed ratios).

**Step 4 — decision.** B clears DR-6 on the stated heuristic and is strongest
on DR-3/DR-5/DR-8 per §4 → **Candidate B (self-built SEC + BRD) is primary.**
Candidate A is kept as an external comparison/benchmark (not for production
training), consistent with §3.4's treatment of Candidate C. See
[D-013](decision_log.md) for the formal record.

**Label semantics, whichever option wins:** the model will estimate *the
likelihood of a bankruptcy filing within roughly the next fiscal year, for
companies resembling the training population*. It will not estimate an
early-warning "deterioration" event, and the UI must say so ([D-010](decision_log.md)).

## 7. What this means for the ML/NLP design

- The ML model uses **financial features only**. No public dataset pairs
  bankruptcy labels with NLP risk signals from the same filings, so NLP signals
  cannot be model inputs without building that training set ([D-004](decision_log.md)).
  NLP signals are combined with model output at the synthesis/contradiction layer instead.
- Features should be **ratios computable by the Phase 6 engine**, so the model
  and the deterministic analysis share one definition of each ratio.
