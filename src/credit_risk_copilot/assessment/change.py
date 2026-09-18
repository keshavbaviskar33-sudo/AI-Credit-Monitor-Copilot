"""What changed since the previous assessment (FR-11).

The diff runs on `identity_key`, not on `evidence_id`. That is the whole
design: an evidence ID is a content hash and changes whenever any cited value
changes, so two assessments of a deteriorating company share almost no IDs and
an ID-based diff would report the entire register as new every quarter. The
identity key strips the period and the values and keeps the subject -- "the
leverage dimension status", "the covenant-breach assertion" -- which is what
makes "still deteriorating, now worse" expressible at all.

The output is three-way rather than two-way. `APPEARED` and `RESOLVED` are the
obvious halves; `CHANGED` is the one that matters most and the one a set
difference cannot produce, because a signal that fired last period and fires
again with a worse number is neither new nor gone, and reporting it as
`UNCHANGED` would bury the deterioration.

Nothing here ranks the changes. A change report that sorted by importance
would need a severity model, which is the composite score this project has
refused four times; the report is grouped by layer and ordered by identity so
that two runs produce byte-identical output.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.assessment.models import (
    Assessment,
    ContradictionCode,
    CorroborationCode,
    EvidenceItem,
    EvidenceKind,
    LayerId,
)


class ChangeKind(str, Enum):
    """How one piece of evidence differs from the previous assessment."""

    #: Present now, absent before.
    APPEARED = "appeared"
    #: Present before, absent now. Named `RESOLVED` rather than `DISAPPEARED`
    #: only where it is a concern that stopped firing; the field
    #: `EvidenceChange.was_elevated` says which case this is, because a ratio
    #: trend that vanished because its inputs went missing has not resolved
    #: anything.
    RESOLVED = "resolved"
    #: Same subject, different content.
    CHANGED = "changed"


class EvidenceChange(BaseModel):
    """One subject's movement between two assessments."""

    model_config = ConfigDict(frozen=True)

    identity_key: str
    kind: ChangeKind
    layer: LayerId
    evidence_kind: EvidenceKind
    dimension: str | None = None
    #: The ID in the previous assessment, for `RESOLVED` and `CHANGED`.
    previous_id: str | None = None
    #: The ID in the current assessment, for `APPEARED` and `CHANGED`.
    current_id: str | None = None
    previous_summary: str | None = None
    current_summary: str | None = None
    #: Whether the previous item was a concern -- see `ChangeKind.RESOLVED`.
    was_elevated: bool = False
    #: Whether the current item is a concern.
    is_elevated: bool = False


class FindingChange(BaseModel):
    """A contradiction or corroboration that appeared or went away.

    Keyed on `(code, dimension)` rather than on cited evidence: the same
    disagreement supported by different quotes is the same disagreement, and a
    reader tracking a company wants to know it persisted, not that its
    citations were re-hashed.
    """

    model_config = ConfigDict(frozen=True)

    kind: ChangeKind
    code: str
    dimension: str | None = None
    explanation: str


class AssessmentChange(BaseModel):
    """The difference between two assessments of the same company."""

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    previous_as_of: str
    current_as_of: str
    evidence_changes: tuple[EvidenceChange, ...] = ()
    contradiction_changes: tuple[FindingChange, ...] = ()
    corroboration_changes: tuple[FindingChange, ...] = ()
    #: Movement in the model's ranking position, when both assessments have
    #: one. Reported in percentile points because that is the unit D-033 says
    #: the output is in; a change in the raw score is not reported at all.
    percentile_move: float | None = None

    @property
    def newly_elevated(self) -> tuple[EvidenceChange, ...]:
        """Evidence that is a concern now and was not before -- the headline
        of a monitoring product, and the only view this module offers, because
        every other ordering would be a severity judgement."""
        return tuple(
            change
            for change in self.evidence_changes
            if change.is_elevated and not change.was_elevated
        )


