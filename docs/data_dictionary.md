# Data Dictionary — Training Dataset (Candidate B)

| | |
|---|---|
| **Status** | Draft v0.1 — Phase 3 |
| **Date** | 2026-09-14 |
| **Related** | [D-013](decision_log.md) · [data_feasibility.md §6](data_feasibility.md) · [decision_log.md](decision_log.md) (D-004, D-007, D-008, D-010) |

This is the data dictionary for the chosen ML training dataset ([D-013](decision_log.md)): a self-built join of SEC XBRL financial facts and the Florida-UCLA-LoPucki Bankruptcy Research Database (BRD). It defines the unit of observation, the label, the features, and provenance — the four things [data_feasibility.md](data_feasibility.md) DR-1–DR-8 require before this feeds the ratio engine (Phase 6) or the baseline model (Phase 8).

## 1. Unit of observation

A **company-fiscal-year** (firm-year): one operating company, one fiscal year, identified by SEC **CIK** + fiscal year end date. This matches DR-1.

## 2. Population

- **Positive class (bankrupt):** companies in the BRD Cases table with a resolvable `CikBefore`, restricted to fiscal years with real pre-filing SEC XBRL data (see §5, the linkage audit). BRD's own inclusion rule already applies: "large" (≥$100M assets in 1980 dollars) and "public" (filed a 10-K within ~3 years before the bankruptcy petition) — see [data_feasibility.md §3.3](data_feasibility.md).
- **Negative class (not bankrupt that year):** all other fiscal years for the same population of US SEC filers with XBRL data, per [scope.md](scope.md) — non-financial operating companies (D-006 exclusions apply once SIC exclusion ranges are finalised in Phase 5/7), excluding any fiscal year that is itself a positive-class year for that company. A rough universe size is in §5.

## 3. Target definition

**Label = 1** if the company filed a Chapter 7 or Chapter 11 bankruptcy petition (per the BRD `Chapter` field) within roughly the 12 months following a given fiscal year end; **label = 0** otherwise. This mirrors Candidate A's convention ("the fiscal year before the chapter filing is labelled 1") so the two datasets stay comparable ([data_feasibility.md §3.2](data_feasibility.md)).

This is **not** a probability of default (D-010): it is an estimated likelihood of a bankruptcy filing, for companies resembling the training population, over the stated horizon.

## 4. Provenance fields (point-in-time rule, D-008)

Every fact used at training or inference time must carry, from SEC's `companyfacts` API:

| Field | Source | Purpose |
|---|---|---|
| `cik` | SEC | Entity identifier, links to BRD `CikBefore` |
| `accn` | SEC (`companyfacts`) | Accession number of the filing that reported the fact |
| `form` | SEC (`companyfacts`) | e.g. `10-K` — restrict to annual filings |
| `fy` / `fp` | SEC (`companyfacts`) | Fiscal year / period (`FY` for annual) |
| `filed` | SEC (`companyfacts`) | Date the filing was actually filed — **this, not `end`, is what the point-in-time rule filters on** |
| `end` | SEC (`companyfacts`) | Fiscal period end date the value covers |
| `val` | SEC (`companyfacts`) | The reported value |

An assessment "as of" date *T* must only use facts with `filed <= T` (D-008). Verified present on every sampled fact — see [data_feasibility.md §6](data_feasibility.md).

## 5. Linkage audit (Phase 3, run 2026-09-14)

Full-scale version of the 4-company spot-check in `data_feasibility.md §6`, run by `scripts/phase3_data_audit.py` against live SEC data for all 992 BRD cases with a `CikBefore`. Raw output in `data/processed/` (gitignored — rerun the script to reproduce; each SEC call is cached under `data/raw/`, so a rerun only fetches what's missing).

| Outcome | Count | Notes |
|---|---:|---|
| Total BRD cases with a CIK | 992 | |
| Skipped — bankruptcy filed before 2008 | 527 | Predates XBRL; a `companyfacts` lookup would trivially return nothing |
| `companyfacts` returned 404 (no XBRL on file) | 144 | Concentrated in 2008–2011 (34/64/31/12/3 by year) — consistent with XBRL's staggered phase-in by filer size, not a bug |
| `companyfacts` returned data (`ok`) | 321 | |
| — of which, **≥2 pre-bankruptcy annual XBRL periods** | **178** | **This is the usable positive-event count** |
| — of which, 1 period only | 18 | Has a single pre-bankruptcy 10-K (which itself may report 2 fiscal years of comparatives — not counted as 2 "periods" here since only one filing's `filed` date is confirmed pre-bankruptcy) |
| — of which, 0 periods | 125 | XBRL exists for the company, but none of it was filed before this bankruptcy (e.g. only post-emergence filings) |

**Result: 178 usable positive events** — above the "100+" working heuristic in [data_feasibility.md §5](data_feasibility.md), but materially lower than the earlier rough estimate of 299–426 "linkable" cases (that count only checked for a CIK + year, not for actual usable pre-filing history). D-013 stands on this more precise number, but 178 events split across a ~2009–2022 out-of-time train/validation/test design (mirroring Candidate A's split style) means each split may only hold a few dozen positive events — a real statistical-power constraint for Phase 8/9 to design around (e.g. wider validation/test windows, or reporting confidence intervals rather than point estimates).

**Negative-class universe (rough, unfiltered):** of 8,020 SEC filers with a ticker, 939 unique CIKs have ever appeared in the BRD Cases table at all (not just the linkable/usable ones) — leaving **7,973** candidate non-bankrupt companies. This is a proxy, not a final count: it does not yet exclude financial-sector SIC codes (D-006), require a minimum XBRL history, or account for filers without a ticker.

## 6. Features (raw XBRL concepts, pre-ratio)

Phase 6 defines the actual ratio engine; this is the raw `us-gaap` concept set the audit confirmed is present for sampled filers and that the ratio engine will draw on: `Assets`, `Liabilities`, `StockholdersEquity`, `AssetsCurrent`, `LiabilitiesCurrent`, `Revenues` (or `SalesRevenueNet`), `NetIncomeLoss`, `OperatingIncomeLoss`, `CashAndCashEquivalentsAtCarryingValue`, `LongTermDebt`. Exact concept-to-ratio mapping, and handling of companies that use alternate tags for the same concept, is Phase 5/6 work.

## 7. Known limitations

- BRD stopped updating after its December 2022 release — no bankruptcies after that date are labelled (D-013).
- BRD only covers *large* public-company bankruptcies; smaller bankrupt public companies are absent from BRD and would be silently mislabelled 0 unless excluded from the negative population.
- The exact SIC exclusion ranges for non-financial operating companies (D-006) are finalised in Phase 5/7, not here — the negative-universe estimate in §5 does not yet apply them.
- Candidate A (external comparison only, never training data) still has unconfirmed X14–X18 feature definitions; do not use it for anything beyond a benchmark until that's resolved.
