"""Evidence registration: addressability, completeness, and what is compressed."""

from __future__ import annotations

from datetime import date

import pytest

from credit_risk_copilot.assessment.evidence import (
    health_evidence,
    high_specificity_codes,
    model_evidence,
    narrative_evidence,
)
from credit_risk_copilot.assessment.models import Concern, EvidenceKind, LayerId
from credit_risk_copilot.health.models import EconomicDirection, SignalCode
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode, Specificity

from ._assessment_helpers import (
    FILED,
    explanation,
    health_report,
    health_signal,
    narrative_report,
    narrative_signal,
)


def _health() -> tuple:
    report = health_report(
        dimension_states={
            "liquidity": EconomicDirection.DETERIORATING,
            "leverage": EconomicDirection.IMPROVING,
        }
    )
    return health_evidence(report, accession="0000000000-15-000001", form="10-K", filed=FILED)


def test_evidence_ids_are_stable_across_runs():
    """The property every stored citation depends on.

    If this fails, a re-run of an unchanged pipeline repoints Phase 12's stored
    citations at different IDs, and Phase 13's immutable drafts stop
    validating.
    """
    assert [item.evidence_id for item in _health()] == [item.evidence_id for item in _health()]


def test_an_evidence_id_changes_when_the_cited_value_changes():
    """The other half: an ID that survived a value change would let a stored
    draft keep citing a number that is no longer there."""
    before = health_evidence(
        health_report(dimension_states={"liquidity": EconomicDirection.DETERIORATING}),
        filed=FILED,
    )
    after = health_evidence(
        health_report(dimension_states={"liquidity": EconomicDirection.IMPROVING}),
        filed=FILED,
    )
    status_before = next(i for i in before if i.kind is EvidenceKind.DIMENSION_STATUS)
    status_after = next(i for i in after if i.kind is EvidenceKind.DIMENSION_STATUS)
    assert status_before.evidence_id != status_after.evidence_id
    # ...while the identity key, which FR-11's diff runs on, does not.
    assert status_before.identity_key == status_after.identity_key


def test_inconclusive_trends_are_registered_rather_than_dropped():
    """A register that omitted them would make 'we could not compute liquidity'
    indistinguishable from 'liquidity is fine'."""
    items = health_evidence(
        health_report(dimension_states={"liquidity": EconomicDirection.INSUFFICIENT_DATA}),
        filed=FILED,
    )
    trends = [i for i in items if i.kind is EvidenceKind.RATIO_TREND]
    assert trends, "an inconclusive trend must still be citable"
    assert all(item.concern is Concern.UNKNOWN for item in trends)


def test_mixed_dimension_is_elevated_not_quiet():
    """Phase 7 keeps MIXED rather than netting an improvement against a
    deterioration; reading it as quiet here would net them after all."""
    from credit_risk_copilot.assessment.evidence import _DIMENSION_CONCERN
    from credit_risk_copilot.health.models import DimensionStatus

    assert _DIMENSION_CONCERN[DimensionStatus.MIXED] is Concern.ELEVATED


def test_health_signals_carry_their_dimension_and_elevate():
    signal = health_signal(SignalCode.LIQUIDITY_DETERIORATION, "liquidity", "current_ratio")
    items = health_evidence(
        health_report(
            dimension_states={"liquidity": EconomicDirection.DETERIORATING}, signals=(signal,)
        ),
        filed=FILED,
    )
    emitted = [i for i in items if i.kind is EvidenceKind.HEALTH_SIGNAL]
    assert len(emitted) == 1
    assert emitted[0].dimension == "liquidity"
    assert emitted[0].concern is Concern.ELEVATED


def test_model_read_comes_from_the_percentile_not_the_score():
    """D-033: the raw number is not a probability, so thresholding it would
    re-assert the reading D-033 removed."""
    high_score_no_rank = model_evidence(explanation(score=0.97, percentile=None))
    score_item = next(i for i in high_score_no_rank if i.kind is EvidenceKind.MODEL_SCORE)
    assert score_item.concern is Concern.UNKNOWN

    low_score_high_rank = model_evidence(explanation(score=0.03, percentile=99.0))
    score_item = next(i for i in low_score_high_rank if i.kind is EvidenceKind.MODEL_SCORE)
    assert score_item.concern is Concern.ELEVATED


