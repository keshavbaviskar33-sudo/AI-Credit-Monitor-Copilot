"""Explicit contradiction rules (FR-15).

Seven rules, each a named condition over cited evidence. There is no
similarity metric, no learned disagreement detector and no threshold on a
distance between layers, because a contradiction an analyst cannot check is
worse than no contradiction at all -- it is a second opaque model sitting on
top of the first.

## What a rule is allowed to conclude

Nothing. Every finding names both sides and stops. This is not modesty: in
each of these cases the information needed to adjudicate is genuinely absent
from the assessment. When the model ranks a company high and the ratios are
calm, the honest statement is that they disagree -- deciding which is right
requires knowing whether the model has found something the ratio catalog does
not cover, or is reacting to a filing's missing tags, and Phase 9 measured
that both happen. `resolution_hint` therefore names the next thing to look at,
which is a check, not an answer.

## Why these seven

Each one earns its place by being a disagreement that changes what an analyst
does next, and by being reachable from evidence this project actually has.
Rules that would have been guesses -- "the tone of Item 7 disagrees with the
margin trend" -- are absent, because nothing here measures tone.
"""

from __future__ import annotations

from collections.abc import Sequence

from credit_risk_copilot.assessment import reads
from credit_risk_copilot.assessment.evidence import high_specificity_codes
from credit_risk_copilot.assessment.models import (
    Concern,
    ContradictionCode,
    ContradictionFinding,
    EvidenceItem,
    EvidenceKind,
    LayerId,
)
from credit_risk_copilot.nlp.models import Assertion

#: A model driver below this share of total absolute attribution is not
#: material enough to contradict anything. Without a floor, every assessment
#: would carry five dimension disagreements, because some dimension always
#: pushes weakly against the deterministic read and a finding that fires
#: always is a finding nobody reads.
MATERIAL_DRIVER_SHARE = 0.10

#: Share of attribution about the filing rather than the company, above which a
#: high ranking is not a financial finding. A third is the disclosed line: at
#: that point the largest single story about a prediction is the filing's
#: completeness.
#:
#: **Measured, it never fires for the primary model, and that is the result.**
#: On the Phase 11 corpus the gradient-boosting model's artefact share has a
#: median of 0.004 and a 99th percentile of 0.029, against the 44% Phase 9
#: measured on the logistic model it replaced -- D-034's promotion removed the
#: missingness pathology rather than inheriting it. The rule is kept as a
#: standing guard, since it would fire on the retained comparator and on any
#: future model with indicator features, and since a check that currently
#: passes is not the same as a check nobody wrote.
FILING_ARTEFACT_SHARE_LIMIT = 0.35


def _model_elevated_health_quiet(items: Sequence[EvidenceItem]) -> list[ContradictionFinding]:
    model = reads.read(items, LayerId.PREDICTIVE_MODEL)
    health = reads.read(items, LayerId.FINANCIAL_HEALTH)
    if model is not Concern.ELEVATED or health is not Concern.QUIET:
        return []
    return [
        ContradictionFinding(
            code=ContradictionCode.MODEL_ELEVATED_HEALTH_QUIET,
            dimension=None,
            left_layer=LayerId.PREDICTIVE_MODEL,
            right_layer=LayerId.FINANCIAL_HEALTH,
            left=reads.cited(items, LayerId.PREDICTIVE_MODEL, Concern.ELEVATED),
            right=reads.cited(items, LayerId.FINANCIAL_HEALTH, Concern.QUIET),
            explanation=(
                "The model places this company high in the monitored ranking while no"
                " health dimension is deteriorating and no early-warning signal fired."
            ),
            resolution_hint=(
                "Check the model's dimension attribution and its caveats: a high rank with"
                " calm ratios is driven either by a pattern the 13-ratio catalog does not"
                " cover, or by missing tags in the filing."
            ),
        )
    ]


def _narrative_severe_vs_layer(
    items: Sequence[EvidenceItem],
    *,
    layer: LayerId,
    code: ContradictionCode,
    explanation: str,
    resolution_hint: str,
) -> list[ContradictionFinding]:
    severe = high_specificity_codes(items)
    if not severe:
        return []
    if reads.read(items, layer) is not Concern.QUIET:
        return []
    return [
        ContradictionFinding(
            code=code,
            dimension=None,
            left_layer=LayerId.NARRATIVE,
            right_layer=layer,
            left=tuple(item.evidence_id for item in severe),
            right=reads.cited(items, layer, Concern.QUIET),
            explanation=explanation.format(
                codes=", ".join(sorted({str(i.detail.get("code")) for i in severe}))
            ),
            resolution_hint=resolution_hint,
        )
    ]


