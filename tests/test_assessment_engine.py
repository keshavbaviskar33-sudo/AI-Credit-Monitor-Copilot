"""Assembly, layer absence, citation validation and the change report."""

from __future__ import annotations

from datetime import date

import pytest

from credit_risk_copilot.assessment.asof import AsOfViolation
from credit_risk_copilot.assessment.change import ChangeKind, compare
from credit_risk_copilot.assessment.engine import FilingStamp, assemble_assessment
from credit_risk_copilot.assessment.models import EvidenceKind, LayerId
from credit_risk_copilot.health.models import EconomicDirection
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode

from ._assessment_helpers import (
    FILED,
    explanation,
    health_report,
    narrative_report,
    narrative_signal,
)


def _stamp(as_of: date) -> FilingStamp:
    """The filing that closed the health window, dated on the as-of date.

    Written as a function rather than a constant because the first draft used a
    constant and the gate rejected it: a 2014 assessment stamped with a 2015
    filing is exactly the leak `AsOfGate` exists to catch, and it appeared in
    the test fixture before it could appear anywhere else.
    """
    return FilingStamp(accession="0000000000-15-000001", form="10-K", filed=as_of)


def _assessment(*, as_of=FILED, health=None, model=None, narrative=None, **kwargs):
    return assemble_assessment(
        cik=1,
        company="TEST CO",
        as_of=as_of,
        health=health,
        health_filing=_stamp(as_of) if health is not None else None,
        health_absent_reason=None if health is not None else "no filings in window",
        explanation=model,
        model_absent_reason=None if model is not None else "company out of training range",
        narrative=narrative,
        narrative_absent_reason=None if narrative is not None else "filing text unavailable",
        **kwargs,
    )


def test_a_full_assessment_records_every_layer_as_present():
    assessment = _assessment(
        health=health_report(dimension_states={"liquidity": EconomicDirection.DETERIORATING}),
        model=explanation(percentile=99.0),
        narrative=narrative_report(
            signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),)
        ),
    )
    assert set(assessment.layers_present) == {
        LayerId.FINANCIAL_HEALTH,
        LayerId.PREDICTIVE_MODEL,
        LayerId.NARRATIVE,
    }
    assert assessment.layers_absent == ()
    assert assessment.period_label == "FY2014"


def test_a_missing_layer_is_recorded_with_its_reason():
    """An assessment where the model failed must not look like one where the
    model ran and found nothing."""
    assessment = _assessment(
        health=health_report(dimension_states={"liquidity": EconomicDirection.STABLE}),
        narrative=narrative_report(),
    )
    absent = {a.layer: a.reason for a in assessment.layers_absent}
    assert absent == {LayerId.PREDICTIVE_MODEL: "company out of training range"}
    assert assessment.for_layer(LayerId.PREDICTIVE_MODEL) == ()


def test_a_missing_layer_without_a_reason_is_refused():
    """A default reason is the same as no reason."""
    with pytest.raises(ValueError, match="model_absent_reason is required"):
        assemble_assessment(
            cik=1,
            company="TEST CO",
            as_of=FILED,
            health=None,
            health_absent_reason="none",
            narrative=None,
            narrative_absent_reason="none",
        )


def test_a_health_report_without_a_filing_stamp_is_refused():
    """The gate cannot verify a window that does not say when it closed."""
    with pytest.raises(ValueError, match="health_filing is required"):
        assemble_assessment(
            cik=1,
            company="TEST CO",
            as_of=FILED,
            health=health_report(dimension_states={"liquidity": EconomicDirection.STABLE}),
            model_absent_reason="none",
            narrative_absent_reason="none",
        )


def test_the_gate_runs_over_the_assembled_evidence():
    """Enforcement at the bottom, not at the caller: a layer that over-fetched
    is caught by the assessment it produced."""
    with pytest.raises(AsOfViolation):
        _assessment(
            as_of=date(2014, 6, 30),
            narrative=narrative_report(
                signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),),
                filed=FILED,
            ),
        )


def test_citations_are_validated_mechanically():
    assessment = _assessment(model=explanation(percentile=99.0))
    real = assessment.evidence[0].evidence_id
    assert assessment.validate_citations([real]) == ()
    assert assessment.validate_citations([real, "EV-MS-00000000"]) == ("EV-MS-00000000",)


