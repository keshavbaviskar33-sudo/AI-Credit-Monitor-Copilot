"""R-19 spike: measure PDF table extraction before committing to a library.

R-19 ("library capabilities assumed but not verified, e.g. PDF table
extraction quality") asks for a measurement, not a preference. This compares
the two candidates -- pdfplumber and pymupdf -- over the golden set.

**The metric is reference-value recall, not table count.** Counting tables
rewards a library for finding layout scaffolding. What actually matters is
whether the figures XBRL reports for a filing can be found in the cells that
library extracted. So for every reference value, the script looks for the
number in some extracted cell, trying the scales a filing might present it at
(units, thousands, millions) and the accounting conventions it might use
(comma grouping, parentheses for negatives).

This is a *preview* of QM-01 and deliberately not QM-01 itself: it asks "is
this number present somewhere in the extracted cells", where QM-01 asks "did
we extract this number as the right labelled field". Labelling needs the
canonical schema from Phase 5. Read the figures here as an upper bound.

    uv run python scripts/table_extraction_spike.py
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import pymupdf

from credit_risk_copilot.logging_config import configure_logging

logger = logging.getLogger(__name__)

GOLDEN_DIR = Path("data/processed/golden_set")
MANIFEST = GOLDEN_DIR / "manifest.json"
REFERENCE_VALUES = GOLDEN_DIR / "reference_values.csv"

#: Filings report in units, thousands or millions. Which one is a Phase 5
#: normalisation problem; here every scale counts as a hit so the measurement
#: reflects table extraction rather than unit detection.
SCALES = (1, 1_000, 1_000_000)


def _candidate_strings(value: float) -> set[str]:
    """How a filing might render `value` in a table cell."""
    out: set[str] = set()
    negative = value < 0
    for scale in SCALES:
        scaled = abs(value) / scale
        if scaled < 1 and scaled != 0:
            continue
        if scaled != int(scaled):
            continue
        rendered = f"{int(scaled):,}"
        out.add(rendered)
        if negative:
            out.add(f"({rendered})")
            out.add(f"-{rendered}")
    return out


def _cells_pdfplumber(path: Path) -> tuple[set[str], int, float]:
    started = time.monotonic()
    cells: set[str] = set()
    tables = 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                extracted = page.extract_tables()
            except Exception:  # a bad page must not end the measurement
                continue
            for table in extracted:
                tables += 1
                for row in table:
                    for cell in row:
                        if cell:
                            cells.add(cell.strip().replace("\n", " "))
    return cells, tables, time.monotonic() - started


def _cells_pymupdf(path: Path) -> tuple[set[str], int, float]:
    started = time.monotonic()
    cells: set[str] = set()
    tables = 0
    doc = pymupdf.open(path)
    try:
        for page in doc:
            try:
                finder = page.find_tables()
            except Exception:
                continue
            for table in finder.tables:
                tables += 1
                for row in table.extract():
                    for cell in row:
                        if cell:
                            cells.add(str(cell).strip().replace("\n", " "))
    finally:
        doc.close()
    return cells, tables, time.monotonic() - started


EXTRACTORS = {"pdfplumber": _cells_pdfplumber, "pymupdf": _cells_pymupdf}


def main() -> None:
    configure_logging()
    if not MANIFEST.exists():
        raise FileNotFoundError(f"{MANIFEST} is missing. Run scripts/build_golden_set.py first.")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reference = pd.read_csv(REFERENCE_VALUES)

    results: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        pdf_path = Path(entry["pdf_path"])
        if not pdf_path.exists():
            logger.warning("%s: no PDF at %s; skipping", entry["company"], pdf_path)
            continue

        wanted = reference[reference["accn"] == entry["accession"]]
        targets = [
            (str(row["concept"]), _candidate_strings(float(row["val"])))
            for _, row in wanted.iterrows()
            if str(row["val"]).strip() not in {"", "nan"}
        ]
        targets = [(concept, strings) for concept, strings in targets if strings]

        for library, extract in EXTRACTORS.items():
            cells, tables, seconds = extract(pdf_path)
            hits = sum(1 for _, strings in targets if strings & cells)
            results.append(
                {
                    "company": entry["company"],
                    "accession": entry["accession"],
                    "library": library,
                    "tables": tables,
                    "cells": len(cells),
                    "reference_values": len(targets),
                    "values_found": hits,
                    "recall": round(hits / len(targets), 4) if targets else None,
                    "seconds": round(seconds, 1),
                }
            )
            logger.info(
                "%-28s %-11s tables=%-6d values %d/%d (%.0f%%) in %.0fs",
                entry["company"][:28],
                library,
                tables,
                hits,
                len(targets),
                100 * hits / len(targets) if targets else 0,
                seconds,
            )

    frame = pd.DataFrame(results)
    out_path = GOLDEN_DIR / "table_extraction_spike.csv"
    frame.to_csv(out_path, index=False)

    summary = (
        frame.groupby("library")
        .agg(
            filings=("accession", "nunique"),
            tables=("tables", "sum"),
            reference_values=("reference_values", "sum"),
            values_found=("values_found", "sum"),
            seconds=("seconds", "sum"),
        )
        .assign(recall=lambda d: (d.values_found / d.reference_values).round(4))
    )
    logger.info("R-19 spike summary:\n%s", summary.to_string())
    (GOLDEN_DIR / "table_extraction_spike_summary.json").write_text(
        summary.to_json(orient="index", indent=2), encoding="utf-8"
    )
    logger.info("Per-filing results written to %s", out_path)


if __name__ == "__main__":
    main()