def _narrative_self_contradiction(items: Sequence[EvidenceItem]) -> list[ContradictionFinding]:
    """The same filing both asserting and denying the same condition.

    The one rule here whose two sides come from a single layer and a single
    document, which is what makes it the strongest: two verbatim quotes from
    one 10-K that cannot both be read plainly need no cross-layer inference at
    all. Phase 10 found a real instance while building the corpus -- SandRidge's
    FY2015 filing affirms compliance with its note covenants two months before
    its petition while disclosing a covenant violation elsewhere in the same
    document -- and that case is what this rule exists to surface rather than
    average away.
    """
    asserted: dict[str, EvidenceItem] = {}
    negated: dict[str, EvidenceItem] = {}
    for item in items:
        if item.kind is not EvidenceKind.NARRATIVE_SIGNAL:
            continue
        code = str(item.detail.get("code"))
        if item.detail.get("assertion") == Assertion.ASSERTED.value:
            asserted[code] = item
        elif item.detail.get("assertion") == Assertion.NEGATED.value:
            negated[code] = item

    findings = []
    for code in sorted(set(asserted) & set(negated)):
        findings.append(
            ContradictionFinding(
                code=ContradictionCode.NARRATIVE_SELF_CONTRADICTION,
                dimension=asserted[code].dimension,
                left_layer=LayerId.NARRATIVE,
                right_layer=LayerId.NARRATIVE,
                left=(asserted[code].evidence_id,),
                right=(negated[code].evidence_id,),
                explanation=(
                    f"This filing both states and denies {code.replace('_', ' ')}."
                    " Both quotes are verbatim from the same document."
                ),
                resolution_hint=(
                    "Read both quotes in context: the usual cause is that the two statements"
                    " cover different instruments or different dates, and the difference is"
                    " the fact worth reporting."
                ),
            )
        )
    return findings


def _dimension_disagreement(items: Sequence[EvidenceItem]) -> list[ContradictionFinding]:
    findings = []
    drivers = [
        item
        for item in items
        if item.kind is EvidenceKind.MODEL_DRIVER
        and item.dimension is not None
        and float(item.detail.get("share_of_absolute") or 0.0) >= MATERIAL_DRIVER_SHARE
    ]
    for driver in sorted(drivers, key=lambda i: i.dimension or ""):
        dimension = driver.dimension
        assert dimension is not None
        health = reads.read(items, LayerId.FINANCIAL_HEALTH, dimension=dimension)
        if health is Concern.UNKNOWN or driver.concern is Concern.UNKNOWN:
            continue
        if driver.concern is health:
            continue
        pushing = "raises" if driver.concern is Concern.ELEVATED else "lowers"
        reading = "deteriorating" if health is Concern.ELEVATED else "not deteriorating"
        findings.append(
            ContradictionFinding(
                code=ContradictionCode.DIMENSION_DISAGREEMENT,
                dimension=dimension,
                left_layer=LayerId.PREDICTIVE_MODEL,
                right_layer=LayerId.FINANCIAL_HEALTH,
                left=(driver.evidence_id,),
                right=reads.cited(items, LayerId.FINANCIAL_HEALTH, health, dimension=dimension),
                explanation=(
                    f"On {dimension}, the model's attribution {pushing} the score while the"
                    f" deterministic trend layer reads the dimension as {reading}."
                ),
                resolution_hint=(
                    f"Compare the model's {dimension} features against the ratio trends for the"
                    " same dimension: the model sees levels as well as directions, so the two"
                    " can legitimately differ when a ratio is stable at a weak level."
                ),
            )
        )
    return findings


#: The attribution groups that describe the *filing* rather than the company:
#: missingness indicators, and the Phase 8 `quality` family (ratio coverage,
#: fact coverage, derived-input share, period count).
FILING_ARTEFACT_GROUPS = frozenset({"missingness", "data_quality"})


def artefact_share(items: Sequence[EvidenceItem]) -> float:
    """Share of attribution that is about the filing, not about the company.

    Written against the attribution *groups* rather than against
    `ModelExplanation.missingness_share`, because the primary model has no
    missingness indicators at all. D-034 promoted a gradient-boosting model,
    which handles absent values natively instead of through `__missing`
    columns, so `missingness_share` is structurally zero for it and a rule
    reading that field could only ever fire on the retired logistic
    comparator. The `data_quality` group carries the same meaning for the model
    that actually ships.
    """
    return sum(
        float(item.detail.get("share_of_absolute") or 0.0)
        for item in items
        if item.kind is EvidenceKind.MODEL_DRIVER
        and str(item.detail.get("group")) in FILING_ARTEFACT_GROUPS
    )