def _index(assessment: Assessment) -> dict[str, EvidenceItem]:
    """Latest item per identity key.

    A register can legitimately hold two items under one identity -- a
    narrative code asserted *and* denied share a subject in every sense but
    their mood -- so the key includes the assertion and this stays a 1:1 map.
    Where it is not, the later-registered item wins, deterministically, since
    registration order is itself deterministic.
    """
    return {item.identity_key: item for item in assessment.evidence}


def _findings_index(findings: object) -> dict[tuple[str, str | None], str]:
    return {
        (finding.code.value, finding.dimension): finding.explanation
        for finding in findings  # type: ignore[attr-defined]
    }


def _finding_changes(
    previous: dict[tuple[str, str | None], str],
    current: dict[tuple[str, str | None], str],
) -> tuple[FindingChange, ...]:
    changes = [
        FindingChange(
            kind=ChangeKind.APPEARED,
            code=code,
            dimension=dimension,
            explanation=current[(code, dimension)],
        )
        for code, dimension in sorted(
            set(current) - set(previous), key=lambda k: (k[0], k[1] or "")
        )
    ]
    changes += [
        FindingChange(
            kind=ChangeKind.RESOLVED,
            code=code,
            dimension=dimension,
            explanation=previous[(code, dimension)],
        )
        for code, dimension in sorted(
            set(previous) - set(current), key=lambda k: (k[0], k[1] or "")
        )
    ]
    return tuple(changes)


def compare(previous: Assessment, current: Assessment) -> AssessmentChange:
    """Diff two assessments of one company.

    Raises when the two describe different companies or run backwards in time:
    both are caller errors that would otherwise produce a plausible-looking
    report of nonsense, and a monitoring product that quietly compares two
    different issuers is worse than one that stops.
    """
    if previous.cik != current.cik:
        raise ValueError(
            f"cannot compare assessments of different companies: {previous.cik} vs {current.cik}"
        )
    if current.as_of < previous.as_of:
        raise ValueError(
            f"current assessment ({current.as_of}) predates the previous one ({previous.as_of})"
        )

    before, after = _index(previous), _index(current)
    changes: list[EvidenceChange] = []

    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old is not None and new is not None:
            if old.evidence_id == new.evidence_id:
                continue
            kind = ChangeKind.CHANGED
        elif new is not None:
            kind = ChangeKind.APPEARED
        else:
            kind = ChangeKind.RESOLVED
        reference = new or old
        assert reference is not None
        changes.append(
            EvidenceChange(
                identity_key=key,
                kind=kind,
                layer=reference.layer,
                evidence_kind=reference.kind,
                dimension=reference.dimension,
                previous_id=old.evidence_id if old else None,
                current_id=new.evidence_id if new else None,
                previous_summary=old.summary if old else None,
                current_summary=new.summary if new else None,
                was_elevated=bool(old and old.concern.value == "elevated"),
                is_elevated=bool(new and new.concern.value == "elevated"),
            )
        )

    def _percentile(assessment: Assessment) -> float | None:
        for item in assessment.of_kind(EvidenceKind.MODEL_SCORE):
            value = item.detail.get("score_percentile")
            if isinstance(value, (int, float)):
                return float(value)
        return None

    old_pct, new_pct = _percentile(previous), _percentile(current)
    return AssessmentChange(
        cik=current.cik,
        company=current.company,
        previous_as_of=previous.as_of.isoformat(),
        current_as_of=current.as_of.isoformat(),
        evidence_changes=tuple(changes),
        contradiction_changes=_finding_changes(
            _findings_index(previous.contradictions), _findings_index(current.contradictions)
        ),
        corroboration_changes=_finding_changes(
            _findings_index(previous.corroborations), _findings_index(current.corroborations)
        ),
        percentile_move=(
            None if old_pct is None or new_pct is None else round(new_pct - old_pct, 4)
        ),
    )


__all__ = [
    "AssessmentChange",
    "ChangeKind",
    "ContradictionCode",
    "CorroborationCode",
    "EvidenceChange",
    "FindingChange",
    "compare",
]
