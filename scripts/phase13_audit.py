"""Phase 13: record the whole corpus into the audit store and verify it holds.

The unit tests prove the store's rules on a handful of rows. This proves them
on everything the pipeline has ever produced, which is a different claim: a
`BEFORE UPDATE` trigger that fires on one table in one test is not evidence
that 202 assessments, their drafts and their reviews survive a write, a
reopen and a read.

Four things are checked, and each of them could fail:

1. **Every assessment round-trips byte-identically.** Recorded, the database
   closed and reopened, then read back and compared against the object that
   went in. FR-19 claims the stored draft is what the analyst reviewed; this
   is that claim, exercised rather than asserted.
2. **The database refuses to be edited.** An `UPDATE` and a `DELETE` are
   attempted against every table, on the real file, after it is full.
3. **Supersession is derived correctly at scale.** Companies with several
   filings should show exactly one current assessment and the rest superseded
   — with their reviews intact, which is the half of FR-22 that is easy to
   lose.
4. **It is fast enough to be a product.** The NFR is "interactive at demo
   scale (tens of companies)"; this reports what the history and watchlist
   queries actually cost on the full corpus.

    uv run python scripts/phase13_audit.py
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import phase11_assess as p11  # noqa: E402

from credit_risk_copilot.assessment import FilingStamp, assemble_assessment  # noqa: E402
from credit_risk_copilot.assessment.models import Assessment  # noqa: E402
from credit_risk_copilot.logging_config import configure_logging  # noqa: E402
from credit_risk_copilot.modeling.dataset import observations_from_rows  # noqa: E402
from credit_risk_copilot.review import (  # noqa: E402
    AnalystReview,
    AssessmentState,
    CreditWatchStatus,
    ReviewDecision,
    ReviewStore,
)
from credit_risk_copilot.synthesis.schema import (  # noqa: E402
    SynthesisResult,
    ValidationReport,
)

logger = logging.getLogger(__name__)
OUT_DIR = Path("data/processed/phase13")
DB_PATH = OUT_DIR / "audit_corpus.db"


def build_assessments() -> list[Assessment]:
    panel = pd.read_csv(p11.PHASE8_DIR / "observations_primary.csv")
    observations = [
        o
        for o in observations_from_rows(panel.replace({np.nan: None}).to_dict("records"))
        if o.outcome.is_usable
    ]
    scored = p11._out_of_fold(observations)
    per_filing = pd.read_csv(p11.PHASE10_DIR / "nlp_per_filing.csv")
    narratives = p11._narrative_reports(
        pd.read_csv(p11.PHASE10_DIR / "nlp_signals.csv"), per_filing
    )
    by_accession = {o.key.source_accession: i for i, o in enumerate(observations)}

    built: list[Assessment] = []
    for accession, narrative in narratives.items():
        index = by_accession.get(accession)
        if index is None or index not in scored:
            continue
        observation = observations[index]
        as_of = date.fromisoformat(str(narrative.filed))
        built.append(
            assemble_assessment(
                cik=observation.key.cik,
                company=observation.key.company,
                as_of=as_of,
                health=p11._health_report(observation),
                health_filing=FilingStamp(accession=accession, form="10-K", filed=as_of),
                explanation=p11._explanation(observation, scored[index]),
                narrative=narrative,
                pipeline_versions={"phase": "13"},
            )
        )
    return built


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # A fresh file each run: the store refuses edits, so the only way to
    # re-measure from empty is to start from empty.
    DB_PATH.unlink(missing_ok=True)

    assessments = build_assessments()
    logger.info("Rebuilt %d assessments", len(assessments))

    write_start = time.perf_counter()
    recorded: dict[str, Assessment] = {}
    with ReviewStore(DB_PATH) as store:
        for index, assessment in enumerate(assessments):
            assessment_id = store.record_assessment(assessment)
            recorded[assessment_id] = assessment
            draft_id = store.record_draft(
                assessment_id,
                SynthesisResult(
                    cik=assessment.cik,
                    company=assessment.company,
                    as_of=assessment.as_of.isoformat(),
                    draft=_placeholder_draft(assessment),
                    validation=ValidationReport(accepted=index % 7 != 0),
                    model="gemini-3.6-flash",
                ),
            )
            # Review every third assessment, cycling the decisions so the
            # derived-state logic is exercised on real data rather than on a
            # fixture that only ever approves.
            if index % 3 == 0:
                decision = [
                    ReviewDecision.APPROVE,
                    ReviewDecision.MODIFY,
                    ReviewDecision.REJECT,
                ][(index // 3) % 3]
                store.record_review(
                    AnalystReview(
                        review_id=f"RV-{assessment_id}",
                        draft_id=draft_id,
                        assessment_id=assessment_id,
                        analyst="corpus.harness",
                        decision=decision,
                        watch_status=CreditWatchStatus.MONITOR,
                        comment=None
                        if decision is ReviewDecision.APPROVE
                        else "Recorded by the Phase 13 corpus harness.",
                        modified_text=None
                        if decision is not ReviewDecision.MODIFY
                        else "Analyst restatement recorded by the harness.",
                    )
                )
        counts = store.counts()
    write_seconds = time.perf_counter() - write_start

    # --- reopen and verify -------------------------------------------------
    mismatches: list[str] = []
    with ReviewStore(DB_PATH) as store:
        read_start = time.perf_counter()
        for assessment_id, original in recorded.items():
            if store.load_assessment(assessment_id) != original:
                mismatches.append(assessment_id)
        read_seconds = time.perf_counter() - read_start

        refusals: dict[str, bool] = {}
        for table in ("assessment", "draft", "review"):
            for operation, sql in (
                ("update", f"UPDATE {table} SET recorded_at = 'tampered'"),
                ("delete", f"DELETE FROM {table}"),
            ):
                try:
                    store.raw().execute(sql)
                    refusals[f"{table}.{operation}"] = False
                except sqlite3.IntegrityError:
                    refusals[f"{table}.{operation}"] = True

        watchlist_start = time.perf_counter()
        watchlist = store.watchlist()
        watchlist_seconds = time.perf_counter() - watchlist_start

        multi = sorted({a.cik for a in assessments})
        history_start = time.perf_counter()
        histories = [store.history(cik) for cik in multi]
        history_seconds = time.perf_counter() - history_start

    superseded_with_reviews = sum(
        1
        for history in histories
        for entry in history
        if entry.state is AssessmentState.SUPERSEDED and entry.reviews
    )
    states: dict[str, int] = {}
    for history in histories:
        for entry in history:
            states[entry.state.value] = states.get(entry.state.value, 0) + 1

    summary: dict[str, Any] = {
        "corpus": {
            "assessments_recorded": counts["assessment"],
            "drafts_recorded": counts["draft"],
            "reviews_recorded": counts["review"],
            "companies": len({a.cik for a in assessments}),
            "companies_with_several_assessments": sum(1 for h in histories if len(h) > 1),
        },
        "integrity": {
            "round_trip_mismatches": len(mismatches),
            "note": (
                "Every assessment was recorded, the database closed and reopened, then read"
                " back and compared against the object that went in. Each read also verifies"
                " the stored payload against its recorded hash."
            ),
            "edit_refused": refusals,
            "all_edits_refused": all(refusals.values()),
        },
        "derived_state": {
            "note": (
                "Supersession is computed, never stored -- recording it would mean updating"
                " a row that was already written. A superseded assessment keeps its review."
            ),
            "states": dict(sorted(states.items())),
            "superseded_entries_retaining_their_review": superseded_with_reviews,
            "current_assessments": len(watchlist),
        },
        "performance": {
            "note": "NFR is interactive at demo scale (tens of companies).",
            "db_bytes": DB_PATH.stat().st_size,
            "write_seconds": round(write_seconds, 3),
            "read_back_all_seconds": round(read_seconds, 3),
            "watchlist_seconds": round(watchlist_seconds, 4),
            "history_all_companies_seconds": round(history_seconds, 3),
        },
    }

    (OUT_DIR / "phase13_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def _placeholder_draft(assessment: Assessment):
    """A minimal draft so the store has something real to persist.

    Deliberately *not* a synthesis: Phase 12 owns generating drafts and this
    script owns persisting them. Generating one here would make a storage
    measurement depend on a model's availability and quota.
    """
    from credit_risk_copilot.synthesis.schema import Claim, ClaimKind, DraftSynthesis

    first = assessment.evidence[0].evidence_id if assessment.evidence else None
    return DraftSynthesis(
        headline=Claim(
            kind=ClaimKind.FINDING,
            text=f"Placeholder draft recorded for {assessment.company}.",
            evidence_ids=(first,) if first else (),
        )
    )


if __name__ == "__main__":
    main()