def test_the_middle_of_the_distribution_is_unknown_not_quiet():
    """Forcing a 70th-percentile company into 'quiet' would manufacture
    contradictions out of the middle of the ranking."""
    items = model_evidence(explanation(percentile=70.0))
    score_item = next(i for i in items if i.kind is EvidenceKind.MODEL_SCORE)
    assert score_item.concern is Concern.UNKNOWN


def test_only_financial_groups_become_dimensions():
    """`missingness` and `scale` are attribution groups, not dimensions the
    health layer also speaks about, so they must not take part in a
    per-dimension rule."""
    items = model_evidence(explanation(dimensions={"leverage": 0.9}, missingness_contribution=0.5))
    groups = {
        str(i.detail["group"]): i.dimension for i in items if i.kind is EvidenceKind.MODEL_DRIVER
    }
    assert groups["leverage"] == "leverage"
    assert groups["missingness"] is None


def test_repeated_narrative_assertions_collapse_to_one_item_with_a_count():
    """Sixteen impairment sentences are one fact with sixteen instances."""
    signals = tuple(
        narrative_signal(
            RiskSignalCode.ASSET_IMPAIRMENT,
            Assertion.ASSERTED,
            specificity=Specificity.LOW,
            text=f"We recognised an impairment charge of ${n} million.",
            char_start=100 * n,
        )
        for n in (1, 2, 3)
    )
    items = narrative_evidence(narrative_report(signals=signals))
    emitted = [i for i in items if i.kind is EvidenceKind.NARRATIVE_SIGNAL]
    assert len(emitted) == 1
    assert emitted[0].detail["occurrences"] == 3
    # Document order, not "the best quote": there is no measured ranking over
    # sentences, so the first one a reader would reach is the one shown.
    assert emitted[0].quote == "We recognised an impairment charge of $1 million."


def test_asserted_and_negated_are_separate_items():
    """The self-contradiction rule cannot fire unless both moods survive
    registration as distinct, citable evidence."""
    items = narrative_evidence(
        narrative_report(
            signals=(
                narrative_signal(RiskSignalCode.COVENANT_BREACH, Assertion.ASSERTED),
                narrative_signal(
                    RiskSignalCode.COVENANT_BREACH,
                    Assertion.NEGATED,
                    text="We were in compliance with all covenants.",
                    char_start=900,
                ),
            )
        )
    )
    emitted = [i for i in items if i.kind is EvidenceKind.NARRATIVE_SIGNAL]
    assert len(emitted) == 2
    assert {i.concern for i in emitted} == {Concern.ELEVATED, Concern.QUIET}


def test_an_unlocated_section_is_registered_as_evidence():
    items = narrative_evidence(narrative_report(missing_sections=("item_7",)))
    gaps = [i for i in items if i.kind is EvidenceKind.NARRATIVE_COVERAGE]
    assert len(gaps) == 1
    assert "item_7" in gaps[0].summary


def test_high_specificity_selection_reads_the_measured_field():
    items = narrative_evidence(
        narrative_report(
            signals=(
                narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),
                narrative_signal(
                    RiskSignalCode.ASSET_IMPAIRMENT,
                    Assertion.ASSERTED,
                    specificity=Specificity.LOW,
                    text="An impairment was recorded.",
                    char_start=500,
                ),
            )
        )
    )
    severe = high_specificity_codes(items)
    assert [i.detail["code"] for i in severe] == ["going_concern_doubt"]


def test_every_stated_number_is_machine_readable():
    """FR-17 needs to check a drafted figure against the evidence without
    parsing English."""
    items = model_evidence(explanation(score=0.42, percentile=95.0))
    score_item = next(i for i in items if i.kind is EvidenceKind.MODEL_SCORE)
    assert 0.42 in score_item.numbers
    assert 95.0 in score_item.numbers


@pytest.mark.parametrize("filed", [FILED, date(2020, 1, 1)])
def test_narrative_evidence_carries_the_filing_date_the_gate_checks(filed):
    items = narrative_evidence(
        narrative_report(
            signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),),
            filed=filed,
        )
    )
    assert all(item.filed == filed for item in items)
    assert all(item.layer is LayerId.NARRATIVE for item in items)
