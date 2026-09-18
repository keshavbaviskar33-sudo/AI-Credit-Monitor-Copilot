"""Synthetic `companyfacts` payloads and filing refs for Phase 8 tests.

Not a test module (no `test_` prefix). Builds the smallest possible real-shaped
`companyfacts` JSON so the modelling tests exercise the genuine
resolver -> ratios -> health -> features path rather than a mock of it. The
point-in-time tests are only meaningful if the thing under test is the real
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FakeFilingRef:
    """Structurally `sec_edgar.FilingRef`."""

    cik: int
    accession: str
    form: str
    filed: str
    period: str


#: A minimal but self-consistent balance sheet / income statement / cash flow
#: set: enough tags for most of the ratio catalog to resolve, with the
#: accounting identities holding so `validation.py` does not flag every period.
_TAG_TEMPLATE: dict[str, float] = {
    "Assets": 1000.0,
    "AssetsCurrent": 400.0,
    "Liabilities": 600.0,
    "LiabilitiesCurrent": 250.0,
    "StockholdersEquity": 400.0,
    "CashAndCashEquivalentsAtCarryingValue": 120.0,
    "InventoryNet": 90.0,
    "AccountsReceivableNetCurrent": 110.0,
    "LongTermDebtNoncurrent": 300.0,
    "LongTermDebtCurrent": 50.0,
    "Revenues": 900.0,
    "CostOfGoodsAndServicesSold": 540.0,
    "OperatingIncomeLoss": 120.0,
    "NetIncomeLoss": 60.0,
    "InterestExpense": 30.0,
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 90.0,  # noqa: E501
    "NetCashProvidedByUsedInOperatingActivities": 150.0,
    "NetCashProvidedByUsedInInvestingActivities": -80.0,
    "NetCashProvidedByUsedInFinancingActivities": -40.0,
    "PaymentsToAcquirePropertyPlantAndEquipment": 70.0,
}

#: Tags reported at a point in time (a balance) rather than over a period.
_INSTANT_TAGS = frozenset(
    {
        "Assets",
        "AssetsCurrent",
        "Liabilities",
        "LiabilitiesCurrent",
        "StockholdersEquity",
        "CashAndCashEquivalentsAtCarryingValue",
        "InventoryNet",
        "AccountsReceivableNetCurrent",
        "LongTermDebtNoncurrent",
        "LongTermDebtCurrent",
    }
)


def filing(
    *,
    accession: str,
    filed: str,
    period_end: str,
    years: dict[int, float],
    form: str = "10-K",
    overrides: dict[tuple[int, str], float] | None = None,
) -> dict[str, Any]:
    """One filing's contribution to a companyfacts payload.

    `years` maps fiscal year -> a multiplier applied to every template value,
    so a declining company is expressed as `{2018: 1.0, 2019: 0.8, 2020: 0.5}`.
    `overrides` sets one exact `(year, tag)` value, for tests that need a
    specific number (a restatement, a negative equity).
    """
    entries: dict[str, list[dict[str, Any]]] = {}
    for year, scale in years.items():
        for tag, base in _TAG_TEMPLATE.items():
            value = (overrides or {}).get((year, tag), base * scale)
            entry: dict[str, Any] = {
                "end": f"{year}-12-31",
                "val": value,
                "accn": accession,
                "fy": max(years),
                "fp": "FY",
                "form": form,
                "filed": filed,
            }
            if tag not in _INSTANT_TAGS:
                entry["start"] = f"{year}-01-01"
            entries.setdefault(tag, []).append(entry)
    return {"accession": accession, "filed": filed, "period_end": period_end, "entries": entries}


def company_facts(*filings: dict[str, Any]) -> dict[str, Any]:
    """Merge filing contributions into one `companyfacts`-shaped payload."""
    us_gaap: dict[str, Any] = {}
    for contribution in filings:
        for tag, entries in contribution["entries"].items():
            concept = us_gaap.setdefault(tag, {"label": tag, "units": {"USD": []}})
            concept["units"]["USD"].extend(entries)
    return {"cik": 1, "entityName": "Test Co", "facts": {"us-gaap": us_gaap}}


def filing_refs(*filings: dict[str, Any], cik: int = 1) -> list[FakeFilingRef]:
    return [
        FakeFilingRef(
            cik=cik,
            accession=contribution["accession"],
            form="10-K",
            filed=contribution["filed"],
            period=contribution["period_end"],
        )
        for contribution in filings
    ]


def declining_company(cik: int = 1) -> tuple[dict[str, Any], list[FakeFilingRef]]:
    """Three annual filings, each reporting its own year plus two comparatives,
    with the business deteriorating through time."""
    scales = {2017: 1.0, 2018: 0.9, 2019: 0.7, 2020: 0.4}
    # The accession's middle digits are the *filing* year, as real EDGAR
    # accessions are -- a FY2018 report filed in March 2019 is a -19- accession.
    filings = [
        filing(
            accession=f"0000000000-{str(year + 1)[2:]}-000001",
            filed=f"{year + 1}-03-01",
            period_end=f"{year}-12-31",
            years={y: scales[y] for y in range(max(2017, year - 2), year + 1)},
        )
        for year in (2018, 2019, 2020)
    ]
    return company_facts(*filings), filing_refs(*filings, cik=cik)
