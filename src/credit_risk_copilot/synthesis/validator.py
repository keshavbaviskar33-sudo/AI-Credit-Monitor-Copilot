"""The grounding validator (FR-17).

Eight checks over a draft and the assessment it was generated from. All of
them run in code, none of them ask a model anything, and none of them depend
on the draft's prose being well formed -- a validator that needs the output to
be reasonable before it can tell you the output is unreasonable is not a
validator.

## The checks, and what each one is for

| Check | Catches |
|---|---|
| citations resolve | an invented evidence ID |
| every claim cites something | an assertion with no source at all |
| numbers are grounded | a fabricated figure |
| numbers are cited correctly | a real figure attached to the wrong claim |
| quotes are verbatim | words put in the filer's mouth |
| no forbidden conclusion | the output shape D-010 forbids |
| contradictions are described | the failure D-038 names explicitly |
| layer absences are described | silence rendered as calm |

The last two are completeness checks and they are the reason this module takes
the `Assessment` rather than just the draft. A fabrication check can work from
the draft plus a list of valid IDs; "the assessment had three contradictions
and the draft mentions none" cannot.

## Why a mis-cited number is not a fabricated one

Both are wrong, and treating them identically would be easier. But they have
different causes and different fixes: a fabricated figure means the model
invented a measurement and the draft is unusable; a mis-cited one means a true
figure is attached to a claim citing different evidence, which a reviewer
repoints in a second. Collapsing them would force a regeneration for the
cheaper error and teach a reader to ignore the category.

## What this module deliberately does not check

**Whether a claim is *true* given its evidence.** "Leverage is improving"
citing a deteriorating-leverage evidence item resolves, carries no numbers,
quotes nothing, and passes every check here. That is a semantic judgement, and
the only things available to make it are another model -- which is the
ungrounded step this phase exists to avoid -- or the analyst, who has it by
design (D-003). The limitation is stated in the phase doc rather than papered
over with a heuristic that would catch some cases and imply it catches all.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from credit_risk_copilot.assessment.models import Assessment, EvidenceItem, EvidenceKind
from credit_risk_copilot.synthesis.numbers import mentions, ungrounded
from credit_risk_copilot.synthesis.schema import (
    REJECTING,
    Claim,
    ClaimKind,
    DraftSynthesis,
    FailureCode,
    GroundingFinding,
    Severity,
    ValidationReport,
)

#: Output shapes the project has refused since D-010. Matched on the phrase, not
#: on a classifier: the ban is on a small, enumerable set of constructions, and a
#: regex that a reader can audit line by line is the right tool for a rule whose
#: whole value is that it cannot be argued with.
#:
#: Each pattern is anchored on the *assertion*, not the vocabulary. "The score is
#: not a probability of default" must pass -- it is the caveat the project
#: requires -- while "a 72% probability of default" must not, so the negated and
#: qualified forms are excluded by the lookbehind rather than by hoping the
#: phrase does not appear.
FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?<!not )(?<!never )(?<!is not a )\b\d+(?:\.\d+)?\s*%?\s*(?:chance|probability|likelihood)"
        r"\s+(?:of|that)\b",
        "states a numeric probability of an outcome",
    ),
    (
        r"\b(?:we|I|the system|this report)\s+(?:recommend|advise|conclude)\s+"
        r"(?:approving|declining|rejecting|extending|withdrawing)\b",
        "makes a credit decision",
    ),
    (
        r"\b(?:assign|assigns|assigned|we rate|rated)\s+(?:a\s+)?"
        r"(?:credit\s+)?rating\s+of\b|\brating of\s+[A-C][A-C+-]{0,3}\b",
        "assigns a credit rating",
    ),
    (
        r"\b(?:will|is going to|is certain to)\s+(?:default|go bankrupt|file for bankruptcy)\b",
        "predicts an outcome as certain",
    ),
    (
        r"\b(?:creditworthy|not creditworthy|safe to lend|do not lend)\b",
        "states a lending conclusion",
    ),
)

_COMPILED = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in FORBIDDEN_PATTERNS
)


def _evidence_text(items: Sequence[EvidenceItem]) -> str:
    parts: list[str] = []
    for item in items:
        parts.append(item.summary)
        if item.period_label:
            parts.append(item.period_label)
        if item.quote:
            parts.append(item.quote)
    return " ".join(parts)


def _identity_text(assessment: Assessment) -> str:
    """The assessment's own header, available to every claim.

    Found by measurement, not by design: the first run rejected a correct draft
    for 21st Century Oncology Holdings because the `21` in the company's *name*
    parsed as a numeric assertion with no matching value. A company name, a
    CIK, the as-of date and the fiscal period are identity, not measurement,
    and naming them is never a quantitative claim -- so they ground every
    claim in the draft rather than only the ones that happen to cite an item
    mentioning them.
    """
    parts = [assessment.company, str(assessment.cik), assessment.as_of.isoformat()]
    if assessment.period_label:
        parts.append(assessment.period_label)
    return " ".join(parts)


def _values(items: Sequence[EvidenceItem]) -> frozenset[float]:
    return frozenset(number for item in items for number in item.numbers)


def _cited_items(assessment: Assessment, claim: Claim) -> tuple[EvidenceItem, ...]:
    found = (assessment.by_id(evidence_id) for evidence_id in claim.evidence_ids)
    return tuple(item for item in found if item is not None)


def _check_quote(claim: Claim, index: int, cited: Sequence[EvidenceItem]) -> list[GroundingFinding]:
    """A quoted sentence must be verbatim in a cited narrative item.

    Phase 10's SC-03 guarantees the quote on an evidence item is verbatim from
    the filing; this check carries that guarantee across the LLM, which is the
    one place in the pipeline where text could be silently rewritten. A
    substring is accepted so a draft may quote a clause of the stored sentence
    -- shortening is not fabricating -- but nothing else is.
    """
    if claim.quote is None:
        return []
    sources = [item.quote for item in cited if item.quote is not None]
    normalised = " ".join(claim.quote.split())
    for source in sources:
        if normalised in " ".join(source.split()):
            return []
    return [
        GroundingFinding(
            code=FailureCode.NON_VERBATIM_QUOTE,
            severity=Severity.REJECT,
            claim_index=index,
            subject=claim.quote[:120],
            detail=(
                "The quoted text is not present in any narrative evidence this claim cites."
                if sources
                else "The claim presents a quotation but cites no evidence carrying one."
            ),
        )
    ]


def _check_numbers(
    claim: Claim,
    index: int,
    cited: Sequence[EvidenceItem],
    assessment: Assessment,
) -> tuple[list[GroundingFinding], int]:
    """Every literal in the claim, against the evidence it cites.

    A literal not supported by the cited evidence is looked up in the whole
    assessment before it is called a fabrication, which is what separates
    `MISCITED_NUMBER` from `UNGROUNDED_NUMBER`.
    """
    identity = _identity_text(assessment)
    counted = len(mentions(claim.text))
    failures = ungrounded(claim.text, _values(cited), f"{_evidence_text(cited)} {identity}")
    if not failures:
        return [], counted

    everywhere = _values(assessment.evidence)
    everywhere_text = f"{_evidence_text(assessment.evidence)} {identity}"
    findings: list[GroundingFinding] = []
    for literal in failures:
        elsewhere = not ungrounded(literal, everywhere, everywhere_text)
        findings.append(
            GroundingFinding(
                code=FailureCode.MISCITED_NUMBER if elsewhere else FailureCode.UNGROUNDED_NUMBER,
                severity=Severity.FLAG if elsewhere else Severity.REJECT,
                claim_index=index,
                subject=literal,
                detail=(
                    f"{literal!r} appears elsewhere in the assessment but not in the evidence"
                    " this claim cites."
                    if elsewhere
                    else f"{literal!r} does not appear anywhere in the assessment."
                ),
            )
        )
    return findings, counted


def _check_forbidden(claim: Claim, index: int) -> list[GroundingFinding]:
    findings = []
    for pattern, reason in _COMPILED:
        match = pattern.search(claim.text)
        if match:
            findings.append(
                GroundingFinding(
                    code=FailureCode.FORBIDDEN_CONCLUSION,
                    severity=Severity.REJECT,
                    claim_index=index,
                    subject=match.group(0),
                    detail=f"The claim {reason}, which this product does not produce (D-010).",
                )
            )
    return findings


def _check_completeness(draft: DraftSynthesis, assessment: Assessment) -> list[GroundingFinding]:
    """Did the draft describe what the assessment required it to describe?

    Coverage is checked by *count of described contradictions*, not by
    matching each one: a draft that describes two of three disagreements is a
    judgement call about salience, and a validator that demanded all of them
    would force the model to pad. A draft that describes none, with
    contradictions present, is not a judgement call.
    """
    findings: list[GroundingFinding] = []

    if assessment.contradictions and not draft.of_kind(ClaimKind.DISAGREEMENT):
        codes = ", ".join(sorted({c.code.value for c in assessment.contradictions}))
        findings.append(
            GroundingFinding(
                code=FailureCode.OMITTED_CONTRADICTION,
                severity=Severity.REJECT,
                subject=codes,
                detail=(
                    f"The assessment carries {len(assessment.contradictions)} contradiction(s)"
                    f" ({codes}) and the draft describes none."
                ),
            )
        )

    if assessment.layers_absent and not draft.of_kind(ClaimKind.LIMITATION):
        absent = ", ".join(a.layer.value for a in assessment.layers_absent)
        findings.append(
            GroundingFinding(
                code=FailureCode.OMITTED_LAYER_ABSENCE,
                severity=Severity.REJECT,
                subject=absent,
                detail=(
                    f"{absent} produced no evidence for this assessment and the draft states no"
                    " limitation, so a reader cannot tell an absence of findings from an"
                    " absence of analysis."
                ),
            )
        )
    return findings


def validate(draft: DraftSynthesis, assessment: Assessment) -> ValidationReport:
    """Check a draft against the assessment it was generated from.

    The report is the product of this phase. `accepted` is false whenever any
    finding is in `REJECTING`; a flagged draft is accepted and carries its
    findings to the reviewer.
    """
    findings: list[GroundingFinding] = []
    citations = 0
    numbers = 0

    for index, claim in enumerate(draft.all_claims):
        missing = assessment.validate_citations(claim.evidence_ids)
        citations += len(claim.evidence_ids)
        for evidence_id in missing:
            findings.append(
                GroundingFinding(
                    code=FailureCode.UNRESOLVED_CITATION,
                    severity=Severity.REJECT,
                    claim_index=index,
                    subject=evidence_id,
                    detail=f"{evidence_id} is not an evidence item in this assessment.",
                )
            )

        # A CHECK is a next action for the analyst ("confirm the missing
        # sections against the filing"), so it asserts nothing about the
        # company and needs no source. Every other kind does.
        if not claim.evidence_ids and claim.kind is not ClaimKind.CHECK:
            findings.append(
                GroundingFinding(
                    code=FailureCode.UNCITED_CLAIM,
                    severity=Severity.REJECT,
                    claim_index=index,
                    subject=claim.text[:120],
                    detail="The claim cites no evidence.",
                )
            )

        cited = _cited_items(assessment, claim)
        number_findings, counted = _check_numbers(claim, index, cited, assessment)
        findings.extend(number_findings)
        numbers += counted
        findings.extend(_check_quote(claim, index, cited))
        findings.extend(_check_forbidden(claim, index))

    findings.extend(_check_completeness(draft, assessment))

    return ValidationReport(
        accepted=not any(finding.code in REJECTING for finding in findings),
        findings=tuple(findings),
        claims_checked=len(draft.all_claims),
        citations_checked=citations,
        numbers_checked=numbers,
    )


def narrative_evidence_ids(assessment: Assessment) -> frozenset[str]:
    """Evidence a claim may attach a quotation to."""
    return frozenset(
        item.evidence_id
        for item in assessment.of_kind(EvidenceKind.NARRATIVE_SIGNAL)
        if item.quote is not None
    )
