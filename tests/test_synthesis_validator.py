"""The grounding validator (FR-17), check by check.

Every test names a way a draft can be wrong and asserts the validator says so.
The two tests that matter most are the ones asserting a *correct* draft is
accepted: a validator that rejects good drafts is not strict, it is broken,
and it will be switched off the first week it is used.
"""

from __future__ import annotations

from credit_risk_copilot.assessment.engine import FilingStamp, assemble_assessment
from credit_risk_copilot.assessment.models import EvidenceKind
from credit_risk_copilot.health.models import EconomicDirection
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode
from credit_risk_copilot.synthesis.schema import Claim, ClaimKind, DraftSynthesis, FailureCode
from credit_risk_copilot.synthesis.validator import validate

from ._assessment_helpers import (
    FILED,
    explanation,
    health_report,
    narrative_report,
    narrative_signal,
)

QUOTE = "There exists substantial doubt about our ability to continue as a going concern."


def build_assessment(*, with_narrative: bool = True, with_model: bool = True):
    return assemble_assessment(
        cik=1,
        company="TEST CO",
        as_of=FILED,
        health=health_report(
            dimension_states={
                "liquidity": EconomicDirection.DETERIORATING,
                "leverage": EconomicDirection.IMPROVING,
            }
        ),
        health_filing=FilingStamp(accession="0000000000-15-000001", form="10-K", filed=FILED),
        explanation=explanation(score=0.8123, percentile=97.8312) if with_model else None,
        model_absent_reason=None if with_model else "company outside training range",
        narrative=narrative_report(
            signals=(
                narrative_signal(
                    RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED, text=QUOTE
                ),
            )
        )
        if with_narrative
        else None,
        narrative_absent_reason=None if with_narrative else "filing text unavailable",
    )


def ids(assessment, kind: EvidenceKind) -> tuple[str, ...]:
    return tuple(item.evidence_id for item in assessment.of_kind(kind))


def good_draft(assessment) -> DraftSynthesis:
    """A draft that cites correctly, rounds honestly and covers what it must."""
    score = ids(assessment, EvidenceKind.MODEL_SCORE)[0]
    liquidity = next(
        i.evidence_id
        for i in assessment.of_kind(EvidenceKind.DIMENSION_STATUS)
        if i.dimension == "liquidity"
    )
    narrative = ids(assessment, EvidenceKind.NARRATIVE_SIGNAL)[0]
    claims = [
        Claim(
            kind=ClaimKind.FINDING,
            text="Liquidity is deteriorating over FY2014.",
            evidence_ids=(liquidity,),
            dimension="liquidity",
        ),
        Claim(
            kind=ClaimKind.FINDING,
            text="The filer states substantial doubt about continuing as a going concern.",
            evidence_ids=(narrative,),
            quote="substantial doubt about our ability to continue as a going concern",
        ),
        Claim(
            kind=ClaimKind.CHECK,
            text="Confirm the covenant position against the filing's debt footnote.",
        ),
    ]
    if assessment.contradictions:
        claims.append(
            Claim(
                kind=ClaimKind.DISAGREEMENT,
                text="The layers do not agree on this company's position.",
                evidence_ids=(score,),
            )
        )
    if assessment.layers_absent:
        claims.append(
            Claim(
                kind=ClaimKind.LIMITATION,
                text="One analytical layer did not run for this filing.",
                evidence_ids=(liquidity,),
            )
        )
    return DraftSynthesis(
        headline=Claim(
            kind=ClaimKind.FINDING,
            text="The company ranks at the 97.8th percentile of the monitored population.",
            evidence_ids=(score,),
        ),
        claims=tuple(claims),
    )


def test_a_correct_draft_is_accepted():
    """Including a rounded restatement (97.8312 written as 97.8) and a quote
    shortened to a clause -- both of which a real draft does constantly."""
    assessment = build_assessment()
    report = validate(good_draft(assessment), assessment)
    assert report.accepted, report.findings
    assert report.findings == ()
    assert report.claims_checked == len(good_draft(assessment).all_claims)


def test_a_fabricated_citation_is_rejected():
    assessment = build_assessment()
    draft = good_draft(assessment)
    broken = draft.model_copy(
        update={"headline": draft.headline.model_copy(update={"evidence_ids": ("EV-MS-deadbeef",)})}
    )
    report = validate(broken, assessment)
    assert not report.accepted
    assert FailureCode.UNRESOLVED_CITATION in report.codes()
    assert report.findings[0].subject == "EV-MS-deadbeef"


def test_a_fabricated_number_is_rejected():
    assessment = build_assessment()
    draft = good_draft(assessment)
    broken = draft.model_copy(
        update={
            "headline": draft.headline.model_copy(
                update={"text": "The company ranks at the 62.5th percentile."}
            )
        }
    )
    report = validate(broken, assessment)
    assert not report.accepted
    assert FailureCode.UNGROUNDED_NUMBER in report.codes()


def test_a_real_number_cited_to_the_wrong_evidence_is_flagged_not_rejected():
    """A mis-citation is a different error from a hallucination: the figure is
    real and a reviewer repoints it, so the draft survives with a finding."""
    assessment = build_assessment()
    draft = good_draft(assessment)
    liquidity = next(
        i.evidence_id
        for i in assessment.of_kind(EvidenceKind.DIMENSION_STATUS)
        if i.dimension == "liquidity"
    )
    broken = draft.model_copy(
        update={
            "headline": draft.headline.model_copy(
                update={
                    "text": "The company ranks at the 97.8th percentile.",
                    "evidence_ids": (liquidity,),
                }
            )
        }
    )
    report = validate(broken, assessment)
    assert report.accepted
    assert FailureCode.MISCITED_NUMBER in report.codes()
    assert report.flags and not report.rejections


