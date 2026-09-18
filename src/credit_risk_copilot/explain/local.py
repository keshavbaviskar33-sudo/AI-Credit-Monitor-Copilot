"""Turning attributions into explanations an analyst can challenge.

An attribution value on its own -- `ratio_debt_to_assets: +0.21` -- is not an
explanation in a credit-monitoring product. It becomes one when the reader can
follow it down:

    +0.21 on ratio_debt_to_assets
        -> leverage dimension
        -> debt_to_assets = 0.63 for FY2019
        -> total_debt 4,120M / total_assets 6,540M
        -> total_debt DERIVED from short_term_debt + long_term_debt
        -> accession 0000950170-20-000123, 10-K, received 2020-03-12

Every hop in that chain already exists in the project -- `groups.py` maps a
feature to concepts, Phase 6 maps a ratio to its inputs, Phase 5's
`CanonicalFact.provenance` carries the accession and the filing date. This
module is what walks it.

## The rule when the chain breaks

It does break, in three legitimate ways: an aggregate feature (e.g.
`n_deteriorating_ratios`) spans too many facts for a single link to mean
anything; a missingness indicator is *about* the absence of a fact, so there is
no fact to point at; and a derived fact's provenance points at its inputs
rather than at itself. In all three the explanation is emitted with the
evidence it has and a `PROVENANCE_INCOMPLETE` caveat -- never silently, and
never by dropping the contribution. "We cannot show you where this came from"
is information the analyst needs, not noise to suppress.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from credit_risk_copilot.explain.adapters import AttributionResult
from credit_risk_copilot.explain.groups import (
    base_feature,
    dimension_of,
    family_of,
    group_of,
    is_missingness_indicator,
    ratio_inputs,
)
from credit_risk_copilot.explain.schema import (
    Caveat,
    CaveatCode,
    DimensionAttribution,
    EvidenceLink,
    FeatureContribution,
    ModelExplanation,
)
from credit_risk_copilot.financials.models import CanonicalFact, Confidence, Origin
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.features import SPECS_BY_NAME

#: Share of a prediction's absolute contribution that must come from
#: missingness indicators before the explanation is flagged. Set at a third
#: because below that missingness is a minor term among financial drivers, and
#: above it a reader who took the top contributors at face value would be
#: substantially misreading what moved the score.
MISSINGNESS_CAVEAT_THRESHOLD = 1 / 3

#: How many features to keep per dimension in the rolled-up view.
TOP_FEATURES_PER_GROUP = 4

#: Tolerance on `baseline + sum(contributions) == link score`. Anything larger
#: means the attribution does not reconstruct the model and the explanation
#: should not be trusted.
RECONSTRUCTION_TOLERANCE = 1e-6


def _evidence_for(
    feature: str, facts: Mapping[tuple[str, str], CanonicalFact], period_label: str
) -> tuple[EvidenceLink, ...]:
    """The canonical facts a feature was computed from, with their filings."""
    links: list[EvidenceLink] = []
    for concept in ratio_inputs(feature):
        fact = facts.get((concept, period_label))
        if fact is None:
            continue
        provenance = fact.provenance[0] if fact.provenance else None
        links.append(
            EvidenceLink(
                concept=concept,
                period_label=period_label,
                value=fact.effective_value,
                status=fact.status.value,
                origin=fact.origin.value,
                confidence=fact.confidence.value,
                xbrl_concept=provenance.concept if provenance else None,
                accession=provenance.accession if provenance else None,
                form=provenance.form if provenance else None,
                filed=provenance.filed if provenance else None,
            )
        )
    return tuple(links)


def _contributions(
    attribution: AttributionResult,
    row: int,
    observation: Observation,
    facts: Mapping[tuple[str, str], CanonicalFact],
) -> tuple[FeatureContribution, ...]:
    period = observation.key.fiscal_period_label
    built: list[FeatureContribution] = []
    for column, feature in enumerate(attribution.feature_names):
        contribution = float(attribution.contributions[row, column])
        raw_value = float(attribution.values[row, column])
        missing = is_missingness_indicator(feature)
        spec = SPECS_BY_NAME.get(base_feature(feature))
        built.append(
            FeatureContribution(
                feature=feature,
                family=family_of(feature),
                dimension=dimension_of(feature),
                value=None if np.isnan(raw_value) else raw_value,
                is_missingness_indicator=missing,
                contribution=contribution,
                raises_risk=contribution > 0,
                source_kind=(
                    "missingness" if missing else (spec.source_kind if spec else "unknown")
                ),
                source_id=spec.source_id if spec else None,
                evidence=() if missing else _evidence_for(feature, facts, period),
            )
        )
    return tuple(sorted(built, key=lambda c: -abs(c.contribution)))


def _by_dimension(
    contributions: Sequence[FeatureContribution], *, axis: str = "dimension"
) -> tuple[DimensionAttribution, ...]:
    total_absolute = sum(abs(c.contribution) for c in contributions) or 1.0
    grouped: dict[str, list[FeatureContribution]] = {}
    for contribution in contributions:
        grouped.setdefault(group_of(contribution.feature, axis=axis), []).append(contribution)

    rolled = [
        DimensionAttribution(
            group=group,
            contribution=sum(c.contribution for c in members),
            share_of_absolute=sum(abs(c.contribution) for c in members) / total_absolute,
            feature_count=len(members),
            top_features=tuple(
                sorted(members, key=lambda c: -abs(c.contribution))[:TOP_FEATURES_PER_GROUP]
            ),
        )
        for group, members in grouped.items()
    ]
    return tuple(sorted(rolled, key=lambda g: -g.share_of_absolute))


def _caveats(
    explanation_contributions: Sequence[FeatureContribution],
    observation: Observation,
    *,
    calibration_slope: float | None,
    cohort_confounded: bool,
    base_rate_is_sampling_design: bool,
    reconstruction_error: float,
) -> tuple[Caveat, ...]:
    """Every specific reason this explanation should not be read at face value.

    Assembled from the explanation itself plus what the *model's* own
    evaluation established, so a caveat that applies to every prediction from
    this model (calibration, cohort construction) travels with each one rather
    than living only in a document nobody reads alongside the number.
    """
    caveats: list[Caveat] = []
    total = sum(abs(c.contribution) for c in explanation_contributions) or 1.0
    missing_share = (
        sum(abs(c.contribution) for c in explanation_contributions if c.is_missingness_indicator)
        / total
    )

    if missing_share >= MISSINGNESS_CAVEAT_THRESHOLD:
        caveats.append(
            Caveat(
                code=CaveatCode.MISSINGNESS_DRIVEN,
                message=(
                    f"{missing_share:.0%} of this prediction's absolute contribution comes from "
                    "missingness indicators -- the model is reacting substantially to which "
                    "figures the filing did not contain, not to their values."
                ),
            )
        )

    if calibration_slope is not None and not 0.8 <= calibration_slope <= 1.25:
        caveats.append(
            Caveat(
                code=CaveatCode.NOT_CALIBRATED,
                message=(
                    f"The model's calibration slope is {calibration_slope:.2f} (1.0 would be "
                    "calibrated). Read the output as a position in a ranking, never as a "
                    "probability of bankruptcy."
                ),
            )
        )

    # Unconditional, and deliberately *not* folded into `NOT_CALIBRATED`.
    # D-033 gave two independent reasons the score is a ranking: the slope, and
    # a training base rate that is a property of the sampling design rather
    # than of any portfolio. Only the first is a function of the slope. When
    # D-034 promoted the gradient-boosting model -- whose slope is 0.81, inside
    # the [0.8, 1.25] band -- the slope-conditional caveat stopped firing and
    # the second reason went with it, which is exactly the silent loss of a
    # caveat that D-029 attaches caveats to every prediction to prevent.
    if base_rate_is_sampling_design:
        caveats.append(
            Caveat(
                code=CaveatCode.BASE_RATE_NOT_PORTFOLIO,
                message=(
                    "The training base rate is set by how the corpus was sampled, not by any "
                    "real portfolio, so the score's level carries no portfolio meaning even "
                    "where its calibration slope looks acceptable. Compare companies by rank."
                ),
            )
        )

    if cohort_confounded:
        caveats.append(
            Caveat(
                code=CaveatCode.COHORT_CONFOUNDED,
                message=(
                    "This model was trained against a comparison cohort selected for having "
                    "survived, so part of its discrimination reflects sample construction "
                    "rather than credit risk."
                ),
            )
        )

    if reconstruction_error > RECONSTRUCTION_TOLERANCE:
        caveats.append(
            Caveat(
                code=CaveatCode.UNSTABLE_ATTRIBUTION,
                message=(
                    f"Contributions reconstruct the model's own score to within "
                    f"{reconstruction_error:.2e}, above the {RECONSTRUCTION_TOLERANCE:.0e} "
                    "tolerance; the decomposition is approximate."
                ),
            )
        )

    top = [c for c in explanation_contributions if not c.is_missingness_indicator][:8]
    if any(not c.evidence for c in top):
        untraced = [c.feature for c in top if not c.evidence]
        caveats.append(
            Caveat(
                code=CaveatCode.PROVENANCE_INCOMPLETE,
                message=(
                    "These leading contributors are aggregates or derived measures with no "
                    f"single filing to point at: {', '.join(untraced)}."
                ),
                subject=untraced[0],
            )
        )

    for contribution in top:
        for link in contribution.evidence:
            if link.origin == Origin.DERIVED.value:
                caveats.append(
                    Caveat(
                        code=CaveatCode.DERIVED_INPUT,
                        message=(
                            f"{link.concept} for {link.period_label} was derived rather than "
                            "reported directly by the filer."
                        ),
                        subject=link.concept,
                    )
                )
            if link.confidence == Confidence.LOW.value:
                caveats.append(
                    Caveat(
                        code=CaveatCode.LOW_CONFIDENCE_INPUT,
                        message=(
                            f"{link.concept} for {link.period_label} resolved with low confidence."
                        ),
                        subject=link.concept,
                    )
                )

    periods = observation.features.get("periods_available")
    if periods is not None and periods < 3:
        caveats.append(
            Caveat(
                code=CaveatCode.LIMITED_HISTORY,
                message=(
                    f"Only {periods:.0f} fiscal period(s) of history back this observation, so "
                    "trend contributions rest on very little."
                ),
            )
        )

    # De-duplicate on (code, subject): one derived input mentioned by three
    # ratios is one caveat, not three.
    seen: set[tuple[str, str | None]] = set()
    unique: list[Caveat] = []
    for caveat in caveats:
        key = (caveat.code.value, caveat.subject)
        if key not in seen:
            seen.add(key)
            unique.append(caveat)
    return tuple(unique)


def explain_observation(
    *,
    observation: Observation,
    attribution: AttributionResult,
    row: int,
    score: float,
    link_score: float,
    facts: Mapping[tuple[str, str], CanonicalFact],
    model_name: str,
    model_family: str,
    calibration_slope: float | None = None,
    cohort_confounded: bool = True,
    base_rate_is_sampling_design: bool = True,
    score_percentile: float | None = None,
) -> ModelExplanation:
    """Build one observation's explanation, with its provenance and caveats.

    `facts` is the `CompanyFinancials.as_of(cutoff)` view the observation was
    built from -- the same object, so evidence links cannot drift from the
    values the features were computed on. `cohort_confounded` and
    `base_rate_is_sampling_design` both default to `True` because on the Phase
    8 corpus both are true, and a caveat that has to be remembered is a caveat
    that will be forgotten.
    """
    contributions = _contributions(attribution, row, observation, facts)
    reconstruction_error = abs(
        attribution.baseline + float(attribution.contributions[row].sum()) - link_score
    )
    return ModelExplanation(
        cik=observation.key.cik,
        company=observation.key.company,
        prediction_date=observation.key.prediction_date,
        fiscal_period_label=observation.key.fiscal_period_label,
        source_accession=observation.key.source_accession,
        model_name=model_name,
        model_family=model_family,
        attribution_method=attribution.method,
        score=score,
        baseline=attribution.baseline,
        score_percentile=score_percentile,
        contributions=contributions,
        by_dimension=_by_dimension(contributions),
        caveats=_caveats(
            contributions,
            observation,
            calibration_slope=calibration_slope,
            cohort_confounded=cohort_confounded,
            base_rate_is_sampling_design=base_rate_is_sampling_design,
            reconstruction_error=reconstruction_error,
        ),
    )
