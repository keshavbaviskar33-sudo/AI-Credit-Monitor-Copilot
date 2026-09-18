"""The analyst review schema: where D-003 stops being a principle.

"The analyst owns every final judgement" has been this project's first
sentence since Phase 1 and, until this module, was enforced by nothing. A
pipeline that drafts and a human who agrees are not a human-in-the-loop system
unless disagreeing is as easy, as recorded and as permanent as agreeing.

## The rules live in the types, not in a service layer

`AnalystReview` cannot be constructed without the things FR-18 requires: a
`modify` or `reject` without a comment raises at construction, not at save. A
validation that lives in the storage layer protects the database; a validation
that lives in the type protects every code path that will ever build one of
these, including the UI in Phase 14 and whatever comes after.

The same reasoning puts `decision` and `watch_status` in the constructor with
**no defaults**. §7 of `user_workflow.md` asks for "no default review action"
as an anti-automation-bias measure, and a schema that defaults to `APPROVE`
would hand the UI a pre-selected answer no matter what the UI intended.

## Nothing here can be edited

There is no `update` anywhere in this package. A correction is a new review
that points at the one it corrects (`supersedes_review_id`), because an audit
trail that can be rewritten is not one. `store.py` enforces the same rule in
SQL, so the guarantee does not depend on every caller going through this type.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewDecision(str, Enum):
    """What the analyst did with the draft (FR-18).

    Three verbs, deliberately symmetrical. `user_workflow.md` §7 asks that
    rejecting be as easy as approving; the first place that has to be true is
    the data model, where all three are the same shape and none is the
    default.
    """

    #: The draft is an accurate basis for the analyst's own assessment.
    APPROVE = "approve"
    #: Partly right. The analyst's corrected assessment is stored *alongside*
    #: the draft, never over it.
    MODIFY = "modify"
    #: Wrong or unusable. The draft is still stored, with the reason.
    REJECT = "reject"


class CreditWatchStatus(str, Enum):
    """The analyst's standing on the company (FR-20).

    `user_workflow.md` §5 proposed this vocabulary and left it "to be
    confirmed in Phase 13". Confirmed as proposed, for one reason: the four
    terms describe *what the analyst will do next*, not how bad they think the
    company is. A severity vocabulary (`low`/`medium`/`high`) would be a
    composite risk score wearing words, which this project has refused since
    D-010 — and it would invite comparison with the model's ranking, which is
    a different quantity measured a different way.

    Only an analyst action sets this. Nothing in the pipeline writes it, which
    is FR-20 and is why it lives on the review rather than on the assessment.
    """

    #: No action beyond the normal cycle.
    STABLE = "stable"
    #: Look again next filing; nothing actionable yet.
    MONITOR = "monitor"
    #: Formally on the watchlist; reviewed out of cycle.
    WATCHLIST = "watchlist"
    #: Escalated to a risk or portfolio manager.
    ESCALATE = "escalate"


class AnalystReview(BaseModel):
    """One analyst's decision on one draft, at one moment, forever.

    Bound to `draft_id` *and* `assessment_id` rather than to a company: a
    review that referred to "the latest assessment" would mean something
    different the day after it was written, which is exactly what FR-21 and
    FR-22 exist to prevent.
    """

    model_config = ConfigDict(frozen=True)

    review_id: str
    #: The exact draft reviewed -- and through it the model, prompt and data
    #: versions that produced it.
    draft_id: str
    assessment_id: str
    #: Who. A free-text identifier in the MVP; a real deployment would bind
    #: this to an authenticated principal, and the column is here so that
    #: change is a substitution rather than a migration.
    analyst: str = Field(min_length=1)
    decision: ReviewDecision
    watch_status: CreditWatchStatus
    #: Required for `MODIFY` and `REJECT`. Optional for `APPROVE`, because
    #: demanding a justification for agreement is how you train people to
    #: write "ok" -- and a field full of "ok" is worse than an empty one.
    comment: str | None = None
    #: The analyst's own assessment, for `MODIFY`. Stored beside the draft and
    #: never merged into it (FR-19).
    modified_text: str | None = None
    #: Set when this review corrects an earlier one. The earlier review stays
    #: exactly as it was; corrections are new records, never edits.
    supersedes_review_id: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _enforce_fr18(self) -> AnalystReview:
        """FR-18's "modify/reject require a comment", in the type.

        Also refuses `modified_text` on a decision that is not `MODIFY`: an
        approval carrying a rewritten assessment is an ambiguous record, and
        the ambiguity would surface months later in an audit rather than now.
        """
        needs_comment = self.decision in (ReviewDecision.MODIFY, ReviewDecision.REJECT)
        if needs_comment and not (self.comment or "").strip():
            raise ValueError(f"a {self.decision.value} review requires a comment (FR-18)")
        if self.decision is ReviewDecision.MODIFY:
            if not (self.modified_text or "").strip():
                raise ValueError("a modify review requires the analyst's own assessment text")
        elif self.modified_text is not None:
            raise ValueError(
                f"modified_text is only meaningful on a modify review, not on {self.decision.value}"
            )
        return self

    @property
    def is_correction(self) -> bool:
        return self.supersedes_review_id is not None


class AssessmentState(str, Enum):
    """Where an assessment sits in the lifecycle (`user_workflow.md` §6).

    **Derived, never stored.** Four of these five states are the result of an
    action somebody took, and `SUPERSEDED` is the result of an action taken
    about a *different* assessment -- a newer filing arriving. Recording it
    would mean going back and updating a row that was already written, which
    is precisely the operation this package refuses. So the state is computed
    from what is stored: the latest assessment for a company is current, every
    earlier one is superseded, and the rest follows from its reviews.
    """

    #: Recorded, no review yet.
    DRAFT = "draft"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"
    #: A newer assessment exists for this company. Keeps whatever review it
    #: had -- a superseded assessment is not an unreviewed one.
    SUPERSEDED = "superseded"


class AssessmentHistory(BaseModel):
    """One assessment, its draft, its reviews and its derived state.

    The unit FR-22 asks for: a newer filing creates a new assessment version
    and earlier assessments and reviews remain accessible. This is what
    "accessible" returns.
    """

    model_config = ConfigDict(frozen=True)

    assessment_id: str
    cik: int
    company: str
    as_of: str
    period_label: str | None
    state: AssessmentState
    #: True when this is the most recent assessment for the company.
    is_current: bool
    draft_id: str | None
    draft_model: str | None
    #: Whether the Phase 12 validator accepted the draft. Carried here so a
    #: reviewer is never shown a draft without its verdict.
    draft_accepted: bool | None
    #: Every review ever recorded against this assessment, oldest first,
    #: corrections included.
    reviews: tuple[AnalystReview, ...] = ()
    pipeline_versions: dict[str, str] = Field(default_factory=dict)

    @property
    def effective_review(self) -> AnalystReview | None:
        """The review that currently stands.

        The latest review that nothing else corrects. Superseded reviews stay
        in `reviews` and stay readable -- the audit trail is the point -- but
        only one of them is the analyst's current position.
        """
        corrected = {r.supersedes_review_id for r in self.reviews if r.supersedes_review_id}
        standing = [r for r in self.reviews if r.review_id not in corrected]
        return max(standing, key=lambda r: r.recorded_at) if standing else None

    @property
    def watch_status(self) -> CreditWatchStatus | None:
        """The company's credit watch status, or `None` if never reviewed.

        `None` is not a status. An unreviewed company has no analyst standing,
        and defaulting it to `STABLE` would manufacture a judgement nobody
        made -- which is the whole failure mode FR-20 exists to prevent.
        """
        review = self.effective_review
        return review.watch_status if review else None
