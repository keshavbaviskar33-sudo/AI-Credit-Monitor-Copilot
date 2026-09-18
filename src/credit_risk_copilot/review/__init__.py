"""Analyst review and append-only persistence (Phase 13).

Where [D-003] -- "the analyst owns every final judgement" -- stops being a
principle in a README and becomes a schema that refuses to forget.

    store = ReviewStore("data/credit_risk_copilot.db")
    assessment_id = store.record_assessment(assessment)
    draft_id = store.record_draft(assessment_id, synthesis_result)
    store.record_review(AnalystReview(..., decision=ReviewDecision.REJECT,
                                      watch_status=CreditWatchStatus.ESCALATE,
                                      comment="Covenant position is misread."))
    store.history(cik)      # FR-22: every version, with its reviews
    store.watchlist()       # each company's current assessment

Three guarantees, each enforced rather than intended:

- **Nothing is edited.** `BEFORE UPDATE` and `BEFORE DELETE` triggers abort on
  every table, so history is append-only for callers that never read this
  docstring. A correction is a new review pointing at the one it corrects.
- **The draft is immutable and verifiable.** Stored with its Phase 12 verdict
  and a content hash that is checked on every read (FR-19).
- **Judgement is the analyst's.** `AnalystReview` cannot be built without a
  decision and a watch status, neither has a default, and modify/reject
  cannot be built without a comment (FR-18, FR-20).
"""

from credit_risk_copilot.review.models import (
    AnalystReview,
    AssessmentHistory,
    AssessmentState,
    CreditWatchStatus,
    ReviewDecision,
)
from credit_risk_copilot.review.store import (
    SCHEMA_VERSION,
    AppendOnlyViolation,
    ReviewStore,
    SchemaVersionMismatch,
)

__all__ = [
    "SCHEMA_VERSION",
    "AnalystReview",
    "AppendOnlyViolation",
    "AssessmentHistory",
    "AssessmentState",
    "CreditWatchStatus",
    "ReviewDecision",
    "ReviewStore",
    "SchemaVersionMismatch",
]
