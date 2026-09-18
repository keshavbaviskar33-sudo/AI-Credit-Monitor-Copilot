"""The contradiction and corroboration rules (FR-15).

Each test states a scenario in the layers' own vocabulary and asserts which
rule fires. The negative cases matter as much as the positive ones: a rule
that fires on every assessment is indistinguishable from no rule, and three of
the tests here exist only to pin a case where nothing should be reported.
"""

from __future__ import annotations

from credit_risk_copilot.assessment.contradictions import detect_contradictions
from credit_risk_copilot.assessment.corroboration import detect_corroboration
from credit_risk_copilot.assessment.evidence import (
    health_evidence,
    model_evidence,
    narrative_evidence,
)
from credit_risk_copilot.assessment.models import (
    Concern,
    ContradictionCode,
    CorroborationCode,
    LayerId,
)
from credit_risk_copilot.assessment.reads import read
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

CALM = {
    "liquidity": EconomicDirection.IMPROVING,
    "leverage": EconomicDirection.STABLE,
    "profitability": EconomicDirection.STABLE,
}
STRESSED = {
    "liquidity": EconomicDirection.DETERIORATING,
    "leverage": EconomicDirection.DETERIORATING,
    "profitability": EconomicDirection.STABLE,
}


def _items(*, health=None, model=None, narrative=None):
    items = []
    if health is not None:
        items += health_evidence(health, accession="a", form="10-K", filed=FILED)
    if model is not None:
        items += model_evidence(model)
    if narrative is not None:
        items += narrative_evidence(narrative)
    return tuple(items)


def _codes(findings):
    return {finding.code for finding in findings}


# --------------------------------------------------------------------------
# Contradictions


def test_model_elevated_with_calm_ratios_is_reported():
    items = _items(
        health=health_report(dimension_states=CALM),
        model=explanation(percentile=97.0),
        narrative=narrative_report(),
    )
    findings = detect_contradictions(items)
    assert ContradictionCode.MODEL_ELEVATED_HEALTH_QUIET in _codes(findings)
    finding = next(f for f in findings if f.code is ContradictionCode.MODEL_ELEVATED_HEALTH_QUIET)
    # Both sides are cited, and the finding adjudicates neither.
    assert finding.left and finding.right
    assert {i.evidence_id for i in items} >= set(finding.cited)


def test_no_contradiction_when_the_model_sits_in_the_middle():
    """The `UNKNOWN` band exists so the middle of the ranking does not
    manufacture disagreements."""
    findings = detect_contradictions(
        _items(
            health=health_report(dimension_states=CALM),
            model=explanation(percentile=70.0),
            narrative=narrative_report(),
        )
    )
    assert ContradictionCode.MODEL_ELEVATED_HEALTH_QUIET not in _codes(findings)


def test_severe_narrative_against_a_quiet_model_is_reported():
    findings = detect_contradictions(
        _items(
            model=explanation(percentile=10.0),
            narrative=narrative_report(
                signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),)
            ),
        )
    )
    assert ContradictionCode.NARRATIVE_SEVERE_MODEL_QUIET in _codes(findings)


def test_a_low_specificity_assertion_does_not_contradict_anything():
    """Phase 10 measured `ASSET_IMPAIRMENT` as ordinary in healthy filers, so
    'the filing mentions an impairment' must not be enough to contradict a
    model or a set of ratios."""
    items = _items(
        health=health_report(dimension_states=CALM),
        model=explanation(percentile=10.0),
        narrative=narrative_report(
            signals=(
                narrative_signal(
                    RiskSignalCode.ASSET_IMPAIRMENT,
                    Assertion.ASSERTED,
                    specificity=Specificity.LOW,
                    text="An impairment charge was recorded in the period.",
                ),
            )
        ),
    )
    assert read(items, LayerId.NARRATIVE) is not Concern.ELEVATED
    findings = _codes(detect_contradictions(items))
    assert ContradictionCode.NARRATIVE_SEVERE_MODEL_QUIET not in findings
    assert ContradictionCode.NARRATIVE_SEVERE_HEALTH_QUIET not in findings


def test_a_filing_that_asserts_and_denies_the_same_condition():
    """The SandRidge case Phase 10 found while building its corpus: the same
    10-K affirming covenant compliance and disclosing a violation."""
    findings = detect_contradictions(
        _items(
            narrative=narrative_report(
                signals=(
                    narrative_signal(
                        RiskSignalCode.COVENANT_BREACH,
                        Assertion.ASSERTED,
                        specificity=Specificity.MODERATE,
                        text="We were not in compliance with the fixed charge coverage covenant.",
                    ),
                    narrative_signal(
                        RiskSignalCode.COVENANT_BREACH,
                        Assertion.NEGATED,
                        specificity=Specificity.MODERATE,
                        text="We were in compliance with all covenants under the notes.",
                        char_start=9000,
                    ),
                )
            )
        )
    )
    finding = next(f for f in findings if f.code is ContradictionCode.NARRATIVE_SELF_CONTRADICTION)
    assert finding.left_layer is LayerId.NARRATIVE is finding.right_layer
    assert len(finding.left) == 1 and len(finding.right) == 1


