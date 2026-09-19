"""Phase 17, debt 1: re-run Phase 7 for real over the Phase 11 corpus.

[combined_assessment.md §8](../docs/combined_assessment.md) limitation 2 calls
this the single highest-value follow-up the project owes itself. Phase 11 did
not re-run the health layer; it rebuilt each report from the Phase 8 *feature
encoding* of one, and that encoding had already collapsed `IMPROVING`, `STABLE`
and `MIXED` into a single not-deteriorating flag. The phase stated the direction
of the resulting bias -- contradictions up, health corroboration down -- but
could not state its size, because nothing had ever measured it.

**The design of the measurement is the point.** Both arms run in one process
over one corpus, and the model layer is fitted **once** and shared. So every
difference reported below is caused by the health reports and by nothing else:
not by a reseeded bootstrap, not by a refitted estimator, not by a different
corpus draw. The reconstruction arm is `phase11_assess._health_report`
unmodified -- the actual code that produced the published numbers, imported
rather than reimplemented, so this cannot accidentally measure a rewrite of it.

**What "for real" costs, and why it is affordable now.** A real report needs the
point-in-time path: re-resolve every filing visible at the cutoff, take
`as_of`, run Phases 6 and 7. That loop is the only place the leakage contract
is enforced, so this script does not copy it -- `modeling.dataset` now exposes
it as `analyse_company_filings`, and the reports here come from the same code
that built the Phase 8 panel. Reports are cached to disk after the first run
because the resolve step is the slow one and the phase re-measures repeatedly.

    uv run python scripts/phase17_health_rerun.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from phase11_assess import (  # noqa: E402
    DIMENSIONS,
    PHASE8_DIR,
    PHASE10_DIR,
    _explanation,
    _health_report,
    _matched_budget,
    _narrative_reports,
    _out_of_fold,
    _rates,
)

from credit_risk_copilot.assessment import (  # noqa: E402
    Assessment,
    ContradictionCode,
    CorroborationCode,
    FilingStamp,
    assemble_assessment,
)
from credit_risk_copilot.health.models import DimensionStatus, FinancialHealthReport  # noqa: E402
from credit_risk_copilot.logging_config import configure_logging  # noqa: E402
from credit_risk_copilot.modeling.contract import Observation  # noqa: E402
from credit_risk_copilot.modeling.dataset import (  # noqa: E402
    analyse_company_filings,
    observations_from_rows,
)
from credit_risk_copilot.sec_edgar import SecEdgarClient  # noqa: E402

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed/phase17")
REPORT_CACHE = OUT_DIR / "real_health_reports.json"


# ---------------------------------------------------------------------------
# The real Phase 7 reports


def _company_facts(cik: int) -> dict[str, Any] | None:
    path = RAW_DIR / "companyfacts" / f"CIK{cik:010d}.json"
    if not path.exists():
        return None
    facts: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return facts


def real_health_reports(wanted: dict[str, int]) -> dict[str, FinancialHealthReport]:
    """A real `FinancialHealthReport` per corpus accession, point-in-time.

    `wanted` maps accession -> cik. Companies are processed once each, because
    `analyse_company_filings` re-resolves a company's whole visible history at
    every cutoff and doing that per accession would repeat the slowest step.
    """
    if REPORT_CACHE.exists():
        cached = json.loads(REPORT_CACHE.read_text(encoding="utf-8"))
        reports = {a: FinancialHealthReport.model_validate(r) for a, r in cached.items()}
        logger.info("Loaded %d cached real health reports", len(reports))
        return reports

    client = SecEdgarClient()
    by_company: dict[int, set[str]] = {}
    for accession, cik in wanted.items():
        by_company.setdefault(cik, set()).add(accession)

    reports: dict[str, FinancialHealthReport] = {}
    for index, (cik, accessions) in enumerate(sorted(by_company.items()), start=1):
        company_facts = _company_facts(cik)
        if company_facts is None:
            logger.warning("CIK%010d: no cached company facts", cik)
            continue
        try:
            filings = client.annual_filings(cik)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CIK%010d: filing index unavailable (%s)", cik, exc)
            continue
        analyses, _ = analyse_company_filings(
            company_facts=company_facts,
            filings=filings,
            cik=cik,
            company=str(company_facts.get("entityName") or f"CIK{cik}"),
        )
        for analysis in analyses:
            if analysis.accession in accessions:
                reports[analysis.accession] = analysis.report
        if index % 25 == 0:
            logger.info("%d/%d companies -> %d reports", index, len(by_company), len(reports))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_CACHE.write_text(
        json.dumps({a: r.model_dump(mode="json") for a, r in reports.items()}, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote %d real health reports to %s", len(reports), REPORT_CACHE)
    return reports


# ---------------------------------------------------------------------------
# One arm of the comparison


def assemble_arm(
    *,
    accessions: list[str],
    observations: list[Observation],
    by_accession: dict[str, int],
    scored: dict[int, dict[str, Any]],
    narratives: dict[str, Any],
    labels: dict[str, int],
    health_for: Callable[[str, Observation], FinancialHealthReport | None],
) -> tuple[pd.DataFrame, dict[str, Assessment]]:
    """Assemble every corpus assessment using one source of health reports."""
    rows: list[dict[str, Any]] = []
    assessments: dict[str, Assessment] = {}

    for accession in accessions:
        observation = observations[by_accession[accession]]
        narrative = narratives[accession]
        health = health_for(accession, observation)
        if health is None:
            continue
        as_of = date.fromisoformat(str(narrative.filed))
        assessment = assemble_assessment(
            cik=observation.key.cik,
            company=observation.key.company,
            as_of=as_of,
            health=health,
            health_filing=FilingStamp(accession=accession, form="10-K", filed=as_of),
            explanation=_explanation(observation, scored[by_accession[accession]]),
            narrative=narrative,
            pipeline_versions={"phase": "17"},
        )
        assessments[accession] = assessment

        contradiction_codes = {f.code for f in assessment.contradictions}
        corroboration_codes = {f.code for f in assessment.corroborations}
        row: dict[str, Any] = {
            "accession": accession,
            "cik": observation.key.cik,
            "company": observation.key.company,
            "label": labels[accession],
            "percentile": scored[by_accession[accession]]["percentile"],
            "n_contradictions": len(assessment.contradictions),
            "n_corroborations": len(assessment.corroborations),
        }
        for code in ContradictionCode:
            row[f"contra_{code.value}"] = code in contradiction_codes
        for code in CorroborationCode:
            row[f"corrob_{code.value}"] = code in corroboration_codes
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame["layer_model"] = frame["percentile"] >= 90.0
    frame["layer_narrative"] = [
        any(
            item.detail.get("assertion") == "asserted" and item.detail.get("specificity") == "high"
            for item in assessments[a].evidence
        )
        for a in frame["accession"]
    ]
    frame["layer_health"] = [
        any(
            item.kind.value == "dimension_status" and item.detail.get("status") == "deteriorating"
            for item in assessments[a].evidence
        )
        for a in frame["accession"]
    ]
    return frame, assessments


def measure(frame: pd.DataFrame) -> dict[str, Any]:
    """The Phase 11 measurement, unchanged, over one arm's findings."""
    return {
        "single_layers": {
            name: {**_rates(frame, name), **(_matched_budget(frame, name) or {})}
            for name in ("layer_model", "layer_narrative", "layer_health")
        },
        "contradictions": {
            code.value: _rates(frame, f"contra_{code.value}") for code in ContradictionCode
        },
        "corroborations": {
            code.value: {
                **_rates(frame, f"corrob_{code.value}"),
                **(_matched_budget(frame, f"corrob_{code.value}") or {}),
            }
            for code in CorroborationCode
        },
    }