def test_an_uncited_finding_is_rejected_but_an_uncited_check_is_not():
    assessment = build_assessment()
    draft = good_draft(assessment)
    assert any(c.kind is ClaimKind.CHECK and not c.evidence_ids for c in draft.all_claims)
    assert validate(draft, assessment).accepted

    broken = draft.model_copy(
        update={"headline": draft.headline.model_copy(update={"evidence_ids": ()})}
    )
    assert FailureCode.UNCITED_CLAIM in validate(broken, assessment).codes()


def test_a_reworded_quotation_is_rejected():
    """Phase 10's SC-03 guarantees the stored quote is verbatim; this is the
    one place in the pipeline where text could be silently rewritten."""
    assessment = build_assessment()
    draft = good_draft(assessment)
    claims = list(draft.claims)
    claims[1] = claims[1].model_copy(
        update={"quote": "substantial doubt about our capacity to continue as a going concern"}
    )
    report = validate(draft.model_copy(update={"claims": tuple(claims)}), assessment)
    assert not report.accepted
    assert FailureCode.NON_VERBATIM_QUOTE in report.codes()


def test_a_probability_of_default_is_rejected():
    assessment = build_assessment()
    draft = good_draft(assessment)
    score = ids(assessment, EvidenceKind.MODEL_SCORE)[0]
    broken = draft.model_copy(
        update={
            "claims": draft.claims
            + (
                Claim(
                    kind=ClaimKind.FINDING,
                    text="There is a 72% probability of default within twelve months.",
                    evidence_ids=(score,),
                ),
            )
        }
    )
    report = validate(broken, assessment)
    assert not report.accepted
    assert FailureCode.FORBIDDEN_CONCLUSION in report.codes()


def test_the_required_caveat_is_not_mistaken_for_a_forbidden_conclusion():
    """ "The score is not a probability of default" is the sentence D-010
    requires; a ban that caught it would ban the caveat it exists to protect."""
    assessment = build_assessment()
    draft = good_draft(assessment)
    score = ids(assessment, EvidenceKind.MODEL_SCORE)[0]
    safe = draft.model_copy(
        update={
            "claims": draft.claims
            + (
                Claim(
                    kind=ClaimKind.LIMITATION,
                    text=(
                        "The ranking position is not a probability of default and must not be"
                        " read as one."
                    ),
                    evidence_ids=(score,),
                ),
            )
        }
    )
    assert validate(safe, assessment).accepted


def test_omitting_every_contradiction_is_rejected():
    assessment = build_assessment()
    assert assessment.contradictions
    draft = good_draft(assessment)
    stripped = tuple(c for c in draft.claims if c.kind is not ClaimKind.DISAGREEMENT)
    report = validate(draft.model_copy(update={"claims": stripped}), assessment)
    assert not report.accepted
    assert FailureCode.OMITTED_CONTRADICTION in report.codes()


def test_omitting_an_absent_layer_is_rejected():
    """Silence rendered as calm -- the failure the whole pipeline is shaped to
    prevent."""
    assessment = build_assessment(with_model=False)
    assert assessment.layers_absent
    liquidity = next(
        i.evidence_id
        for i in assessment.of_kind(EvidenceKind.DIMENSION_STATUS)
        if i.dimension == "liquidity"
    )
    draft = DraftSynthesis(
        headline=Claim(
            kind=ClaimKind.FINDING,
            text="Liquidity is deteriorating.",
            evidence_ids=(liquidity,),
        )
    )
    report = validate(draft, assessment)
    assert not report.accepted
    assert FailureCode.OMITTED_LAYER_ABSENCE in report.codes()


def test_a_digit_in_the_company_name_is_not_a_numeric_claim():
    """Found by measurement, not by design.

    The first fault-injection run rejected a correct draft for 21st Century
    Oncology Holdings: the `21` in the company's own name parsed as an
    unsupported numeric assertion. Identity -- name, CIK, as-of date, fiscal
    period -- is not measurement, and naming it is never a quantitative claim.
    """
    assessment = build_assessment().model_copy(
        update={"company": "21st Century Oncology Holdings, Inc."}
    )
    score = ids(assessment, EvidenceKind.MODEL_SCORE)[0]
    draft = DraftSynthesis(
        headline=Claim(
            kind=ClaimKind.FINDING,
            text="21st Century Oncology Holdings, Inc. ranks at the 97.8th percentile.",
            evidence_ids=(score,),
        ),
        claims=(
            Claim(
                kind=ClaimKind.DISAGREEMENT,
                text="Layers disagree.",
                evidence_ids=(score,),
            ),
        ),
    )
    report = validate(draft, assessment)
    assert report.accepted, report.findings
    # ...and a number that is genuinely absent is still caught in the same claim.
    broken = draft.model_copy(
        update={
            "headline": draft.headline.model_copy(
                update={
                    "text": "21st Century Oncology Holdings, Inc. ranks at the 44.1th percentile."
                }
            )
        }
    )
    assert FailureCode.UNGROUNDED_NUMBER in validate(broken, assessment).codes()


def test_the_validator_counts_what_it_checked():
    assessment = build_assessment()
    report = validate(good_draft(assessment), assessment)
    assert report.citations_checked > 0
    assert report.numbers_checked > 0
