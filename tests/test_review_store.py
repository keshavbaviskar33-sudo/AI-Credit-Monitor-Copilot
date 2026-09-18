"""Append-only persistence and the analyst review record (FR-18 to FR-22)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from credit_risk_copilot.review import (
    AnalystReview,
    AppendOnlyViolation,
    AssessmentState,
    CreditWatchStatus,
    ReviewDecision,
    ReviewStore,
    SchemaVersionMismatch,
)
from credit_risk_copilot.synthesis.schema import SynthesisResult, ValidationReport

from .test_synthesis_validator import build_assessment, good_draft


@pytest.fixture
def store():
    with ReviewStore() as open_store:
        yield open_store


def synthesis_result(assessment, *, accepted: bool = True, model: str = "gemini-3.6-flash"):
    return SynthesisResult(
        cik=assessment.cik,
        company=assessment.company,
        as_of=assessment.as_of.isoformat(),
        draft=good_draft(assessment),
        validation=ValidationReport(accepted=accepted),
        model=model,
    )


def review(draft_id, assessment_id, *, decision, **kwargs) -> AnalystReview:
    return AnalystReview(
        review_id=kwargs.pop("review_id", f"RV-{decision.value}-1"),
        draft_id=draft_id,
        assessment_id=assessment_id,
        analyst="k.baviskar",
        decision=decision,
        watch_status=kwargs.pop("watch_status", CreditWatchStatus.MONITOR),
        **kwargs,
    )


# --------------------------------------------------------------------------
# FR-18: the rules are in the type


def test_modify_and_reject_require_a_comment():
    for decision in (ReviewDecision.MODIFY, ReviewDecision.REJECT):
        with pytest.raises(ValueError, match="requires a comment"):
            review("DR-1", "AS-1", decision=decision)


def test_approve_does_not_require_a_comment():
    """Demanding a justification for agreement trains people to write "ok",
    and a field full of "ok" is worse than an empty one."""
    assert review("DR-1", "AS-1", decision=ReviewDecision.APPROVE).comment is None


def test_modify_requires_the_analysts_own_text():
    with pytest.raises(ValueError, match="analyst's own assessment text"):
        review("DR-1", "AS-1", decision=ReviewDecision.MODIFY, comment="partly wrong")


def test_an_approval_may_not_carry_a_rewritten_assessment():
    """An ambiguous record surfaces months later in an audit rather than now."""
    with pytest.raises(ValueError, match="only meaningful on a modify"):
        review("DR-1", "AS-1", decision=ReviewDecision.APPROVE, modified_text="my own version")


def test_there_is_no_default_decision_or_watch_status():
    """`user_workflow.md` §7 asks for no default review action. A schema that
    defaulted to APPROVE would hand the UI a pre-selected answer whatever the
    UI intended."""
    with pytest.raises(ValueError):
        AnalystReview(review_id="RV-1", draft_id="DR-1", assessment_id="AS-1", analyst="a")


# --------------------------------------------------------------------------
# Append-only, enforced by the database


def test_the_database_refuses_an_update(store):
    """The guarantee is tested by attacking the connection directly. A rule
    that can only be exercised through the module that provides it has not
    been tested."""
    store.record_assessment(build_assessment())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.raw().execute("UPDATE assessment SET company = 'OTHER'")


def test_the_database_refuses_a_delete(store):
    store.record_assessment(build_assessment())
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        store.raw().execute("DELETE FROM assessment")


@pytest.mark.parametrize("table", ["assessment", "draft", "review"])
def test_every_table_is_append_only(store, table):
    triggers = {
        row[0]
        for row in store.raw()
        .execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        .fetchall()
    }
    assert f"{table}_is_append_only_update" in triggers
    assert f"{table}_is_append_only_delete" in triggers


def test_a_correction_is_a_new_record_not_an_edit(store):
    assessment = build_assessment()
    assessment_id = store.record_assessment(assessment)
    draft_id = store.record_draft(assessment_id, synthesis_result(assessment))

    first = review(draft_id, assessment_id, decision=ReviewDecision.APPROVE, review_id="RV-1")
    store.record_review(first)
    correction = AnalystReview(
        review_id="RV-2",
        draft_id=draft_id,
        assessment_id=assessment_id,
        analyst="k.baviskar",
        decision=ReviewDecision.REJECT,
        watch_status=CreditWatchStatus.ESCALATE,
        comment="On a second read the covenant position is misread.",
        supersedes_review_id="RV-1",
        recorded_at=first.recorded_at + timedelta(minutes=5),
    )
    store.record_review(correction)

    history = store.latest(assessment.cik)
    # Both survive: the audit trail is the point.
    assert len(history.reviews) == 2
    # Only one stands.
    assert history.effective_review.review_id == "RV-2"
    assert history.state is AssessmentState.REJECTED
    assert history.watch_status is CreditWatchStatus.ESCALATE


# --------------------------------------------------------------------------
# FR-19 / FR-22: immutable drafts and accessible history


def test_a_stored_assessment_round_trips_and_is_hash_checked(store):
    assessment = build_assessment()
    assessment_id = store.record_assessment(assessment)
    assert store.load_assessment(assessment_id) == assessment

    # Corrupt the payload behind the store's back; the hash must catch it.
    store.raw().execute("PRAGMA writable_schema = OFF")
    store.raw().execute("DROP TRIGGER assessment_is_append_only_update")
    store.raw().execute("UPDATE assessment SET payload = payload || ' '")
    with pytest.raises(AppendOnlyViolation, match="does not match its recorded hash"):
        store.load_assessment(assessment_id)


def test_recording_the_same_assessment_twice_is_idempotent(store):
    assessment = build_assessment()
    first = store.record_assessment(assessment)
    second = store.record_assessment(assessment)
    assert first == second
    assert store.counts()["assessment"] == 1


def test_a_rejected_draft_is_still_stored_with_its_verdict(store):
    """Phase 12 returns a rejected draft rather than retrying so the rejection
    rate stays visible; discarding it here would undo that one layer down."""
    assessment = build_assessment()
    assessment_id = store.record_assessment(assessment)
    draft_id = store.record_draft(assessment_id, synthesis_result(assessment, accepted=False))
    assert store.load_draft(draft_id).validation.accepted is False
    assert store.latest(assessment.cik).draft_accepted is False


def test_a_newer_assessment_supersedes_an_older_one_without_editing_it(store):
    """FR-22, and the reason supersession is derived: recording it would mean
    updating a row that was already written."""
    old = build_assessment()
    newer = old.model_copy(update={"as_of": old.as_of.replace(year=old.as_of.year + 1)})

    old_id = store.record_assessment(old)
    old_draft = store.record_draft(old_id, synthesis_result(old))
    store.record_review(
        review(old_draft, old_id, decision=ReviewDecision.APPROVE, review_id="RV-old")
    )
    store.record_assessment(newer)

    history = store.history(old.cik)
    assert len(history) == 2
    assert history[0].is_current and history[0].state is AssessmentState.DRAFT
    # A superseded assessment keeps its review; it is simply no longer latest.
    assert history[1].state is AssessmentState.SUPERSEDED
    assert history[1].effective_review.review_id == "RV-old"


def test_an_unreviewed_company_has_no_watch_status(store):
    """`None` is not a status. Defaulting to STABLE would manufacture a
    judgement nobody made, which is what FR-20 exists to prevent."""
    assessment = build_assessment()
    store.record_assessment(assessment)
    latest = store.latest(assessment.cik)
    assert latest.state is AssessmentState.DRAFT
    assert latest.watch_status is None


def test_a_review_cannot_reference_a_draft_that_does_not_exist(store):
    assessment = build_assessment()
    assessment_id = store.record_assessment(assessment)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_review(
            review("DR-nonexistent", assessment_id, decision=ReviewDecision.APPROVE)
        )


def test_the_watchlist_returns_each_companys_current_assessment(store):
    first = build_assessment()
    second = first.model_copy(update={"cik": 99, "company": "AARDVARK CO"})
    store.record_assessment(first)
    store.record_assessment(second)
    watchlist = store.watchlist()
    assert [h.company for h in watchlist] == ["AARDVARK CO", "TEST CO"]
    assert all(h.is_current for h in watchlist)


def test_a_schema_written_by_another_version_is_refused(tmp_path):
    """An append-only audit store that silently rewrites itself to a new shape
    is a contradiction."""
    path = tmp_path / "audit.db"
    ReviewStore(path).close()
    connection = sqlite3.connect(path)
    connection.execute("UPDATE schema_meta SET version = 99")
    connection.commit()
    connection.close()
    with pytest.raises(SchemaVersionMismatch, match="version 99"):
        ReviewStore(path)


def test_history_survives_reopening_the_database(tmp_path):
    assessment = build_assessment()
    path = tmp_path / "audit.db"
    with ReviewStore(path) as store:
        assessment_id = store.record_assessment(assessment)
        draft_id = store.record_draft(assessment_id, synthesis_result(assessment))
        store.record_review(
            AnalystReview(
                review_id="RV-1",
                draft_id=draft_id,
                assessment_id=assessment_id,
                analyst="k.baviskar",
                decision=ReviewDecision.MODIFY,
                watch_status=CreditWatchStatus.WATCHLIST,
                comment="Leverage conclusion overstated.",
                modified_text="Leverage is deteriorating but from a covenant-compliant base.",
                recorded_at=datetime.now(UTC),
            )
        )
    with ReviewStore(path) as reopened:
        latest = reopened.latest(assessment.cik)
        assert latest.state is AssessmentState.MODIFIED
        assert latest.watch_status is CreditWatchStatus.WATCHLIST
        assert latest.effective_review.modified_text.startswith("Leverage is deteriorating")
        assert reopened.load_draft(latest.draft_id).model == "gemini-3.6-flash"


def test_pipeline_versions_are_recorded_with_the_assessment(store):
    """FR-21: an assessment says which model, prompt and catalog produced it."""
    assessment = build_assessment()
    store.record_assessment(assessment)
    versions = store.latest(assessment.cik).pipeline_versions
    assert versions["model"] == "gradient_boosting_all"
    assert "nlp_catalog" in versions