def _score_not_evidence_backed(items: Sequence[EvidenceItem]) -> list[ContradictionFinding]:
    scores = [item for item in items if item.kind is EvidenceKind.MODEL_SCORE]
    findings = []
    share = artefact_share(items)
    for score in scores:
        if score.concern is not Concern.ELEVATED:
            continue
        if share < FILING_ARTEFACT_SHARE_LIMIT:
            continue
        caveats = tuple(
            item.evidence_id
            for item in items
            if item.kind is EvidenceKind.MODEL_CAVEAT
            and str(item.detail.get("code")) in ("missingness_driven", "provenance_incomplete")
        ) + tuple(
            item.evidence_id
            for item in items
            if item.kind is EvidenceKind.MODEL_DRIVER
            and str(item.detail.get("group")) in FILING_ARTEFACT_GROUPS
        )
        findings.append(
            ContradictionFinding(
                code=ContradictionCode.SCORE_NOT_EVIDENCE_BACKED,
                dimension=None,
                left_layer=LayerId.PREDICTIVE_MODEL,
                right_layer=LayerId.DATA_QUALITY,
                left=(score.evidence_id,),
                right=caveats,
                explanation=(
                    f"{share:.0%} of this prediction's attribution comes from how complete the"
                    " filing is -- missing values and coverage features -- rather than from"
                    " what its figures say."
                ),
                resolution_hint=(
                    "Check which concepts are missing for this filing before treating the rank"
                    " as a financial finding; a thin XBRL tagging year produces this without"
                    " any change in the company's condition."
                ),
            )
        )
    return findings


def _absence_not_observed(items: Sequence[EvidenceItem]) -> list[ContradictionFinding]:
    """A quiet narrative layer that never read part of the filing.

    The `left` side is empty when the narrative layer found nothing at all,
    which is the case this rule most needs to cover: there is no evidence of
    silence, only evidence that nobody listened, and the finding says so.
    """
    gaps = tuple(item.evidence_id for item in items if item.kind is EvidenceKind.NARRATIVE_COVERAGE)
    if not gaps:
        return []
    if reads.read(items, LayerId.NARRATIVE) is Concern.ELEVATED:
        return []
    found = tuple(item.evidence_id for item in items if item.kind is EvidenceKind.NARRATIVE_SIGNAL)
    return [
        ContradictionFinding(
            code=ContradictionCode.ABSENCE_NOT_OBSERVED,
            dimension=None,
            left_layer=LayerId.NARRATIVE,
            right_layer=LayerId.NARRATIVE,
            left=found,
            right=gaps,
            explanation=(
                f"{len(gaps)} narrative section(s) could not be located in this filing, so"
                " the absence of narrative risk signals is partly an absence of reading."
            ),
            resolution_hint=(
                "Confirm the missing sections against the filing itself before reporting"
                " 'no narrative concerns'; section detection fails on some older filings."
            ),
        )
    ]


def detect_contradictions(items: Sequence[EvidenceItem]) -> tuple[ContradictionFinding, ...]:
    """Every rule, in a deterministic order.

    Ordering is by rule, then by dimension within a rule -- not by any notion
    of severity, which would be the composite score this layer refuses,
    smuggled in as a sort key.
    """
    findings: list[ContradictionFinding] = []
    findings += _model_elevated_health_quiet(items)
    findings += _narrative_severe_vs_layer(
        items,
        layer=LayerId.PREDICTIVE_MODEL,
        code=ContradictionCode.NARRATIVE_SEVERE_MODEL_QUIET,
        explanation=(
            "The filer states {codes} about itself, and the model places it in the lower"
            " half of the monitored ranking."
        ),
        # The first draft of this hint said to treat the model as the weaker
        # side, on the reasoning that the filer's own verbatim words outrank a
        # fitted score. The measurement reversed it: on the Phase 11 corpus
        # this rule fired on 11 comparison filings and 1 pre-bankruptcy filing
        # (lift 0.09), so the companies it flags are overwhelmingly ones that
        # did *not* fail within the year. The hint now says what was measured
        # instead of what was assumed.
        resolution_hint=(
            "Check whether the statement is about a resolved or historical condition before"
            " acting on it. Measured on the Phase 11 corpus, this disagreement occurred far"
            " more often in filings that were not followed by bankruptcy than in those that"
            " were, so the filer's severe language is not on its own the stronger side here."
        ),
    )
    findings += _narrative_severe_vs_layer(
        items,
        layer=LayerId.FINANCIAL_HEALTH,
        code=ContradictionCode.NARRATIVE_SEVERE_HEALTH_QUIET,
        explanation=(
            "The filer states {codes} about itself, and no health dimension is deteriorating."
        ),
        resolution_hint=(
            "Narrative distress can precede the accounting: check whether the statement"
            " concerns events after the balance-sheet date."
        ),
    )
    findings += _narrative_self_contradiction(items)
    findings += _dimension_disagreement(items)
    findings += _score_not_evidence_backed(items)
    findings += _absence_not_observed(items)
    return tuple(findings)