# ---------------------------------------------------------------------------
# What the reconstruction got wrong


def status_confusion(
    accessions: list[str],
    reconstructed: dict[str, FinancialHealthReport],
    real: dict[str, FinancialHealthReport],
) -> dict[str, Any]:
    """Per-dimension: what the encoding said, against what Phase 7 really says.

    This is the direct measurement the reconstruction could not make about
    itself. `MIXED` and `IMPROVING` are the two statuses the encoding could not
    represent, so the cells that matter are the ones where a real `MIXED` was
    read as `STABLE` -- each of those is one dimension that should have counted
    as elevated and did not.
    """
    pairs: Counter[tuple[str, str]] = Counter()
    per_dimension: dict[str, Counter[tuple[str, str]]] = {d: Counter() for d in DIMENSIONS}
    agree = 0
    total = 0
    for accession in accessions:
        left, right = reconstructed.get(accession), real.get(accession)
        if left is None or right is None:
            continue
        for dimension in DIMENSIONS:
            a = left.dimensions.get(dimension)
            b = right.dimensions.get(dimension)
            if a is None or b is None:
                continue
            cell = (a.status.value, b.status.value)
            pairs[cell] += 1
            per_dimension[dimension][cell] += 1
            total += 1
            agree += int(a.status is b.status)

    real_counts: Counter[str] = Counter()
    for accession in accessions:
        report = real.get(accession)
        if report is None:
            continue
        for dimension in DIMENSIONS:
            health = report.dimensions.get(dimension)
            if health is not None:
                real_counts[health.status.value] += 1

    return {
        "dimension_slots": total,
        "agreement": round(agree / total, 4) if total else None,
        "reconstructed_to_real": {f"{a} -> {b}": n for (a, b), n in sorted(pairs.items())},
        "real_status_distribution": dict(sorted(real_counts.items())),
        "mixed_read_as_stable": pairs[(DimensionStatus.STABLE.value, DimensionStatus.MIXED.value)],
        "improving_read_as_stable": pairs[
            (DimensionStatus.STABLE.value, DimensionStatus.IMPROVING.value)
        ],
        "per_dimension": {
            dimension: {f"{a} -> {b}": n for (a, b), n in sorted(counter.items())}
            for dimension, counter in per_dimension.items()
        },
    }


