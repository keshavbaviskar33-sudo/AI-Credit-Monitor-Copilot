"""Turning each layer's output into addressable evidence.

One registrar per layer, each pure: a layer's report goes in, a tuple of
`EvidenceItem` comes out, and nothing is fetched, inferred or scored on the
way. The rules in `contradictions.py` and `corroboration.py` then run over
`EvidenceItem`s only, which is what stops a rule from quietly depending on a
field that exists in one layer and not another.

## Why the IDs are content hashes

Phase 12 drafts a synthesis citing evidence IDs and Phase 13 stores that draft
immutably. If an ID were a position (`EV-7`) or a counter, re-running the
pipeline after a data fix could silently repoint a stored citation at a
different fact -- the draft would still validate and would now be wrong. A
content hash cannot do that: change the cited value and the ID changes, the
stored citation fails validation, and the failure is visible. That is the
property worth paying a hash for.

Hash inputs are formatted through `_fmt`, never through `repr`, because
`repr(0.1 + 0.2)` is a platform detail and an evidence ID must be identical on
every machine that runs the pipeline.

## Completeness over curation

Every registrar emits everything its layer produced, including the parts that
say "no conclusion". A ratio whose trend is `INSUFFICIENT_DATA` gets an
evidence item stating exactly that, and a narrative section that was never
located gets one too. Selecting a subset for a prompt is Phase 12's job and a
visible one; dropping evidence here would be invisible, and "the register did
not mention liquidity" would be indistinguishable from "liquidity is fine".

The one deliberate compression is documented at `narrative_evidence`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from hashlib import blake2s

from credit_risk_copilot.assessment.models import (
    KIND_TAGS,
    Concern,
    EvidenceItem,
    EvidenceKind,
    LayerId,
)
from credit_risk_copilot.explain.schema import ModelExplanation
from credit_risk_copilot.health.models import (
    DimensionStatus,
    EconomicDirection,
    FinancialHealthReport,
    HistoryDepth,
)
from credit_risk_copilot.nlp.models import (
    Assertion,
    NarrativeRiskReport,
    RiskSignalCode,
    Specificity,
)

#: Which financial dimension a narrative signal speaks to, where it speaks to
#: one. `None` means the signal is about the entity as a whole -- going-concern
#: doubt is not a liquidity fact, it is a statement about survival, and filing
#: it under one dimension would let a dimension-level rule cancel it against an
#: improving current ratio.
NARRATIVE_DIMENSIONS: dict[RiskSignalCode, str | None] = {
    RiskSignalCode.GOING_CONCERN_DOUBT: None,
    RiskSignalCode.BANKRUPTCY_CONTEMPLATED: None,
    RiskSignalCode.DELISTING_NOTICE: None,
    RiskSignalCode.MATERIAL_WEAKNESS: None,
    RiskSignalCode.COVENANT_BREACH: "leverage",
    RiskSignalCode.COVENANT_WAIVER_OR_AMENDMENT: "leverage",
    RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION: "leverage",
    RiskSignalCode.DEBT_RESTRUCTURING: "leverage",
    RiskSignalCode.CREDIT_RATING_DOWNGRADE: "leverage",
    RiskSignalCode.LIQUIDITY_SHORTFALL: "liquidity",
    RiskSignalCode.DIVIDEND_SUSPENSION: "cash_flow",
    RiskSignalCode.ASSET_IMPAIRMENT: "profitability",
}


def _fmt(value: float) -> str:
    """A float's canonical string for hashing and for prose.

    Four significant figures: enough to distinguish two genuinely different
    ratios, not enough for floating-point noise in the fifteenth decimal to
    change an evidence ID between two runs that computed the same number by
    slightly different routes.
    """
    return f"{value:.4g}"


def _signed(value: float) -> str:
    """`_fmt` with the sign always shown -- a change of `0.12` and one of
    `-0.12` must not read identically in a sentence an analyst skims."""
    return f"{value:+.4g}"


#: The five dimensions the Phase 7 health layer reports on. A model
#: attribution group matching one of these is comparable with a health
#: dimension; `scale`, `missingness` and `quality` are not.
_HEALTH_DIMENSIONS = frozenset({"liquidity", "leverage", "profitability", "coverage", "cash_flow"})


def make_ids(
    *, layer: LayerId, kind: EvidenceKind, subject: str, content: Sequence[str]
) -> tuple[str, str]:
    """`(evidence_id, identity_key)` for one item.

    `subject` identifies *what* the item is about across time (a ratio id, a
    dimension, a signal code); `content` is what it currently says. The
    identity key uses only the former, the hash uses both -- see the module
    docstring for why the two have to differ.
    """
    identity_key = f"{layer.value}:{kind.value}:{subject}"
    digest = blake2s("|".join((identity_key, *content)).encode("utf-8"), digest_size=4).hexdigest()
    return f"EV-{KIND_TAGS[kind]}-{digest}", identity_key


_HEALTH_CONCERN: dict[EconomicDirection, Concern] = {
    EconomicDirection.DETERIORATING: Concern.ELEVATED,
    EconomicDirection.IMPROVING: Concern.QUIET,
    EconomicDirection.STABLE: Concern.QUIET,
    EconomicDirection.NOT_MEANINGFUL: Concern.UNKNOWN,
    EconomicDirection.INSUFFICIENT_DATA: Concern.UNKNOWN,
    EconomicDirection.DISCONTINUOUS_HISTORY: Concern.UNKNOWN,
}

_DIMENSION_CONCERN: dict[DimensionStatus, Concern] = {
    DimensionStatus.DETERIORATING: Concern.ELEVATED,
    # MIXED means at least one ratio in the dimension is deteriorating while
    # another improves. Phase 7 refuses to net those against each other, and
    # reading MIXED as QUIET here would net them after all -- the deterioration
    # is real and something in the dimension is getting worse.
    DimensionStatus.MIXED: Concern.ELEVATED,
    DimensionStatus.IMPROVING: Concern.QUIET,
    DimensionStatus.STABLE: Concern.QUIET,
    DimensionStatus.INSUFFICIENT_DATA: Concern.UNKNOWN,
}


def health_evidence(
    report: FinancialHealthReport,
    *,
    accession: str | None = None,
    form: str | None = None,
    filed: date | None = None,
) -> tuple[EvidenceItem, ...]:
    """Dimension statuses, ratio trends, early-warning signals and data quality.

    Filing identity is passed in rather than read off the report because a
    Phase 7 report is built from a *window* of filings and does not belong to
    any single one. What is stamped here is the filing that closed the window
    -- the latest one that contributed -- which is the one the as-of gate has
    to admit.
    """
    items: list[EvidenceItem] = []

    for name, dimension in sorted(report.dimensions.items()):
        conclusive = tuple(
            trend
            for trend in dimension.ratio_trends
            if trend.economic_direction
            in (
                EconomicDirection.IMPROVING,
                EconomicDirection.STABLE,
                EconomicDirection.DETERIORATING,
            )
        )
        deteriorating = tuple(
            t.ratio_id
            for t in conclusive
            if t.economic_direction is EconomicDirection.DETERIORATING
        )
        summary = (
            f"{name}: {dimension.status.value} over {report.period_label}"
            f" ({len(conclusive)} of {len(dimension.ratio_trends)} ratios conclusive"
        )
        summary += f"; deteriorating: {', '.join(deteriorating)})" if deteriorating else ")"
        evidence_id, identity_key = make_ids(
            layer=LayerId.FINANCIAL_HEALTH,
            kind=EvidenceKind.DIMENSION_STATUS,
            subject=name,
            content=(dimension.status.value, report.period_label, *deteriorating),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.FINANCIAL_HEALTH,
                kind=EvidenceKind.DIMENSION_STATUS,
                dimension=name,
                concern=_DIMENSION_CONCERN[dimension.status],
                summary=summary,
                period_label=report.period_label,
                accession=accession,
                form=form,
                filed=filed,
                detail={
                    "status": dimension.status.value,
                    "ratios_total": len(dimension.ratio_trends),
                    "ratios_conclusive": len(conclusive),
                    "ratios_deteriorating": len(deteriorating),
                },
            )
        )

        for trend in dimension.ratio_trends:
            numbers: list[float] = []
            if trend.absolute_change is not None:
                numbers.append(trend.absolute_change)
            latest = next(
                (r.value for r in reversed(trend.results) if r.value is not None),
                None,
            )
            if latest is not None:
                numbers.append(latest)
            body = (
                f"{trend.ratio_id}: {trend.economic_direction.value}"
                f" ({trend.direction.value}) across {trend.periods_available} calculated"
                f" period(s) in {report.period_label}"
            )
            if latest is not None:
                body += f"; latest {_fmt(latest)}"
            if trend.absolute_change is not None:
                body += f"; change {_signed(trend.absolute_change)}"
            if trend.persistence:
                body += f"; {trend.persistence} consecutive period(s) same direction"
            if trend.reason:
                body += f"; {trend.reason}"
            evidence_id, identity_key = make_ids(
                layer=LayerId.FINANCIAL_HEALTH,
                kind=EvidenceKind.RATIO_TREND,
                subject=trend.ratio_id,
                content=(
                    trend.economic_direction.value,
                    trend.direction.value,
                    report.period_label,
                    *(_fmt(n) for n in numbers),
                ),
            )
            items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    identity_key=identity_key,
                    layer=LayerId.FINANCIAL_HEALTH,
                    kind=EvidenceKind.RATIO_TREND,
                    dimension=name,
                    concern=_HEALTH_CONCERN[trend.economic_direction],
                    summary=body,
                    numbers=tuple(numbers),
                    period_label=report.period_label,
                    accession=accession,
                    form=form,
                    filed=filed,
                    detail={
                        "economic_direction": trend.economic_direction.value,
                        "direction": trend.direction.value,
                        "periods_available": trend.periods_available,
                        "persistence": trend.persistence,
                        "history_depth": trend.history_depth.value,
                        "unusual_movement": trend.unusual_movement,
                        "negative_equity": trend.negative_equity,
                        "latest_value": latest,
                    },
                )
            )

    for signal in report.signals:
        subject = f"{signal.code.value}:{signal.ratio_id or 'cross_dimension'}"
        evidence_id, identity_key = make_ids(
            layer=LayerId.FINANCIAL_HEALTH,
            kind=EvidenceKind.HEALTH_SIGNAL,
            subject=subject,
            content=(report.period_label, signal.evidence),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.FINANCIAL_HEALTH,
                kind=EvidenceKind.HEALTH_SIGNAL,
                dimension=None if signal.category == "cross_dimension" else signal.category,
                # Every Phase 7 signal is an early *warning*: the engine raises
                # one only on a deteriorating trend, a negative-equity
                # denominator or an outlier move, so there is no quiet signal.
                concern=Concern.ELEVATED,
                summary=f"{signal.code.value}: {signal.evidence}",
                period_label=report.period_label,
                accession=accession,
                form=form,
                filed=filed,
                detail={
                    "code": signal.code.value,
                    "category": signal.category,
                    "ratio_id": signal.ratio_id,
                    "persistence": signal.trend.persistence if signal.trend else None,
                    "affected_dimensions": ", ".join(signal.affected_dimensions) or None,
                },
            )
        )

    for change in report.changes_since_previous_period:
        if change.absolute_change is None:
            continue
        evidence_id, identity_key = make_ids(
            layer=LayerId.FINANCIAL_HEALTH,
            kind=EvidenceKind.RATIO_CHANGE,
            subject=change.ratio_id,
            content=(
                change.from_period,
                change.to_period,
                _fmt(change.absolute_change),
            ),
        )
        numbers = [change.absolute_change]
        for value in (change.from_value, change.to_value):
            if value is not None:
                numbers.append(value)
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.FINANCIAL_HEALTH,
                kind=EvidenceKind.RATIO_CHANGE,
                dimension=None,
                concern=Concern.UNKNOWN,
                summary=(
                    f"{change.ratio_id} moved {_fmt(change.absolute_change)}"
                    f" from {change.from_period} to {change.to_period}"
                ),
                numbers=tuple(numbers),
                period_label=change.to_period,
                accession=accession,
                form=form,
                filed=filed,
                detail={
                    "from_period": change.from_period,
                    "to_period": change.to_period,
                    "from_value": change.from_value,
                    "to_value": change.to_value,
                },
            )
        )

    quality = report.data_quality
    for label, ratios in (
        ("low_confidence_input", quality.ratios_with_low_confidence_input),
        ("manual_correction", quality.ratios_with_manual_correction),
        ("limited_history", quality.ratios_with_limited_history),
    ):
        if not ratios:
            continue
        evidence_id, identity_key = make_ids(
            layer=LayerId.DATA_QUALITY,
            kind=EvidenceKind.DATA_QUALITY_CAVEAT,
            subject=label,
            content=(report.period_label, *sorted(ratios)),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.DATA_QUALITY,
                kind=EvidenceKind.DATA_QUALITY_CAVEAT,
                concern=Concern.UNKNOWN,
                summary=(
                    f"{len(ratios)} ratio(s) carry {label.replace('_', ' ')}:"
                    f" {', '.join(sorted(ratios))}"
                ),
                period_label=report.period_label,
                accession=accession,
                form=form,
                filed=filed,
                detail={"caveat": label, "ratio_count": len(ratios)},
            )
        )
    return tuple(items)


#: Above this percentile the model's position is treated as a read of
#: `ELEVATED` by the cross-layer rules. Chosen to match the alert rate the
#: Phase 8 evaluation reports precision at, so a contradiction here means the
#: same thing as an alert there; disclosed as a threshold rather than buried,
#: on the same principle as `health/thresholds.py`.
ELEVATED_PERCENTILE = 90.0
#: Below this, the model is treated as reading `QUIET`. The band between the
#: two is deliberately `UNKNOWN`: a company at the 70th percentile is neither
#: flagged nor cleared, and forcing it into one of the two would manufacture
#: contradictions out of the middle of the distribution.
QUIET_PERCENTILE = 50.0


def model_evidence(explanation: ModelExplanation) -> tuple[EvidenceItem, ...]:
    """The score, its per-dimension attribution, and every caveat.

    The score item's `concern` is read from `score_percentile`, never from
    `score`. D-033 settled that the raw number is not a probability, and a rule
    that thresholded it would be re-asserting the reading D-033 removed.
    Without a percentile the model has no read at all, which is `UNKNOWN`.
    """
    items: list[EvidenceItem] = []
    percentile = explanation.score_percentile

    if percentile is None:
        concern = Concern.UNKNOWN
        position = "no population supplied, so no ranking position"
    elif percentile >= ELEVATED_PERCENTILE:
        concern = Concern.ELEVATED
        position = f"{_fmt(percentile)}th percentile of the scored population"
    elif percentile < QUIET_PERCENTILE:
        concern = Concern.QUIET
        position = f"{_fmt(percentile)}th percentile of the scored population"
    else:
        concern = Concern.UNKNOWN
        position = f"{_fmt(percentile)}th percentile of the scored population"

    numbers = [explanation.score] + ([percentile] if percentile is not None else [])
    evidence_id, identity_key = make_ids(
        layer=LayerId.PREDICTIVE_MODEL,
        kind=EvidenceKind.MODEL_SCORE,
        subject=explanation.model_name,
        content=(
            explanation.fiscal_period_label,
            _fmt(explanation.score),
            _fmt(percentile) if percentile is not None else "none",
        ),
    )
    items.append(
        EvidenceItem(
            evidence_id=evidence_id,
            identity_key=identity_key,
            layer=LayerId.PREDICTIVE_MODEL,
            kind=EvidenceKind.MODEL_SCORE,
            concern=concern,
            summary=(
                f"{explanation.model_name} scores {_fmt(explanation.score)}"
                f" for {explanation.fiscal_period_label}: {position}."
                " The score is a ranking position, not a probability of default."
            ),
            numbers=tuple(numbers),
            period_label=explanation.fiscal_period_label,
            accession=explanation.source_accession,
            filed=explanation.prediction_date,
            detail={
                "model_name": explanation.model_name,
                "model_family": explanation.model_family,
                "attribution_method": explanation.attribution_method,
                "score": explanation.score,
                "baseline": explanation.baseline,
                "score_percentile": percentile,
                "missingness_share": explanation.missingness_share,
            },
        )
    )

    for attribution in explanation.by_dimension:
        top = ", ".join(c.feature for c in attribution.top_features[:3])
        evidence_id, identity_key = make_ids(
            layer=LayerId.PREDICTIVE_MODEL,
            kind=EvidenceKind.MODEL_DRIVER,
            subject=attribution.group,
            content=(
                explanation.fiscal_period_label,
                _fmt(attribution.contribution),
                _fmt(attribution.share_of_absolute),
            ),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.PREDICTIVE_MODEL,
                kind=EvidenceKind.MODEL_DRIVER,
                # `group` is a dimension name for financial groups and a family
                # name ("missingness", "scale") otherwise. Only the former is a
                # dimension the health layer also speaks about, so only the
                # former can take part in a per-dimension rule.
                dimension=attribution.group if attribution.group in _HEALTH_DIMENSIONS else None,
                concern=(
                    Concern.ELEVATED
                    if attribution.contribution > 0
                    else Concern.QUIET
                    if attribution.contribution < 0
                    else Concern.UNKNOWN
                ),
                summary=(
                    f"{attribution.group} contributes {_signed(attribution.contribution)}"
                    f" to the score ({_fmt(attribution.share_of_absolute * 100)}% of total"
                    f" absolute attribution across {attribution.feature_count} feature(s)"
                    + (f"; largest: {top}" if top else "")
                    + ")"
                ),
                numbers=(attribution.contribution, attribution.share_of_absolute * 100),
                period_label=explanation.fiscal_period_label,
                accession=explanation.source_accession,
                filed=explanation.prediction_date,
                detail={
                    "group": attribution.group,
                    "contribution": attribution.contribution,
                    "share_of_absolute": attribution.share_of_absolute,
                    "feature_count": attribution.feature_count,
                    "raises_risk": attribution.contribution > 0,
                },
            )
        )

    for caveat in explanation.caveats:
        evidence_id, identity_key = make_ids(
            layer=LayerId.PREDICTIVE_MODEL,
            kind=EvidenceKind.MODEL_CAVEAT,
            subject=f"{caveat.code.value}:{caveat.subject or ''}",
            content=(explanation.fiscal_period_label, caveat.message),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.PREDICTIVE_MODEL,
                kind=EvidenceKind.MODEL_CAVEAT,
                concern=Concern.UNKNOWN,
                summary=f"{caveat.code.value}: {caveat.message}",
                period_label=explanation.fiscal_period_label,
                accession=explanation.source_accession,
                filed=explanation.prediction_date,
                detail={"code": caveat.code.value, "subject": caveat.subject},
            )
        )
    return tuple(items)


def narrative_evidence(report: NarrativeRiskReport) -> tuple[EvidenceItem, ...]:
    """One evidence item per distinct statement the filer makes about itself.

    **The one compression in this module.** A filing can assert asset
    impairment sixteen times; that is one fact about the company with sixteen
    instances, not sixteen facts. Signals are therefore grouped by
    `(code, assertion)` and the group's *first occurrence in document order*
    carries the verbatim quote, with the occurrence count in `detail`.

    Document order rather than "the best quote", because any notion of best
    would be a ranking over sentences that nothing in this project has measured
    -- and the first occurrence is the one a reader checking the filing reaches
    first. The full set stays on the source `NarrativeRiskReport`, which Phase
    13 persists alongside the assessment, so nothing is lost, only summarised.

    `NEGATED` signals are registered with `concern=QUIET` and kept, because an
    explicit statement of covenant compliance is evidence -- and because the
    self-contradiction rule needs both moods present to fire at all.
    """
    items: list[EvidenceItem] = []
    grouped: dict[tuple[RiskSignalCode, Assertion], list] = {}
    for signal in report.signals:
        grouped.setdefault((signal.code, signal.assertion), []).append(signal)

    for (code, assertion), signals in sorted(
        grouped.items(), key=lambda kv: (kv[0][0].value, kv[0][1].value)
    ):
        ordered = sorted(signals, key=lambda s: (s.quote.section_id or "", s.quote.char_start))
        first = ordered[0]
        if assertion is Assertion.ASSERTED:
            concern = Concern.ELEVATED
            mood = "states"
        elif assertion is Assertion.NEGATED:
            concern = Concern.QUIET
            mood = "explicitly denies"
        else:
            # HYPOTHETICAL and CROSS_REFERENCE are emitted only when the caller
            # asked for them. They are not a read on the company either way:
            # D-035 measured conditional covenant language at lift 1.02.
            concern = Concern.UNKNOWN
            mood = "discusses (conditionally)"

        evidence_id, identity_key = make_ids(
            layer=LayerId.NARRATIVE,
            kind=EvidenceKind.NARRATIVE_SIGNAL,
            subject=f"{code.value}:{assertion.value}",
            content=(report.accession or "", first.quote.text, str(len(ordered))),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.NARRATIVE,
                kind=EvidenceKind.NARRATIVE_SIGNAL,
                dimension=NARRATIVE_DIMENSIONS.get(code),
                concern=concern,
                summary=(
                    f"The filer {mood} {first.label.lower()}"
                    f" ({len(ordered)} occurrence(s) in {first.quote.section_id or 'the filing'};"
                    f" specificity {first.specificity.value})"
                ),
                accession=report.accession,
                form=report.form,
                filed=date.fromisoformat(report.filed) if report.filed else None,
                quote=first.quote.text,
                detail={
                    "code": code.value,
                    "assertion": assertion.value,
                    "specificity": first.specificity.value,
                    "pattern_id": first.pattern_id,
                    "section_id": first.quote.section_id,
                    "char_start": first.quote.char_start,
                    "char_end": first.quote.char_end,
                    "occurrences": len(ordered),
                },
            )
        )

    for coverage in report.coverage:
        if coverage.located:
            continue
        evidence_id, identity_key = make_ids(
            layer=LayerId.NARRATIVE,
            kind=EvidenceKind.NARRATIVE_COVERAGE,
            subject=coverage.section_id,
            content=(report.accession or "", coverage.reason or "not located"),
        )
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                identity_key=identity_key,
                layer=LayerId.NARRATIVE,
                kind=EvidenceKind.NARRATIVE_COVERAGE,
                concern=Concern.UNKNOWN,
                summary=(
                    f"{coverage.section_id} was not located in this filing"
                    f" ({coverage.reason or 'no reason recorded'}), so no signal from it"
                    " could have been found either way"
                ),
                accession=report.accession,
                form=report.form,
                filed=date.fromisoformat(report.filed) if report.filed else None,
                detail={"section_id": coverage.section_id, "located": False},
            )
        )
    return tuple(items)


def high_specificity_codes(items: Sequence[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    """Asserted narrative items whose code was *measured* as high-specificity.

    Phase 10 set `Specificity` from each code's rate in pre-bankruptcy versus
    comparison filings, and corrected two of its own declarations from the data
    when they disagreed. Reading that field rather than hard-coding a list here
    keeps the cross-layer rules on the measurement instead of on a second
    opinion that would drift from it.
    """
    return tuple(
        item
        for item in items
        if item.kind is EvidenceKind.NARRATIVE_SIGNAL
        and item.detail.get("assertion") == Assertion.ASSERTED.value
        and item.detail.get("specificity") == Specificity.HIGH.value
    )


def limited_history(report: FinancialHealthReport) -> bool:
    """True when no dimension has adequate history behind any of its trends."""
    return all(
        trend.history_depth is HistoryDepth.LIMITED
        for dimension in report.dimensions.values()
        for trend in dimension.ratio_trends
    )
