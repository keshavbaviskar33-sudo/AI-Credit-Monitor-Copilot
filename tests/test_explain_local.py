"""Local explanations: provenance, caveats, and the temporal guarantee.

The tests that matter here are not about attribution arithmetic -- that is
`test_explain_adapters.py` -- but about whether an explanation is *safe to put
in front of an analyst*: does it point at the right filing, does it admit when
it cannot, and can it ever cite evidence that did not exist at the prediction
date?
"""

from __future__ import annotations

from datetime import date

import numpy as np

from credit_risk_copilot.explain.adapters import AttributionResult
from credit_risk_copilot.explain.local import explain_observation
from credit_risk_copilot.explain.schema import CaveatCode
from credit_risk_copilot.financials.models import (
    CanonicalFact,
    Confidence,
    FactStatus,
    Origin,
    Period,
    PeriodType,
    Provenance,
    SourceType,
    StatementType,
)
from credit_risk_copilot.modeling.contract import Observation, ObservationKey, Outcome

_PERIOD = Period(label="FY2018", fiscal_year=2018, period_type=PeriodType.INSTANT, end="2018-12-31")


def _fact(
    concept: str,
    value: float,
    *,
    accession: str = "0000000000-19-000001",
    filed: str = "2019-03-01",
    origin: Origin = Origin.REPORTED,
    confidence: Confidence = Confidence.HIGH,
) -> CanonicalFact:
    return CanonicalFact(
        concept=concept,
        statement=StatementType.BALANCE_SHEET,
        period=_PERIOD,
        value=value,
        currency="USD",
        status=FactStatus.FOUND,
        confidence=confidence,
        origin=origin,
        provenance=(
            Provenance(
                source_type=SourceType.XBRL,
                extraction_method="xbrl-companyfacts",
                concept="Assets",
                namespace="us-gaap",
                accession=accession,
                form="10-K",
                filed=filed,
            ),
        ),
    )


def _observation(**feature_overrides: float | None) -> Observation:
    features: dict[str, float | None] = {"periods_available": 5.0}
    features.update(feature_overrides)
    return Observation(
        key=ObservationKey(
            cik=1,
            company="Test Co",
            prediction_date=date(2019, 3, 1),
            information_cutoff=date(2019, 3, 1),
            source_accession="0000000000-19-000001",
            source_form="10-K",
            fiscal_period_label="FY2018",
        ),
        features=features,
        outcome=Outcome(label=0, horizon_end=date(2020, 3, 1)),
    )


def _attribution(
    names: tuple[str, ...], contributions: list[float], values: list[float]
) -> AttributionResult:
    return AttributionResult(
        method="linear_contribution",
        feature_names=names,
        contributions=np.array([contributions], dtype=float),
        baseline=-4.0,
        values=np.array([values], dtype=float),
    )


def _explain(
    names: tuple[str, ...],
    contributions: list[float],
    values: list[float],
    facts: dict[tuple[str, str], CanonicalFact],
    *,
    observation: Observation | None = None,
    calibration_slope: float | None = 0.33,
    cohort_confounded: bool = True,
    base_rate_is_sampling_design: bool = True,
):  # type: ignore[no-untyped-def]
    attribution = _attribution(names, contributions, values)
    return explain_observation(
        observation=observation or _observation(),
        attribution=attribution,
        row=0,
        score=0.42,
        link_score=-4.0 + sum(contributions),
        facts=facts,
        model_name="test_model",
        model_family="logistic",
        calibration_slope=calibration_slope,
        cohort_confounded=cohort_confounded,
        base_rate_is_sampling_design=base_rate_is_sampling_design,
    )


