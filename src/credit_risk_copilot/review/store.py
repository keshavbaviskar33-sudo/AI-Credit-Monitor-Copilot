"""Append-only SQLite persistence for assessments, drafts and reviews.

Core principle 6 of this project is "history is append-only". Until now that
was a sentence in a README. Here it is a property of the database: every table
carries `BEFORE UPDATE` and `BEFORE DELETE` triggers that `RAISE(ABORT)`, so
an `UPDATE` does not quietly succeed for a caller who bypassed this module,
forgot the convention, or opened the file in a SQLite browser.

That distinction is the whole design. A store that is append-only *by
convention* is append-only until the first hurried afternoon. A store whose
`UPDATE` raises is append-only in a way an auditor can verify without reading
any Python.

## Why stdlib `sqlite3` and not SQLAlchemy

`pyproject.toml` has carried a `db` extra with SQLAlchemy since Phase 2, added
before any of this existed. It is not used here, for two reasons that only
became visible once the schema did.

The schema is five tables with no polymorphism, no lazy loading and no
relationship graph worth mapping -- the payloads are JSON documents produced
by pydantic models that already own their validation. An ORM over that adds a
layer to read through and removes nothing.

More decisively: `sqlite3` is in the standard library, so the persistence
tests run in every environment with no optional extra installed. Phase 12
established that the test suite must not depend on an optional dependency;
the argument applies at least as strongly to the layer that stores the audit
trail.

## What is stored, and what is derived

Stored: assessments, drafts, reviews -- the things somebody or something
*did*. Derived: supersession and lifecycle state, because those are
consequences of a later event and recording them would mean updating a row
that was already written.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from hashlib import blake2s
from pathlib import Path

from credit_risk_copilot.assessment.models import Assessment
from credit_risk_copilot.review.models import (
    AnalystReview,
    AssessmentHistory,
    AssessmentState,
    ReviewDecision,
)
from credit_risk_copilot.synthesis.prompt import request_fingerprint
from credit_risk_copilot.synthesis.schema import SynthesisResult

#: Bumped whenever the schema changes in a way a stored database would notice.
#: Checked on open rather than migrated: an append-only audit store that
#: silently rewrites itself to a new shape is a contradiction, so a mismatch
#: is reported and the operator decides.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version     INTEGER NOT NULL,
    created_at  TEXT    NOT NULL
);

-- One row per assessment the pipeline produced. `assessment_id` is content
-- derived, so recording the same assessment twice is idempotent rather than a
-- duplicate.
CREATE TABLE IF NOT EXISTS assessment (
    assessment_id       TEXT PRIMARY KEY,
    cik                 INTEGER NOT NULL,
    company             TEXT    NOT NULL,
    as_of               TEXT    NOT NULL,
    period_label        TEXT,
    prompt_fingerprint  TEXT    NOT NULL,
    pipeline_versions   TEXT    NOT NULL,
    payload             TEXT    NOT NULL,
    payload_hash        TEXT    NOT NULL,
    recorded_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS assessment_by_company ON assessment (cik, as_of);

-- The AI draft, exactly as generated (FR-19). Regenerating produces a new
-- row; nothing ever edits one.
CREATE TABLE IF NOT EXISTS draft (
    draft_id        TEXT PRIMARY KEY,
    assessment_id   TEXT    NOT NULL REFERENCES assessment (assessment_id),
    model           TEXT    NOT NULL,
    accepted        INTEGER NOT NULL,
    payload         TEXT    NOT NULL,
    payload_hash    TEXT    NOT NULL,
    recorded_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS draft_by_assessment ON draft (assessment_id);

-- Analyst decisions. A correction is a new row pointing at the one it
-- corrects; the corrected row is untouched.
CREATE TABLE IF NOT EXISTS review (
    review_id               TEXT PRIMARY KEY,
    draft_id                TEXT NOT NULL REFERENCES draft (draft_id),
    assessment_id           TEXT NOT NULL REFERENCES assessment (assessment_id),
    analyst                 TEXT NOT NULL,
    decision                TEXT NOT NULL,
    watch_status            TEXT NOT NULL,
    comment                 TEXT,
    modified_text           TEXT,
    supersedes_review_id    TEXT REFERENCES review (review_id),
    recorded_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS review_by_assessment ON review (assessment_id);
"""

#: The triggers are the guarantee. Without them "append-only" is a habit.
_TRIGGERS = "".join(
    f"""
CREATE TRIGGER IF NOT EXISTS {table}_is_append_only_update
BEFORE UPDATE ON {table}
BEGIN
    SELECT RAISE(ABORT, '{table} is append-only: record a new row instead of updating');
END;

CREATE TRIGGER IF NOT EXISTS {table}_is_append_only_delete
BEFORE DELETE ON {table}
BEGIN
    SELECT RAISE(ABORT, '{table} is append-only: history is never deleted');
END;
"""
    for table in ("assessment", "draft", "review")
)


