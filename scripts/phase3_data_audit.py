"""Phase 3 data audit: BRD <-> SEC linkage at scale, and a rough negative-class
universe count.

This turns the Phase 2 4-company spot-check (docs/data_feasibility.md #6)
into a full count across every BRD case with a CIK, and gives a first-order
estimate of how large the non-bankrupt ("negative") company-year population
could be. Outputs feed docs/data_feasibility.md and docs/data_dictionary.md.

Everything downloaded is cached under data/raw/ (gitignored) so reruns don't
re-hit SEC or the BRD site. Usage:

    uv run python scripts/phase3_data_audit.py
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

import pandas as pd
import requests

from credit_risk_copilot.config import get_settings
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.sec_edgar import SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
BRD_DOWNLOAD_URL = "https://lopucki.law.ufl.edu/download_cases_table.php"

# XBRL was phased in for US operating companies from roughly 2009 onward
# (docs/data_feasibility.md). A bankruptcy filed before this could not
# possibly have pre-filing XBRL data, so skip fetching those cases.
XBRL_ERA_CUTOFF_YEAR = 2008


def fetch_brd_cases() -> pd.DataFrame:
    cache_csv = RAW_DIR / "brd" / "cases.csv"
    if cache_csv.exists():
        logger.info("Using cached BRD cases table at %s", cache_csv)
        return pd.read_csv(cache_csv, encoding="latin-1", low_memory=False)

    settings = get_settings()
    logger.info("Downloading BRD cases table from %s", BRD_DOWNLOAD_URL)
    response = requests.get(
        BRD_DOWNLOAD_URL,
        headers={"User-Agent": settings.sec_user_agent},
        timeout=settings.sec_request_timeout_seconds,
    )
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        csv_name = next(name for name in zf.namelist() if name.lower().endswith(".csv"))
        cache_csv.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(csv_name) as src, cache_csv.open("wb") as dst:
            dst.write(src.read())

    return pd.read_csv(cache_csv, encoding="latin-1", low_memory=False)


def audit_linkage(cases: pd.DataFrame, client: SecEdgarClient) -> pd.DataFrame:
    linkable = cases[cases["CikBefore"].notna()].copy()
    linkable["CikBefore"] = linkable["CikBefore"].astype(int)

    rows: list[dict[str, object]] = []
    for i, (_, case) in enumerate(linkable.iterrows(), start=1):
        cik = case["CikBefore"]
        name = case["NameCorp"]
        filing_date = str(case["DateFiled"])
        year_filed = case["YearFiled"]

        if year_filed < XBRL_ERA_CUTOFF_YEAR:
            rows.append(
                {
                    "CikBefore": cik,
                    "NameCorp": name,
                    "DateFiled": filing_date,
                    "YearFiled": year_filed,
                    "status": "skipped_pre_xbrl_era",
                    "pre_bankruptcy_annual_periods": 0,
                }
            )
            continue

        if i % 50 == 0:
            logger.info("Linkage audit: %d/%d", i, len(linkable))

        try:
            facts = client.company_facts(cik)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            rows.append(
                {
                    "CikBefore": cik,
                    "NameCorp": name,
                    "DateFiled": filing_date,
                    "YearFiled": year_filed,
                    "status": f"http_error_{status_code}",
                    "pre_bankruptcy_annual_periods": 0,
                }
            )
            continue
        except requests.RequestException as exc:
            rows.append(
                {
                    "CikBefore": cik,
                    "NameCorp": name,
                    "DateFiled": filing_date,
                    "YearFiled": year_filed,
                    "status": f"error_{type(exc).__name__}",
                    "pre_bankruptcy_annual_periods": 0,
                }
            )
            continue

        usgaap = facts.get("facts", {}).get("us-gaap", {})
        assets_units = usgaap.get("Assets", {}).get("units", {})
        assets_entries: list[dict[str, object]] = next(iter(assets_units.values()), [])
        pre_bankruptcy_years = {
            entry["fy"]
            for entry in assets_entries
            if entry.get("form") == "10-K"
            and entry.get("fp") == "FY"
            and str(entry.get("filed", "9999-99-99")) < filing_date
        }
        rows.append(
            {
                "CikBefore": cik,
                "NameCorp": name,
                "DateFiled": filing_date,
                "YearFiled": year_filed,
                "status": "ok",
                "has_assets_concept": bool(assets_entries),
                "pre_bankruptcy_annual_periods": len(pre_bankruptcy_years),
            }
        )

    return pd.DataFrame(rows)


def audit_negative_universe(client: SecEdgarClient, brd_ciks: set[int]) -> dict[str, int]:
    tickers = client.company_tickers()
    all_ciks = {int(row["cik_str"]) for row in tickers.values()}
    return {
        "total_sec_filers_with_ticker": len(all_ciks),
        "ever_bankrupt_in_brd": len(brd_ciks),
        "candidate_negative_universe": len(all_ciks - brd_ciks),
    }


def main() -> None:
    configure_logging()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    cases = fetch_brd_cases()
    client = SecEdgarClient(cache_dir=RAW_DIR)

    linkage = audit_linkage(cases, client)
    linkage_path = PROCESSED_DIR / "brd_sec_linkage_audit.csv"
    linkage.to_csv(linkage_path, index=False)

    usable = linkage[
        (linkage["status"] == "ok") & (linkage["pre_bankruptcy_annual_periods"] >= 2)
    ]
    logger.info("Total BRD cases with a CIK: %d", len(linkage))
    logger.info(
        "Usable cases (>=2 pre-bankruptcy annual XBRL periods): %d", len(usable)
    )
    logger.info("Full linkage audit written to %s", linkage_path)

    brd_ciks = set(cases["CikBefore"].dropna().astype(int))
    negative_summary = audit_negative_universe(client, brd_ciks)
    logger.info("Negative-class universe estimate: %s", negative_summary)

    summary_path = PROCESSED_DIR / "negative_universe_summary.json"
    summary_path.write_text(json.dumps(negative_summary, indent=2), encoding="utf-8")

    status_counts = linkage["status"].value_counts().to_dict()
    period_counts = (
        linkage.loc[linkage["status"] == "ok", "pre_bankruptcy_annual_periods"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    report = {
        "total_cases_with_cik": len(linkage),
        "status_counts": status_counts,
        "usable_cases_2plus_periods": len(usable),
        "pre_bankruptcy_period_distribution": {str(k): v for k, v in period_counts.items()},
        "negative_universe": negative_summary,
    }
    (PROCESSED_DIR / "phase3_audit_summary.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    logger.info("Summary report written to %s", PROCESSED_DIR / "phase3_audit_summary.json")


if __name__ == "__main__":
    main()