class TestProvenanceChain:
    def test_a_ratio_contribution_cites_the_filing_behind_each_input(self) -> None:
        """The chain the product requires: contribution -> concepts -> facts
        -> accession -> receipt date."""
        facts = {
            ("total_debt", "FY2018"): _fact("total_debt", 4_120_000_000),
            ("total_assets", "FY2018"): _fact("total_assets", 6_540_000_000),
        }

        explanation = _explain(("ratio_debt_to_assets",), [0.21], [0.63], facts)

        contribution = explanation.contributions[0]
        assert contribution.dimension == "leverage"
        assert {link.concept for link in contribution.evidence} == {"total_debt", "total_assets"}
        assert all(link.accession == "0000000000-19-000001" for link in contribution.evidence)
        assert all(link.filed == "2019-03-01" for link in contribution.evidence)

    def test_evidence_carries_the_value_and_its_phase5_status(self) -> None:
        facts = {("total_assets", "FY2018"): _fact("total_assets", 6_540_000_000)}

        explanation = _explain(("log_total_assets",), [0.05], [22.6], facts)

        link = explanation.contributions[0].evidence[0]
        assert link.value == 6_540_000_000
        assert link.status == "found"
        assert link.origin == "reported"
        assert link.xbrl_concept == "Assets"

    def test_an_aggregate_admits_it_has_no_single_filing(self) -> None:
        """Rather than inventing one. The caveat is the product of this."""
        explanation = _explain(("n_deteriorating_ratios",), [0.4], [6.0], {})

        assert explanation.contributions[0].evidence == ()
        assert explanation.has_caveat(CaveatCode.PROVENANCE_INCOMPLETE)

    def test_a_derived_input_is_flagged(self) -> None:
        facts = {
            ("total_debt", "FY2018"): _fact("total_debt", 4e9, origin=Origin.DERIVED),
            ("total_assets", "FY2018"): _fact("total_assets", 6e9),
        }

        explanation = _explain(("ratio_debt_to_assets",), [0.21], [0.63], facts)

        assert explanation.has_caveat(CaveatCode.DERIVED_INPUT)

    def test_a_low_confidence_input_is_flagged(self) -> None:
        facts = {
            ("total_debt", "FY2018"): _fact("total_debt", 4e9, confidence=Confidence.LOW),
            ("total_assets", "FY2018"): _fact("total_assets", 6e9),
        }

        explanation = _explain(("ratio_debt_to_assets",), [0.21], [0.63], facts)

        assert explanation.has_caveat(CaveatCode.LOW_CONFIDENCE_INPUT)


class TestTemporalGuarantee:
    def test_an_explanation_never_cites_a_filing_from_after_the_prediction_date(self) -> None:
        """The Phase 8 point-in-time contract has to survive into Phase 9: an
        explanation that quotes a later filing would be a leak an analyst
        could not see."""
        facts = {
            ("total_debt", "FY2018"): _fact("total_debt", 4e9),
            ("total_assets", "FY2018"): _fact("total_assets", 6e9),
        }

        explanation = _explain(("ratio_debt_to_assets",), [0.21], [0.63], facts)

        cutoff = explanation.prediction_date.isoformat()
        for contribution in explanation.contributions:
            for link in contribution.evidence:
                assert link.filed is not None
                assert link.filed <= cutoff


class TestMissingness:
    def test_an_indicator_is_marked_and_carries_no_evidence(self) -> None:
        explanation = _explain(("ratio_roa__missing",), [0.5], [1.0], {})

        contribution = explanation.contributions[0]
        assert contribution.is_missingness_indicator
        assert contribution.source_kind == "missingness"
        assert contribution.evidence == ()

    def test_missingness_share_is_reported(self) -> None:
        explanation = _explain(
            ("ratio_roa__missing", "ratio_debt_to_assets"), [0.6, 0.4], [1.0, 0.5], {}
        )

        assert explanation.missingness_share == 0.6

    def test_a_missingness_dominated_prediction_is_flagged(self) -> None:
        """§13's headline concern, surfaced per prediction rather than only in
        a report."""
        explanation = _explain(
            ("ratio_roa__missing", "ratio_debt_to_assets"), [0.9, 0.1], [1.0, 0.5], {}
        )

        assert explanation.has_caveat(CaveatCode.MISSINGNESS_DRIVEN)

    def test_a_financially_driven_prediction_is_not_flagged(self) -> None:
        explanation = _explain(
            ("ratio_roa__missing", "ratio_debt_to_assets"), [0.1, 0.9], [1.0, 0.5], {}
        )

        assert not explanation.has_caveat(CaveatCode.MISSINGNESS_DRIVEN)


