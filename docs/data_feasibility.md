# Data Feasibility — AI Credit Risk Monitor Copilot

| | |
|---|---|
| **Status** | Draft v0.1 — Phase 1 desk research (no data downloaded, no modelling) |
| **Date** | 2026-09-13 |
| **Related** | [assumptions.md](assumptions.md) (A-04 – A-09, A-11, A-13, A-21) · [risks.md](risks.md) (R-01 – R-05, R-12) |

**Purpose.** Decide early whether the ML layer is feasible for a *US corporate
monitoring* product, and what must be settled in Phase 3. Facts are marked
**verified** (checked at the linked source on 2026-09-13) or **unverified**
(believed but not yet confirmed — must be checked before relying on it).

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
| Features | Believed to be ~18 raw accounting variables (e.g. current assets, EBIT, total liabilities, market value) | **Unverified** |
| Industry field | Unknown | **Unverified** |
| Licence for reuse | Not identified | **Unverified** |
| Class balance | Not stated in the README | **Unverified** |

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
| Per-fact filing metadata | Accession number, form, fiscal year/period and filing date per fact | **Unverified** (A-05) |
| XBRL history | Structured financial data for US operating companies from roughly 2009–2011 onward (phased by filer size) | **Unverified** |
| Bankruptcy labels (BRD) | Over 1,000 large public-company bankruptcies filed since Oct 1979; cases table free to download; **no longer updated after the December 2022 update** | Verified |
| BRD inclusion criteria | "Large" = ≥ $100M assets in 1980 dollars; "public" = filed a 10-K within ~3 years before bankruptcy | Verified (via library/search summary) |
| BRD use conditions | Terms exist; restrictions on redistribution / public use not yet read | **Unverified** (A-21) |
| BRD ↔ SEC linking | Whether BRD includes CIK or another reliable identifier | **Unverified** |

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
| DR-6 Enough events | ✅ likely | ⚠️ unknown | ✅ |
| DR-7 Licence | ❓ | ❓ (BRD terms) · ✅ SEC public | ✅ CC BY 4.0 |
| DR-8 Industry | ❓ | ✅ SIC | ❌ |
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

**Label semantics, whichever option wins:** the model will estimate *the
likelihood of a bankruptcy filing within roughly the next fiscal year, for
companies resembling the training population*. It will not estimate an
early-warning "deterioration" event, and the UI must say so ([D-010](decision_log.md)).

## 6. What this means for the ML/NLP design

- The ML model uses **financial features only**. No public dataset pairs
  bankruptcy labels with NLP risk signals from the same filings, so NLP signals
  cannot be model inputs without building that training set ([D-004](decision_log.md)).
  NLP signals are combined with model output at the synthesis/contradiction layer instead.
- Features should be **ratios computable by the Phase 6 engine**, so the model
  and the deterministic analysis share one definition of each ratio.