def _delta(new: dict[str, Any], old: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        left, right = new.get(key), old.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            out[key] = {"real": left, "reconstructed": right, "delta": round(left - right, 4)}
    return out


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(PHASE8_DIR / "observations_primary.csv")
    observations = [
        o
        for o in observations_from_rows(panel.replace({np.nan: None}).to_dict("records"))
        if o.outcome.is_usable
    ]
    by_accession = {o.key.source_accession: i for i, o in enumerate(observations)}

    per_filing = pd.read_csv(PHASE10_DIR / "nlp_per_filing.csv")
    signal_dump = pd.read_csv(PHASE10_DIR / "nlp_signals.csv")
    narratives = _narrative_reports(signal_dump, per_filing)
    labels = {str(r["accession"]): int(r["label"]) for r in per_filing.to_dict("records")}

    # The model layer is fitted once and shared by both arms. That is what
    # makes every delta below attributable to the health reports alone.
    scored = _out_of_fold(observations)
    corpus = [
        a for a in narratives if a in by_accession and by_accession[a] in scored and a in labels
    ]
    logger.info("Corpus: %d filings", len(corpus))

    wanted = {a: observations[by_accession[a]].key.cik for a in corpus}
    real = real_health_reports(wanted)
    missing = [a for a in corpus if a not in real]
    logger.info("Real reports for %d/%d corpus filings", len(real), len(corpus))

    # Both arms are measured on the filings where *both* exist, so the
    # comparison is never between two different corpora.
    shared = [a for a in corpus if a in real]
    reconstructed = {a: _health_report(observations[by_accession[a]]) for a in shared}

    arms: dict[str, Any] = {}
    frames: dict[str, pd.DataFrame] = {}
    for name, source in (
        ("reconstructed", lambda a, _o: reconstructed.get(a)),
        ("real", lambda a, _o: real.get(a)),
    ):
        frame, _assessments = assemble_arm(
            accessions=shared,
            observations=observations,
            by_accession=by_accession,
            scored=scored,
            narratives=narratives,
            labels=labels,
            health_for=source,
        )
        frames[name] = frame
        arms[name] = measure(frame)
        frame.to_csv(OUT_DIR / f"findings_{name}.csv", index=False)
        logger.info("[%s] assembled %d assessments", name, len(frame))

    comparison_keys = (
        "rate_event",
        "rate_comparison",
        "lift",
        "n_event",
        "n_comparison",
        "k",
        "combination_precision",
        "precision_delta",
    )
    summary: dict[str, Any] = {
        "what_this_measures": (
            "Phase 11 rebuilt each health report from the Phase 8 feature encoding rather than"
            " re-running Phase 7 (combined_assessment.md, limitation 2). Both arms here share one"
            " corpus and one fitted model, so every delta is caused by the health reports alone."
        ),
        "corpus": {
            "filings": len(shared),
            "events": int(frames["real"]["label"].sum()),
            "corpus_filings_without_a_real_report": len(missing),
            "missing_accessions": missing[:20],
        },
        "reconstruction_fidelity": status_confusion(shared, reconstructed, real),
        "deltas": {
            "single_layers": {
                name: _delta(
                    arms["real"]["single_layers"][name],
                    arms["reconstructed"]["single_layers"][name],
                    comparison_keys,
                )
                for name in ("layer_model", "layer_narrative", "layer_health")
            },
            "contradictions": {
                code.value: _delta(
                    arms["real"]["contradictions"][code.value],
                    arms["reconstructed"]["contradictions"][code.value],
                    comparison_keys,
                )
                for code in ContradictionCode
            },
            "corroborations": {
                code.value: _delta(
                    arms["real"]["corroborations"][code.value],
                    arms["reconstructed"]["corroborations"][code.value],
                    comparison_keys,
                )
                for code in CorroborationCode
            },
        },
        "arms": arms,
    }

    (OUT_DIR / "phase17_health_rerun.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    logger.info("Wrote %s", OUT_DIR / "phase17_health_rerun.json")
    print(json.dumps(summary["reconstruction_fidelity"], indent=2))
    print(json.dumps(summary["deltas"], indent=2))


if __name__ == "__main__":
    main()