class TestCaveats:
    def test_poor_calibration_travels_with_every_prediction(self) -> None:
        explanation = _explain(("ratio_debt_to_assets",), [0.2], [0.6], {}, calibration_slope=0.33)

        assert explanation.has_caveat(CaveatCode.NOT_CALIBRATED)

    def test_a_calibrated_model_is_not_flagged(self) -> None:
        explanation = _explain(("ratio_debt_to_assets",), [0.2], [0.6], {}, calibration_slope=0.98)

        assert not explanation.has_caveat(CaveatCode.NOT_CALIBRATED)

    def test_an_acceptable_slope_does_not_remove_the_base_rate_caveat(self) -> None:
        """The defect D-034 exposed. D-033 gave two independent reasons the
        score is a ranking -- the calibration slope, and a base rate set by the
        sampling design -- but only the first was implemented, and it was
        implemented as the gate on both. Promoting the gradient-boosting model
        (slope 0.81, inside the acceptable band) would therefore have silently
        dropped the second reason along with the first."""
        explanation = _explain(("ratio_debt_to_assets",), [0.2], [0.6], {}, calibration_slope=0.81)

        assert not explanation.has_caveat(CaveatCode.NOT_CALIBRATED)
        assert explanation.has_caveat(CaveatCode.BASE_RATE_NOT_PORTFOLIO)

    def test_the_base_rate_caveat_can_be_switched_off_for_a_real_portfolio(self) -> None:
        """It is a fact about this corpus, not a law. A model retrained on a
        population whose base rate means something should not carry it."""
        explanation = _explain(
            ("ratio_debt_to_assets",), [0.2], [0.6], {}, base_rate_is_sampling_design=False
        )

        assert not explanation.has_caveat(CaveatCode.BASE_RATE_NOT_PORTFOLIO)

    def test_cohort_confounding_travels_with_every_prediction(self) -> None:
        explanation = _explain(("ratio_debt_to_assets",), [0.2], [0.6], {})

        assert explanation.has_caveat(CaveatCode.COHORT_CONFOUNDED)

    def test_thin_history_is_flagged(self) -> None:
        explanation = _explain(
            ("ratio_debt_to_assets",),
            [0.2],
            [0.6],
            {},
            observation=_observation(periods_available=2.0),
        )

        assert explanation.has_caveat(CaveatCode.LIMITED_HISTORY)

    def test_caveats_are_deduplicated_by_code_and_subject(self) -> None:
        """Two ratios sharing one derived input is one caveat, not two."""
        facts = {
            ("total_debt", "FY2018"): _fact("total_debt", 4e9, origin=Origin.DERIVED),
            ("total_assets", "FY2018"): _fact("total_assets", 6e9),
            ("total_equity", "FY2018"): _fact("total_equity", 2e9),
        }

        explanation = _explain(
            ("ratio_debt_to_assets", "ratio_debt_to_equity"), [0.2, 0.2], [0.6, 2.0], facts
        )

        derived = [c for c in explanation.caveats if c.code is CaveatCode.DERIVED_INPUT]
        assert len(derived) == 1
        assert derived[0].subject == "total_debt"


class TestRollup:
    def test_contributions_roll_up_to_dimensions_summing_to_one(self) -> None:
        explanation = _explain(
            ("ratio_debt_to_assets", "ratio_current_ratio", "log_total_assets"),
            [0.4, -0.2, 0.1],
            [0.6, 1.2, 22.0],
            {},
        )

        groups = {g.group: g for g in explanation.by_dimension}
        assert set(groups) == {"leverage", "liquidity", "size"}
        assert sum(g.share_of_absolute for g in explanation.by_dimension) == 1.0
        assert groups["leverage"].contribution == 0.4

    def test_contributions_are_ordered_by_magnitude(self) -> None:
        explanation = _explain(
            ("ratio_debt_to_assets", "ratio_current_ratio"), [0.1, -0.9], [0.6, 1.2], {}
        )

        assert explanation.contributions[0].feature == "ratio_current_ratio"

    def test_top_contributors_split_by_direction(self) -> None:
        explanation = _explain(
            ("ratio_debt_to_assets", "ratio_current_ratio"), [0.4, -0.9], [0.6, 1.2], {}
        )

        assert explanation.top_contributors(raising=True)[0].feature == "ratio_debt_to_assets"
        assert explanation.top_contributors(raising=False)[0].feature == "ratio_current_ratio"

    def test_the_explanation_is_deterministic(self) -> None:
        facts = {("total_assets", "FY2018"): _fact("total_assets", 6e9)}
        args = (("log_total_assets",), [0.05], [22.6], facts)

        assert _explain(*args).model_dump() == _explain(*args).model_dump()
