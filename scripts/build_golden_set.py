"""Build the Phase 4 golden evaluation set: 10-K documents + XBRL reference values.

QM-01 measures field-level extraction accuracy against XBRL. That needs a fixed
corpus of filings where the document and a trustworthy reference for the same
numbers both exist. This script assembles one:

    filing HTML (from EDGAR)  ->  extracted
    same HTML rendered to PDF ->  extracted     (A-07 / D-014)
    companyfacts filtered by that filing's accession -> reference values

Filtering `companyfacts` on `accn` is what makes the reference point-in-time
honest (D-008): it returns the figures **as reported in that filing**,
including its comparatives, not values a later filing restated.

Phase 4 stops here. Comparing extracted line items against these reference
values -- the QM-01 number itself -- needs the canonical schema and alias
mapping from Phase 5.

Everything is cached under data/raw/, so reruns cost no SEC requests. Usage:

    uv run python scripts/build_golden_set.py
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.extraction import DocumentSource, HtmlDocumentExtractor
from credit_risk_copilot.extraction.models import ExtractedDocument
from credit_risk_copilot.extraction.pdf_extractor import PdfDocumentExtractor
from credit_risk_copilot.extraction.render import html_to_pdf, prepare_for_render
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.sec_edgar import FilingRef, SecEdgarClient

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
GOLDEN_DIR = Path("data/processed/golden_set")
LINKAGE_AUDIT = Path("data/processed/brd_sec_linkage_audit.csv")

#: Raw us-gaap concepts the reference covers (data_dictionary.md §6). The
#: concept-to-ratio mapping, and companies that tag the same idea differently,
#: are Phase 5/6 problems -- this is only the ground truth to measure against.
REFERENCE_CONCEPTS = (
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "AssetsCurrent",
    "LiabilitiesCurrent",
    "Revenues",
    "SalesRevenueNet",
    "NetIncomeLoss",
    "OperatingIncomeLoss",
    "CashAndCashEquivalentsAtCarryingValue",
    "LongTermDebt",
)

#: Companies that later filed for bankruptcy, drawn from the Phase 3 linkage
#: audit (data/processed/brd_sec_linkage_audit.csv). Chosen by hand rather than
#: by "top N", which would return almost only oil and gas: the corpus needs
#: industry spread to be a fair test of extraction. For each, the script takes
#: the last 10-K filed *before* the bankruptcy petition -- the filing an analyst
#: would actually have been monitoring.
DISTRESSED_CIKS = (
    895126,  # Chesapeake Energy - oil and gas
    1400891,  # iHeartMedia - media
    20520,  # Frontier Communications - telecom
    1064728,  # Peabody Energy - coal mining
    939930,  # Pyxus International - agriculture
    1349436,  # SandRidge Energy - oil and gas
)

#: Large non-financial filers with no bankruptcy event, for contrast. Financial
#: companies are deliberately absent (D-006); the exact SIC exclusion ranges are
#: Phase 5/7 work, so the manifest records each company's SIC rather than
#: pre-empting that rule here.
HEALTHY_CIKS = (
    320193,  # Apple - technology
    1318605,  # Tesla - automotive
    104169,  # Walmart - retail
    78003,  # Pfizer - pharmaceuticals
    21344,  # Coca-Cola - beverages
    1090727,  # UPS - logistics
)


@dataclass(frozen=True)
class GoldenEntry:
    cik: int
    company: str
    sic: str
    sic_description: str
    cohort: str
    bankruptcy_date: str | None
    filing: FilingRef
    html_path: str
    pdf_path: str
    html_stats: dict[str, Any]
    pdf_stats: dict[str, Any]


def _bankruptcy_dates() -> dict[int, date]:
    """Bankruptcy petition date per CIK, from the Phase 3 linkage audit."""
    if not LINKAGE_AUDIT.exists():
        raise FileNotFoundError(
            f"{LINKAGE_AUDIT} is missing. Run scripts/phase3_data_audit.py first."
        )
    audit = pd.read_csv(LINKAGE_AUDIT)
    dates: dict[int, date] = {}
    for _, row in audit.iterrows():
        cik = int(row["CikBefore"])
        filed = datetime.strptime(str(row["DateFiled"]), "%m/%d/%Y").date()
        # A company can appear more than once; the earliest petition is the
        # one that bounds "filings an analyst had before the event".
        if cik not in dates or filed < dates[cik]:
            dates[cik] = filed
    return dates


def _choose_filing(filings: list[FilingRef], before: date | None) -> FilingRef | None:
    """The most recent 10-K, or the last one filed before `before`."""
    candidates = [f for f in filings if f.form == "10-K"]
    if before is not None:
        candidates = [
            f for f in candidates if datetime.strptime(f.filed, "%Y-%m-%d").date() < before
        ]
    return candidates[-1] if candidates else None


def _reference_rows(facts: Any, accession: str) -> list[dict[str, Any]]:
    """Every reference-concept fact reported by one filing.

    Includes comparative periods, because that is what the filing itself
    presented -- and what a document extractor will find in the same table.
    """
    rows: list[dict[str, Any]] = []
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in REFERENCE_CONCEPTS:
        for unit, entries in usgaap.get(concept, {}).get("units", {}).items():
            for entry in entries:
                if entry.get("accn") != accession:
                    continue
                rows.append(
                    {
                        "concept": concept,
                        "unit": unit,
                        "start": entry.get("start", ""),
                        "end": entry.get("end", ""),
                        "fy": entry.get("fy", ""),
                        "fp": entry.get("fp", ""),
                        "form": entry.get("form", ""),
                        "filed": entry.get("filed", ""),
                        "accn": entry.get("accn", ""),
                        "val": entry.get("val", ""),
                    }
                )
    return rows


def _stats(doc: ExtractedDocument) -> dict[str, Any]:
    return {
        "chars": len(doc.text),
        "blocks": len(doc.blocks),
        "tables": len(doc.tables),
        "table_rows": sum(t.n_rows for t in doc.tables),
        "sections": [s.section_id for s in doc.sections],
        "errors": [e.code for e in doc.errors],
    }


def _process(
    cik: int, cohort: str, client: SecEdgarClient, bankruptcy: date | None
) -> tuple[GoldenEntry, list[dict[str, Any]]] | None:
    submissions = client.submissions(cik)
    company = submissions.get("name", f"CIK{cik}")

    filing = _choose_filing(client.annual_filings(cik), bankruptcy)
    if filing is None:
        logger.warning("%s (CIK %d): no usable 10-K found; skipping", company, cik)
        return None

    logger.info("%s (CIK %d): using %s filed %s", company, cik, filing.accession, filing.filed)
    content = client.filing_document(filing)

    source = DocumentSource(
        uri=filing.primary_document,
        media_type="text/html",
        cik=cik,
        accession=filing.accession,
        form=filing.form,
        filed=filing.filed,
    )
    html_doc = HtmlDocumentExtractor().extract(content, source)

    pdf_path = GOLDEN_DIR / "pdf" / f"{filing.accession_compact}.pdf"
    if not pdf_path.exists():
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(html_to_pdf(prepare_for_render(content)))
    pdf_doc = PdfDocumentExtractor().extract(
        pdf_path.read_bytes(),
        source.model_copy(update={"media_type": "application/pdf"}),
    )

    rows = _reference_rows(client.company_facts(cik), filing.accession)
    if not rows:
        logger.warning(
            "%s: no XBRL facts tagged to accession %s -- no reference values",
            company,
            filing.accession,
        )

    entry = GoldenEntry(
        cik=cik,
        company=company,
        sic=str(submissions.get("sic", "")),
        sic_description=str(submissions.get("sicDescription", "")),
        cohort=cohort,
        bankruptcy_date=bankruptcy.isoformat() if bankruptcy else None,
        filing=filing,
        html_path=str(RAW_DIR / "filings" / filing.accession_compact / filing.primary_document),
        pdf_path=str(pdf_path),
        html_stats=_stats(html_doc),
        pdf_stats=_stats(pdf_doc),
    )
    for row in rows:
        row["cik"] = cik
        row["company"] = company
    return entry, rows


def main() -> None:
    configure_logging()
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    client = SecEdgarClient(cache_dir=RAW_DIR)
    bankruptcies = _bankruptcy_dates()

    entries: list[GoldenEntry] = []
    all_rows: list[dict[str, Any]] = []
    cohorts = [(cik, "distressed") for cik in DISTRESSED_CIKS]
    cohorts += [(cik, "healthy") for cik in HEALTHY_CIKS]

    for cik, cohort in cohorts:
        bankruptcy = bankruptcies.get(cik) if cohort == "distressed" else None
        if cohort == "distressed" and bankruptcy is None:
            logger.warning("CIK %d is not in the linkage audit; skipping", cik)
            continue
        try:
            result = _process(cik, cohort, client, bankruptcy)
        except Exception:
            logger.exception("CIK %d failed; continuing with the rest", cik)
            continue
        if result is None:
            continue
        entry, rows = result
        entries.append(entry)
        all_rows.extend(rows)

    manifest = {
        "generated": date.today().isoformat(),
        "filings": len(entries),
        "reference_concepts": list(REFERENCE_CONCEPTS),
        "entries": [
            {
                "cik": e.cik,
                "company": e.company,
                "sic": e.sic,
                "sic_description": e.sic_description,
                "cohort": e.cohort,
                "bankruptcy_date": e.bankruptcy_date,
                "accession": e.filing.accession,
                "form": e.filing.form,
                "filed": e.filing.filed,
                "period": e.filing.period,
                "primary_document": e.filing.primary_document,
                "html_path": e.html_path,
                "pdf_path": e.pdf_path,
                "html": e.html_stats,
                "pdf": e.pdf_stats,
            }
            for e in entries
        ],
    }
    manifest_path = GOLDEN_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    reference_path = GOLDEN_DIR / "reference_values.csv"
    fieldnames = [
        "cik",
        "company",
        "accn",
        "concept",
        "unit",
        "start",
        "end",
        "fy",
        "fp",
        "form",
        "filed",
        "val",
    ]
    with reference_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info("Golden set: %d filings, %d reference values", len(entries), len(all_rows))
    logger.info("Manifest: %s", manifest_path)
    logger.info("Reference values: %s", reference_path)

    missing = [e.company for e in entries if e.html_stats["errors"]]
    if missing:
        logger.info("Filings with extraction errors: %s", ", ".join(missing))


if __name__ == "__main__":
    main()
