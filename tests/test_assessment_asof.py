"""The point-in-time gate (FR-05).

These tests are the guarantee. A historical replay is only worth running if
evidence dated after the replay date cannot reach it, and "the caller filters
first" is not a guarantee -- it is a convention that four layers each have to
remember.
"""

from __future__ import annotations

from datetime import date

import pytest

from credit_risk_copilot.assessment.asof import AsOfGate, AsOfViolation
from credit_risk_copilot.assessment.evidence import narrative_evidence
from credit_risk_copilot.assessment.models import (
    Concern,
    EvidenceItem,
    EvidenceKind,
    LayerId,
)
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode

from ._assessment_helpers import narrative_report, narrative_signal

AS_OF = date(2015, 3, 2)


def _item(filed: date | None) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="EV-NS-deadbeef",
        identity_key="narrative:narrative_signal:test",
        layer=LayerId.NARRATIVE,
        kind=EvidenceKind.NARRATIVE_SIGNAL,
        concern=Concern.ELEVATED,
        summary="test",
        filed=filed,
    )


def test_a_filing_on_the_as_of_date_is_admitted():
    """Inclusive by design: a 10-K accepted on the replay date was public on
    the replay date."""
    AsOfGate(as_of=AS_OF).verify([_item(AS_OF)])


def test_a_filing_after_the_as_of_date_is_rejected():
    with pytest.raises(AsOfViolation) as excinfo:
        AsOfGate(as_of=AS_OF).verify([_item(date(2015, 3, 3))])
    # The message has to name the item and the gap; a leakage failure found in
    # a 200-item assessment is unactionable without them.
    assert "EV-NS-deadbeef" in str(excinfo.value)
    assert "1 day(s) after" in str(excinfo.value)


def test_undated_evidence_fails_closed():
    """An item with no provenance is the shape leakage takes; a gate that
    waved it through would guarantee only the filings it could see."""
    with pytest.raises(AsOfViolation, match="carries no filing date"):
        AsOfGate(as_of=AS_OF).verify([_item(None)])


def test_undated_evidence_can_be_admitted_only_by_asking():
    AsOfGate(as_of=AS_OF, require_filed=False).verify([_item(None)])


def test_admissible_filters_without_raising():
    gate = AsOfGate(as_of=AS_OF)
    items = [_item(date(2014, 1, 1)), _item(date(2016, 1, 1))]
    assert [i.filed for i in gate.admissible(items)] == [date(2014, 1, 1)]


def test_the_gate_reads_the_filing_date_not_the_fiscal_period():
    """FY2014 figures were not public on 2014-12-31. A gate on the period end
    reads the future by a quarter."""
    report = narrative_report(
        signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),),
        filed=date(2015, 3, 2),
    )
    items = narrative_evidence(report)
    # An as-of date inside FY2014 must reject evidence from the FY2014 10-K,
    # because that filing did not exist yet.
    with pytest.raises(AsOfViolation):
        AsOfGate(as_of=date(2014, 12, 31)).verify(items)
    AsOfGate(as_of=date(2015, 3, 2)).verify(items)