def test_dimension_disagreement_needs_a_material_driver():
    """Without the materiality floor every assessment would carry five
    disagreements, because some dimension always pushes weakly the wrong way."""
    material = detect_contradictions(
        _items(
            health=health_report(dimension_states={"leverage": EconomicDirection.IMPROVING}),
            model=explanation(percentile=60.0, dimensions={"leverage": 1.0}),
        )
    )
    assert ContradictionCode.DIMENSION_DISAGREEMENT in _codes(material)

    immaterial = detect_contradictions(
        _items(
            health=health_report(dimension_states={"leverage": EconomicDirection.IMPROVING}),
            model=explanation(percentile=60.0, dimensions={"leverage": 0.01, "profitability": 1.0}),
        )
    )
    assert ContradictionCode.DIMENSION_DISAGREEMENT not in _codes(immaterial)


def test_a_high_rank_built_on_missingness_is_flagged():
    findings = detect_contradictions(
        _items(
            model=explanation(
                percentile=98.0, dimensions={"leverage": 0.2}, missingness_contribution=0.8
            )
        )
    )
    assert ContradictionCode.SCORE_NOT_EVIDENCE_BACKED in _codes(findings)


def test_silence_from_an_unread_section_is_not_silence():
    """The fail-safe NFR: 'no narrative concerns' must not be reported when a
    section was never located."""
    findings = detect_contradictions(
        _items(narrative=narrative_report(missing_sections=("item_7",)))
    )
    finding = next(f for f in findings if f.code is ContradictionCode.ABSENCE_NOT_OBSERVED)
    # The left side is legitimately empty: there is no evidence of silence,
    # only evidence that nobody listened.
    assert finding.left == ()
    assert len(finding.right) == 1


def test_a_fully_read_filing_raises_no_coverage_contradiction():
    findings = detect_contradictions(_items(narrative=narrative_report()))
    assert ContradictionCode.ABSENCE_NOT_OBSERVED not in _codes(findings)


# --------------------------------------------------------------------------
# Corroboration


def test_three_independent_layers_agreeing():
    items = _items(
        health=health_report(
            dimension_states=STRESSED,
            signals=(
                health_signal(SignalCode.LIQUIDITY_DETERIORATION, "liquidity", "current_ratio"),
            ),
        ),
        model=explanation(percentile=99.0, dimensions={"leverage": 1.0}),
        narrative=narrative_report(
            signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),)
        ),
    )
    findings = detect_corroboration(items)
    assert CorroborationCode.ALL_LAYERS_ELEVATED in _codes(findings)
    all_layers = next(f for f in findings if f.code is CorroborationCode.ALL_LAYERS_ELEVATED)
    assert len(all_layers.layers) == 3
    # Two-layer findings are kept alongside, because they cite different
    # evidence and a reader discounting one layer still needs them.
    assert CorroborationCode.MODEL_AND_NARRATIVE in _codes(findings)


def test_health_and_narrative_agree_on_one_dimension():
    findings = detect_corroboration(
        _items(
            health=health_report(dimension_states={"leverage": EconomicDirection.DETERIORATING}),
            narrative=narrative_report(
                signals=(
                    narrative_signal(
                        RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION,
                        Assertion.ASSERTED,
                        text="An event of default occurred under our credit agreement.",
                    ),
                )
            ),
        )
    )
    finding = next(f for f in findings if f.code is CorroborationCode.HEALTH_AND_NARRATIVE)
    assert finding.dimension == "leverage"


def test_only_the_leading_model_driver_corroborates():
    """With five dimensions and a model that attributes something to each,
    reporting every match would make agreement look inevitable."""
    findings = detect_corroboration(
        _items(
            health=health_report(
                dimension_states={
                    "leverage": EconomicDirection.DETERIORATING,
                    "profitability": EconomicDirection.DETERIORATING,
                }
            ),
            model=explanation(percentile=60.0, dimensions={"leverage": 0.2, "profitability": 1.0}),
        )
    )
    matches = [f for f in findings if f.code is CorroborationCode.MODEL_AND_HEALTH]
    assert [f.dimension for f in matches] == ["profitability"]


def test_a_calm_company_corroborates_nothing():
    assert (
        detect_corroboration(
            _items(
                health=health_report(dimension_states=CALM),
                model=explanation(percentile=5.0, dimensions={"leverage": -0.5}),
                narrative=narrative_report(),
            )
        )
        == ()
    )


def test_findings_are_deterministic_in_order():
    items = _items(
        health=health_report(dimension_states=STRESSED),
        model=explanation(percentile=99.0, dimensions={"leverage": 1.0}),
        narrative=narrative_report(
            signals=(narrative_signal(RiskSignalCode.GOING_CONCERN_DOUBT, Assertion.ASSERTED),)
        ),
    )
    assert detect_contradictions(items) == detect_contradictions(items)
    assert detect_corroboration(items) == detect_corroboration(items)