def test_every_stated_number_is_reachable_for_the_fr17_check():
    assessment = _assessment(model=explanation(score=0.42, percentile=95.0))
    numbers = assessment.known_numbers()
    assert 0.42 in numbers and 95.0 in numbers
    assert 0.43 not in numbers


def test_pipeline_versions_are_recorded():
    assessment = _assessment(model=explanation(percentile=50.0), narrative=narrative_report())
    assert assessment.pipeline_versions["model"] == "gradient_boosting_all"
    assert assessment.pipeline_versions["attribution"] == "tree_shap"
    assert "nlp_catalog" in assessment.pipeline_versions


def test_identical_evidence_registered_twice_is_one_item():
    report = narrative_report(
        signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),)
    )
    assessment = _assessment(narrative=report)
    ids = [item.evidence_id for item in assessment.evidence]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
# FR-11: change since the previous assessment


def _quarter(direction: EconomicDirection, percentile: float, as_of: date):
    return _assessment(
        as_of=as_of,
        health=health_report(dimension_states={"leverage": direction}),
        model=explanation(percentile=percentile, prediction_date=as_of),
    )


def test_a_worsening_dimension_is_changed_not_new():
    """The case a set difference cannot produce: same subject, worse number."""
    before = _quarter(EconomicDirection.STABLE, 40.0, date(2014, 3, 1))
    after = _quarter(EconomicDirection.DETERIORATING, 95.0, date(2015, 3, 2))
    diff = compare(before, after)
    status_change = next(
        c
        for c in diff.evidence_changes
        if c.evidence_kind is EvidenceKind.DIMENSION_STATUS and c.dimension == "leverage"
    )
    assert status_change.kind is ChangeKind.CHANGED
    assert status_change.was_elevated is False
    assert status_change.is_elevated is True
    assert status_change in diff.newly_elevated


def test_an_unchanged_subject_produces_no_entry():
    before = _quarter(EconomicDirection.STABLE, 40.0, date(2014, 3, 1))
    after = _quarter(EconomicDirection.STABLE, 40.0, date(2015, 3, 2))
    diff = compare(before, after)
    assert [c.evidence_kind for c in diff.evidence_changes if c.dimension == "leverage"] == []


def test_the_percentile_move_is_reported_in_percentile_points():
    diff = compare(
        _quarter(EconomicDirection.STABLE, 40.0, date(2014, 3, 1)),
        _quarter(EconomicDirection.STABLE, 95.0, date(2015, 3, 2)),
    )
    assert diff.percentile_move == 55.0


def test_a_new_contradiction_is_reported_as_appeared():
    before = _assessment(
        as_of=date(2014, 3, 1),
        health=health_report(dimension_states={"leverage": EconomicDirection.STABLE}),
        model=explanation(percentile=40.0, prediction_date=date(2014, 3, 1)),
    )
    after = _assessment(
        as_of=date(2015, 3, 2),
        health=health_report(dimension_states={"leverage": EconomicDirection.STABLE}),
        model=explanation(percentile=98.0, prediction_date=date(2015, 3, 2)),
    )
    diff = compare(before, after)
    appeared = [c for c in diff.contradiction_changes if c.kind is ChangeKind.APPEARED]
    assert "model_elevated_health_quiet" in {c.code for c in appeared}


def test_comparing_two_different_companies_is_refused():
    a = _assessment(model=explanation(percentile=50.0))
    b = assemble_assessment(
        cik=2,
        company="OTHER CO",
        as_of=FILED,
        health_absent_reason="none",
        explanation=explanation(percentile=50.0),
        narrative_absent_reason="none",
    )
    with pytest.raises(ValueError, match="different companies"):
        compare(a, b)


def test_comparing_backwards_in_time_is_refused():
    old = _quarter(EconomicDirection.STABLE, 40.0, date(2014, 3, 1))
    new = _quarter(EconomicDirection.STABLE, 40.0, date(2015, 3, 2))
    with pytest.raises(ValueError, match="predates"):
        compare(new, old)