class AppendOnlyViolation(RuntimeError):
    """Something tried to change or remove recorded history."""


class SchemaVersionMismatch(RuntimeError):
    """The database on disk was written by a different schema version."""


def _hash(payload: str) -> str:
    return blake2s(payload.encode("utf-8"), digest_size=8).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReviewStore:
    """The audit trail. Opens or creates a SQLite database and never edits it.

    `path` may be `":memory:"`, which the tests use. Foreign keys are enabled
    explicitly because SQLite leaves them off by default, and a reference from
    a review to a draft that does not exist would make the trail unverifiable
    in exactly the way the trail exists to prevent.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialise()

    def _initialise(self) -> None:
        with self._transaction() as connection:
            connection.executescript(_SCHEMA)
            connection.executescript(_TRIGGERS)
            row = connection.execute("SELECT version FROM schema_meta").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta (version, created_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _now()),
                )
            elif row["version"] != SCHEMA_VERSION:
                raise SchemaVersionMismatch(
                    f"{self.path} was written by schema version {row['version']};"
                    f" this build expects {SCHEMA_VERSION}. An append-only store is not"
                    " migrated in place -- export, convert and re-record."
                )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection:
                yield self._connection
        except sqlite3.IntegrityError as error:
            # The triggers raise this. Translated so callers branch on an
            # exception that names the invariant rather than on SQLite's text.
            if "append-only" in str(error):
                raise AppendOnlyViolation(str(error)) from error
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> ReviewStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- recording ---------------------------------------------------------

    def record_assessment(self, assessment: Assessment) -> str:
        """Store an assessment and return its id.

        Idempotent by construction: the id is derived from the company, the
        as-of date and the prompt fingerprint, so re-recording an unchanged
        assessment returns the same id and writes nothing. Re-running the
        pipeline after a data fix changes the fingerprint and therefore
        produces a *new* assessment, which is what FR-22 asks for.
        """
        payload = assessment.model_dump_json()
        fingerprint = request_fingerprint(assessment)
        assessment_id = (
            f"AS-{_hash(f'{assessment.cik}|{assessment.as_of.isoformat()}|{fingerprint}')}"
        )
        with self._transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO assessment
                   (assessment_id, cik, company, as_of, period_label, prompt_fingerprint,
                    pipeline_versions, payload, payload_hash, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    assessment.cik,
                    assessment.company,
                    assessment.as_of.isoformat(),
                    assessment.period_label,
                    fingerprint,
                    json.dumps(assessment.pipeline_versions, sort_keys=True),
                    payload,
                    _hash(payload),
                    _now(),
                ),
            )
        return assessment_id

    def record_draft(self, assessment_id: str, result: SynthesisResult) -> str:
        """Store a synthesis result against an assessment (FR-19).

        The draft is stored **with its verdict**, accepted or not. A rejected
        draft is part of the record: Phase 12 returns it rather than retrying
        precisely so the rejection rate stays visible, and discarding it here
        would undo that one layer down.
        """
        payload = result.model_dump_json()
        draft_id = f"DR-{_hash(f'{assessment_id}|{result.model}|{payload}')}"
        with self._transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO draft
                   (draft_id, assessment_id, model, accepted, payload, payload_hash, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft_id,
                    assessment_id,
                    result.model,
                    int(result.validation.accepted),
                    payload,
                    _hash(payload),
                    _now(),
                ),
            )
        return draft_id

    def record_review(self, review: AnalystReview) -> str:
        """Store an analyst decision.

        FR-18's requirements are already enforced by `AnalystReview` itself,
        so nothing is re-checked here -- a second copy of a rule is a second
        place for it to drift. What this method adds is referential integrity:
        the draft and assessment must exist, and a correction must point at a
        review that does.
        """
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO review
                   (review_id, draft_id, assessment_id, analyst, decision, watch_status,
                    comment, modified_text, supersedes_review_id, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review.review_id,
                    review.draft_id,
                    review.assessment_id,
                    review.analyst,
                    review.decision.value,
                    review.watch_status.value,
                    review.comment,
                    review.modified_text,
                    review.supersedes_review_id,
                    review.recorded_at.isoformat(),
                ),
            )
        return review.review_id

    # -- reading -----------------------------------------------------------

    def _reviews_for(self, assessment_id: str) -> tuple[AnalystReview, ...]:
        rows = self._connection.execute(
            "SELECT * FROM review WHERE assessment_id = ? ORDER BY recorded_at, review_id",
            (assessment_id,),
        ).fetchall()
        return tuple(
            AnalystReview(
                review_id=row["review_id"],
                draft_id=row["draft_id"],
                assessment_id=row["assessment_id"],
                analyst=row["analyst"],
                decision=ReviewDecision(row["decision"]),
                watch_status=row["watch_status"],
                comment=row["comment"],
                modified_text=row["modified_text"],
                supersedes_review_id=row["supersedes_review_id"],
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
            )
            for row in rows
        )

    def _state(self, reviews: tuple[AnalystReview, ...], is_current: bool) -> AssessmentState:
        if not is_current:
            # A superseded assessment keeps its review; it is simply no longer
            # the latest (`user_workflow.md` §6).
            return AssessmentState.SUPERSEDED
        corrected = {r.supersedes_review_id for r in reviews if r.supersedes_review_id}
        standing = [r for r in reviews if r.review_id not in corrected]
        if not standing:
            return AssessmentState.DRAFT
        return {
            ReviewDecision.APPROVE: AssessmentState.APPROVED,
            ReviewDecision.MODIFY: AssessmentState.MODIFIED,
            ReviewDecision.REJECT: AssessmentState.REJECTED,
        }[max(standing, key=lambda r: r.recorded_at).decision]

    def history(self, cik: int) -> tuple[AssessmentHistory, ...]:
        """Every assessment for a company, newest first (FR-22).

        Supersession is computed here rather than stored: the newest
        assessment is current and every earlier one is superseded, which is a
        fact about the set and not about any row in it.
        """
        rows = self._connection.execute(
            """SELECT a.*, d.draft_id, d.model AS draft_model, d.accepted AS draft_accepted
               FROM assessment a
               LEFT JOIN draft d ON d.assessment_id = a.assessment_id
               WHERE a.cik = ?
               ORDER BY a.as_of DESC, a.recorded_at DESC""",
            (cik,),
        ).fetchall()

        out: list[AssessmentHistory] = []
        for index, row in enumerate(rows):
            reviews = self._reviews_for(row["assessment_id"])
            is_current = index == 0
            out.append(
                AssessmentHistory(
                    assessment_id=row["assessment_id"],
                    cik=row["cik"],
                    company=row["company"],
                    as_of=row["as_of"],
                    period_label=row["period_label"],
                    state=self._state(reviews, is_current),
                    is_current=is_current,
                    draft_id=row["draft_id"],
                    draft_model=row["draft_model"],
                    draft_accepted=(
                        None if row["draft_accepted"] is None else bool(row["draft_accepted"])
                    ),
                    reviews=reviews,
                    pipeline_versions=json.loads(row["pipeline_versions"]),
                )
            )
        return tuple(out)

    def latest(self, cik: int) -> AssessmentHistory | None:
        history = self.history(cik)
        return history[0] if history else None

    def load_assessment(self, assessment_id: str) -> Assessment:
        """Read back a stored assessment, verifying it has not changed.

        The hash check is not defensive programming about SQLite. It is the
        claim FR-19 makes -- that what an analyst reviewed is what is stored
        -- turned into something a reader can confirm rather than trust.
        """
        row = self._connection.execute(
            "SELECT payload, payload_hash FROM assessment WHERE assessment_id = ?",
            (assessment_id,),
        ).fetchone()
        if row is None:
            raise KeyError(assessment_id)
        if _hash(row["payload"]) != row["payload_hash"]:
            raise AppendOnlyViolation(
                f"stored assessment {assessment_id} does not match its recorded hash"
            )
        return Assessment.model_validate_json(row["payload"])

    def load_draft(self, draft_id: str) -> SynthesisResult:
        row = self._connection.execute(
            "SELECT payload, payload_hash FROM draft WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            raise KeyError(draft_id)
        if _hash(row["payload"]) != row["payload_hash"]:
            raise AppendOnlyViolation(f"stored draft {draft_id} does not match its recorded hash")
        return SynthesisResult.model_validate_json(row["payload"])

    def watchlist(self) -> tuple[AssessmentHistory, ...]:
        """Each company's current assessment, for the Phase 14 watchlist.

        Ordered by company rather than by anything resembling severity. There
        is no risk ordering in this project to sort by, and inventing one here
        would be the composite score D-010, D-022, D-033 and D-036 have each
        refused -- arriving, at last, disguised as a sort key.
        """
        ciks = [
            row["cik"]
            for row in self._connection.execute(
                "SELECT DISTINCT cik FROM assessment ORDER BY cik"
            ).fetchall()
        ]
        latest = (self.latest(cik) for cik in ciks)
        return tuple(sorted((h for h in latest if h), key=lambda h: h.company))

    def counts(self) -> dict[str, int]:
        """Row counts, for tests and for a health check."""
        with closing(self._connection.cursor()) as cursor:
            return {
                table: cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("assessment", "draft", "review")
            }

    def raw(self) -> sqlite3.Connection:
        """The connection, for tests that need to attempt a forbidden write.

        Exposed deliberately: a guarantee that can only be tested through the
        module that provides it has not been tested.
        """
        return self._connection
