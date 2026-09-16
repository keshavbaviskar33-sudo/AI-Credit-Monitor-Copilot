"""QM-01 for Phase 5: does canonicalization resolve the right concept, value
and period -- not just "is this number extractable" (Phase 4's R-19 spike).

Reuses the Phase 4 golden set (`build_golden_set.py`) and its cached inputs
entirely -- no SEC requests, no PDF re-extraction, no re-rendering (§24):

    companyfacts (cached)         -> resolver.resolve_filing -> CanonicalFilingFacts
    reference_values.csv (Phase 4) -> independent ground truth for value/period accuracy
    filing HTML (cached)           -> HtmlDocumentExtractor  -> corroboration + statement mix

Five things are measured, kept separate rather than collapsed into one
"accuracy" (§22):

1. **Value/period accuracy** -- for every golden-set reference row, does the
   canonical concept it maps to carry that same value for that same period?
   Non-circular: `reference_values.csv` was built by filtering raw
   `companyfacts` directly, before any resolver code existed; the resolver
   reaches the same number through its own tag-priority/derivation logic, so
   a mismatch is a real implementation bug, not a rounding artefact.
2. **Completeness per canonical concept** -- FOUND/DERIVED/CONFLICTING/MISSING
   counts across all 12 filings, extending `data_dictionary.md` §6.1's raw
   coverage table to the post-derivation canonical view.
3. **Validation pass rate** -- how often `balance_sheet_equation` and
   `cash_tie_out` hold across the corpus.
4. **Document corroboration rate** -- how many resolved facts are also
   independently visible in the filing's own HTML tables.
5. **Statement-classification mix** -- descriptive only; the golden set has
   no per-table statement label to score against.

    uv run python scripts/evaluate_canonicalization.py
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.extraction import DocumentSource, HtmlDocumentExtractor
from credit_risk_copilot.financials.company import CompanyFinancials
from credit_risk_copilot.financials.concept_map import CONCEPT_DEFINITIONS
from credit_risk_copilot.financials.models import (
    CanonicalFact,
    CanonicalFilingFacts,
    FactStatus,
    Origin,
    PeriodType,
)
from credit_risk_copilot.financials.periods import is_annual_period, period_from_xbrl_fact
from credit_risk_copilot.financials.reconciliation import corroborate_filing
from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.financials.statements import classify_table
from credit_risk_copilot.logging_config import configure_logging

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
GOLDEN_DIR = Path("data/processed/golden_set")
MANIFEST = GOLDEN_DIR / "manifest.json"
REFERENCE_VALUES = GOLDEN_DIR / "reference_values.csv"
OUT_DIR = GOLDEN_DIR

#: Golden-set reference concept -> the canonical concept it grounds-truths.
#: `SalesRevenueNet` is deliberately absent: 0/12 filers tag it
#: (data_dictionary.md §6.1), so the golden set carries no reference rows for
#: it and there is nothing to check it against.
REFERENCE_TO_CANONICAL: dict[str, str] = {
    "Assets": "total_assets",
    "Liabilities": "total_liabilities",
    "StockholdersEquity": "shareholders_equity",
    "AssetsCurrent": "current_assets",
    "LiabilitiesCurrent": "current_liabilities",
    "Revenues": "revenue",
    "NetIncomeLoss": "net_income",
    "OperatingIncomeLoss": "operating_income",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "LongTermDebt": "long_term_debt",
}


def _company_facts(cik: int) -> dict[str, Any]:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    facts: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return facts


def _period_label(end_iso: str) -> str:
    return f"FY{date.fromisoformat(end_iso).year}"


def _resolve_all(manifest: dict[str, Any]) -> dict[str, CanonicalFilingFacts]:
    """One resolved `CanonicalFilingFacts` per accession, keyed for reuse
    across every metric below -- resolving once, not once per metric (§24)."""
    resolved: dict[str, CanonicalFilingFacts] = {}
    for entry in manifest["entries"]:
        facts = _company_facts(entry["cik"])
        resolved[entry["accession"]] = resolve_filing(
            facts,
            cik=entry["cik"],
            company=entry["company"],
            accession=entry["accession"],
            form=entry["form"],
            filed=entry["filed"],
            period_end=entry["period"],
        )
    return resolved


def _value_accuracy(
    reference: pd.DataFrame,
    filings: dict[str, CanonicalFilingFacts],
    period_end_by_accession: dict[str, str],
) -> tuple[pd.DataFrame, int]:
    """Compare every reference row this schema can actually be checked
    against.

    `reference_values.csv` (Phase 4) pulls every value SEC tagged under a
    reference concept for one accession -- it was built before Phase 5's
    annual-only scope (D-007) existed, so it includes "selected quarterly
    financial data" footnote rows the same concept and accession can carry
    (`periods.is_annual_period`'s docstring has the concrete iHeartMedia
    example). Those rows are not wrong, they are simply not what this
    schema resolves, so they are excluded from the comparison rather than
    counted as canonicalization misses -- the excluded count is returned
    so the exclusion is visible, not silently dropped (§22).
    """
    rows: list[dict[str, Any]] = []
    excluded = 0
    for _, row in reference.iterrows():
        canonical = REFERENCE_TO_CANONICAL.get(str(row["concept"]))
        if canonical is None:
            continue
        filing = filings.get(str(row["accn"]))
        if filing is None:
            continue
        period_end = period_end_by_accession.get(str(row["accn"]))
        if period_end is None or not _looks_annual(row, period_end):
            excluded += 1
            continue

        period_label = _period_label(str(row["end"]))
        fact = filing.get(canonical, period_label)
        resolved_value = fact.effective_value if fact else None
        reference_value = float(row["val"])
        match = resolved_value is not None and abs(resolved_value - reference_value) <= max(
            1.0, 0.001 * abs(reference_value)
        )
        rows.append(
            {
                "company": row["company"],
                "accession": row["accn"],
                "xbrl_concept": row["concept"],
                "canonical_concept": canonical,
                "period_label": period_label,
                "reference_value": reference_value,
                "resolved_value": resolved_value,
                "resolved_status": fact.status.value if fact else "not_resolved",
                "value_matches": match,
                "failure_category": None if match else _failure_category(fact, reference_value),
            }
        )
    return pd.DataFrame(rows), excluded


def _failure_category(fact: CanonicalFact | None, reference_value: float) -> str:
    """Why one reference row did not match (§10's breakdown).

    `scope_preference` means the reference value *is* present -- as a
    differently-scoped candidate the resolver deliberately did not prefer
    (e.g. the golden set's `LongTermDebt` reference row where the schema
    prefers `LongTermDebtNoncurrent`). That is a ground-truth/definition
    difference, not a wrong value, and is reported separately so it cannot
    hide inside an accuracy number.
    """
    if fact is None:
        return "not_resolved"
    if fact.status is FactStatus.CONFLICTING:
        return "conflict"
    if fact.status is FactStatus.MISSING:
        return "missing"
    tolerance = max(1.0, 0.001 * abs(reference_value))
    if any(abs(c.value - reference_value) <= tolerance for c in fact.candidates):
        return "scope_preference"
    if (
        fact.effective_value is not None
        and abs(fact.effective_value + reference_value) <= tolerance
    ):
        return "wrong_sign"
    return "wrong_value"


def _looks_annual(row: pd.Series, period_end: str) -> bool:
    anchor = date.fromisoformat(period_end)
    start = row["start"] if isinstance(row["start"], str) and row["start"] else None
    period_type = PeriodType.INSTANT if start is None else PeriodType.DURATION
    period = period_from_xbrl_fact({"start": start, "end": row["end"]}, period_type=period_type)
    return period is not None and is_annual_period(period, anchor.month, anchor.day)


def _completeness(filings: dict[str, CanonicalFilingFacts]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for concept_def in CONCEPT_DEFINITIONS:
        counts: dict[str, int] = dict.fromkeys((s.value for s in FactStatus), 0)
        total = 0
        for filing in filings.values():
            for fact in filing.facts:
                if fact.concept != concept_def.concept:
                    continue
                counts[fact.status.value] += 1
                total += 1
        resolved = counts[FactStatus.FOUND.value] + counts[FactStatus.DERIVED.value]
        rows.append(
            {
                "concept": concept_def.concept,
                "statement": concept_def.statement.value,
                "total_concept_periods": total,
                **counts,
                "completeness": round(resolved / total, 3) if total else None,
            }
        )
    return pd.DataFrame(rows)


def _validation_pass_rate(filings: dict[str, CanonicalFilingFacts]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for filing in filings.values():
        for result in filing.validations:
            rows.append({"rule": result.rule, "passed": result.passed})
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return (
        frame.groupby("rule")["passed"]
        .agg(["sum", "count"])
        .assign(pass_rate=lambda d: (d["sum"] / d["count"]).round(3))
    )


def _circular_balance_sheet_slots(filings: dict[str, CanonicalFilingFacts]) -> int:
    """Filing-periods where all three balance-sheet sides resolved but
    liabilities was derived from the identity itself -- so the equation check
    is deliberately suppressed (§11). Reported so a smaller check count reads
    as "honest", not as "coverage fell"."""
    count = 0
    for filing in filings.values():
        for label in filing.period_labels:
            liabilities = filing.get("total_liabilities", label)
            if (
                liabilities is not None
                and liabilities.origin is Origin.DERIVED
                and "total_equity" in liabilities.derived_from
            ):
                count += 1
    return count


def _corroboration_rate(
    manifest: dict[str, Any], filings: dict[str, CanonicalFilingFacts]
) -> tuple[float, dict[str, CanonicalFilingFacts]]:
    """What fraction of resolved (FOUND/DERIVED) facts are also independently
    visible in the filing's own cached HTML -- reusing that cache, not
    re-fetching or re-rendering anything (§24)."""
    corroborated: dict[str, CanonicalFilingFacts] = {}
    resolved_count = 0
    corroborated_count = 0
    for entry in manifest["entries"]:
        filing = filings[entry["accession"]]
        html_path = Path(entry["html_path"])
        if not html_path.exists():
            corroborated[entry["accession"]] = filing
            continue
        source = DocumentSource(
            uri=entry["primary_document"],
            media_type="text/html",
            cik=entry["cik"],
            accession=entry["accession"],
            form=entry["form"],
            filed=entry["filed"],
        )
        document = HtmlDocumentExtractor().extract(html_path.read_bytes(), source)
        enriched = corroborate_filing(filing, document)
        corroborated[entry["accession"]] = enriched
        for fact in enriched.facts:
            if fact.status not in (FactStatus.FOUND, FactStatus.DERIVED):
                continue
            resolved_count += 1
            if any(p.source_type.value == "html" for p in fact.provenance):
                corroborated_count += 1
    rate = corroborated_count / resolved_count if resolved_count else 0.0
    return rate, corroborated


def _statement_mix(manifest: dict[str, Any]) -> pd.DataFrame:
    """Descriptive only (§22): the golden set has no per-table statement
    label, so this reports the classifier's output distribution, not an
    accuracy against ground truth."""
    counts: dict[str, int] = {}
    for entry in manifest["entries"]:
        html_path = Path(entry["html_path"])
        if not html_path.exists():
            continue
        source = DocumentSource(uri=entry["primary_document"], media_type="text/html")
        document = HtmlDocumentExtractor().extract(html_path.read_bytes(), source)
        for table in document.tables_in(financial_only=True):
            statement = classify_table(table).value
            counts[statement] = counts.get(statement, 0) + 1
    return pd.DataFrame(sorted(counts.items()), columns=["statement", "financial_tables"])


def _restatement_report(filings: dict[str, CanonicalFilingFacts]) -> pd.DataFrame:
    """Not exercised by the golden set (one filing per company), but reported
    so a lone-filing corpus doesn't silently mean "0 restatements found" reads
    as "no restatements exist" -- it means "not tested here"."""
    by_cik: dict[int, list[CanonicalFilingFacts]] = {}
    for filing in filings.values():
        by_cik.setdefault(filing.cik, []).append(filing)
    rows: list[dict[str, Any]] = []
    for cik, company_filings in by_cik.items():
        company = CompanyFinancials(
            cik=cik, company=company_filings[0].company, filings=tuple(company_filings)
        )
        for r in company.restatements():
            rows.append(
                {"company": company.company, "concept": r.concept, "period": r.period_label}
            )
    return pd.DataFrame(rows)


def main() -> None:
    configure_logging()
    if not MANIFEST.exists():
        raise FileNotFoundError(f"{MANIFEST} is missing. Run scripts/build_golden_set.py first.")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reference = pd.read_csv(REFERENCE_VALUES)

    filings = _resolve_all(manifest)
    period_end_by_accession = {e["accession"]: e["period"] for e in manifest["entries"]}

    value_accuracy, excluded_non_annual = _value_accuracy(
        reference, filings, period_end_by_accession
    )
    value_accuracy.to_csv(OUT_DIR / "qm01_value_accuracy.csv", index=False)
    overall_accuracy = value_accuracy["value_matches"].mean() if not value_accuracy.empty else None
    logger.info(
        "Value/period accuracy: %d/%d (%.1f%%) -- %d reference rows excluded as "
        "non-annual (quarterly footnote data under the same tag/accession)",
        value_accuracy["value_matches"].sum(),
        len(value_accuracy),
        100 * overall_accuracy if overall_accuracy is not None else 0.0,
        excluded_non_annual,
    )

    completeness = _completeness(filings)
    completeness.to_csv(OUT_DIR / "qm01_completeness.csv", index=False)
    logger.info("Per-concept completeness:\n%s", completeness.to_string(index=False))

    validation = _validation_pass_rate(filings)
    if not validation.empty:
        validation.to_csv(OUT_DIR / "qm01_validation.csv")
        logger.info("Validation pass rates:\n%s", validation.to_string())

    logger.info(
        "Balance-sheet checks suppressed as circular (liabilities derived from the identity): %d",
        _circular_balance_sheet_slots(filings),
    )
    if not value_accuracy.empty:
        logger.info(
            "Mismatch causes:\n%s",
            value_accuracy["failure_category"].value_counts().to_string(),
        )

    corroboration_rate, filings = _corroboration_rate(manifest, filings)
    logger.info("Document corroboration rate: %.1f%%", 100 * corroboration_rate)

    statement_mix = _statement_mix(manifest)
    statement_mix.to_csv(OUT_DIR / "qm01_statement_mix.csv", index=False)
    logger.info("Statement classification mix:\n%s", statement_mix.to_string(index=False))

    restatements = _restatement_report(filings)
    if not restatements.empty:
        restatements.to_csv(OUT_DIR / "qm01_restatements.csv", index=False)

    summary = {
        "generated": date.today().isoformat(),
        "filings": len(filings),
        "reference_rows_checked": len(value_accuracy),
        "value_period_accuracy": round(float(overall_accuracy), 4)
        if overall_accuracy is not None
        else None,
        "mean_completeness": round(float(completeness["completeness"].dropna().mean()), 4)
        if not completeness["completeness"].dropna().empty
        else None,
        "document_corroboration_rate": round(corroboration_rate, 4),
    }
    (OUT_DIR / "qm01_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("QM-01 summary: %s", summary)


if __name__ == "__main__":
    main()
