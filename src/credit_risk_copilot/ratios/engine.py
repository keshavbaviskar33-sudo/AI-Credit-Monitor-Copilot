"""The calculation engine: canonical facts -> deterministic ratio results.

    Canonical Facts -> Fact Resolution -> Validation -> Calculation -> RatioResult

No LLM, no financial judgement, no credit decision (§1, §2). Every function
here is pure arithmetic and explicit status logic over `CanonicalFact` values
already resolved by Phase 5.

## The Phase 5/6 boundary, concretely

`calculate_ratio` and everything built on it take a `FactGetter` -- a plain
`(concept, period_label) -> CanonicalFact | None` callable -- not a Phase 5
object. `CanonicalFilingFacts.get` already has exactly this shape, so
`ratios_for_filing` passes it straight through with zero adaptation code;
`ratios_from_facts` adapts the dict `CompanyFinancials.as_of()` returns the
same way. Neither this module nor `registry.py` nor `models.py` imports
`resolver`, `xbrl`, or `extraction` -- deleting every PDF/XBRL/HTML module
from the project would not break this package (§38).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from credit_risk_copilot.financials.models import CanonicalFact, FactStatus
from credit_risk_copilot.ratios.models import (
    RatioChange,
    RatioResult,
    RatioStatus,
    RatioWarning,
    WarningCode,
)
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS, RatioDefinition

#: A source of canonical facts: one filing's own `.get`, or a thin adapter
#: over a `CompanyFinancials.as_of()` dict. Nothing here assumes which.
FactGetter = Callable[[str, str], CanonicalFact | None]


class _FilingLike(Protocol):
    """Structurally, exactly `CanonicalFilingFacts` -- named here instead of
    imported so this module's only real dependency on Phase 5 stays at
    `financials.models.CanonicalFact` (§38)."""

    def get(self, concept: str, period_label: str) -> CanonicalFact | None: ...

    @property
    def period_labels(self) -> tuple[str, ...]: ...


#: Below this many dollars, a value is treated as zero rather than a real
#: nonzero denominator -- the same $1 tolerance `resolver.py` and
#: `validation.py` already use for whole-dollar canonical values.
_ZERO_TOLERANCE = 1.0

#: interest_coverage only (§20): interest_expense present and nonzero but
#: small enough relative to EBIT that the ratio is dominated by noise in the
#: smaller figure, not a meaningful coverage signal. A quality flag, not a
#: judgement about whether coverage is "good" -- that stays Phase 7's.
_INTEREST_COVERAGE_NEAR_ZERO_RATIO = 0.02


def calculate_ratio(
    get_fact: FactGetter, definition: RatioDefinition, period_label: str
) -> RatioResult:
    """Calculate one ratio, for one period, from whatever `get_fact` returns
    for each of `definition.inputs`. Never raises on missing or invalid
    data -- every failure mode is a `RatioStatus`, so a caller computing many
    ratios never has one bad input abort the batch (§30)."""
    inputs: dict[str, CanonicalFact | None] = {
        concept: get_fact(concept, period_label) for concept in definition.inputs
    }

    conflicting = [
        c for c, f in inputs.items() if f is not None and f.status is FactStatus.CONFLICTING
    ]
    if conflicting:
        return _unavailable(
            definition,
            period_label,
            inputs,
            RatioStatus.CONFLICTING_INPUT,
            f"Conflicting input(s) {', '.join(conflicting)}: disagreeing sources were "
            "reported and never resolved to one value.",
        )

    missing = [c for c, f in inputs.items() if f is None or f.effective_value is None]
    if missing:
        return _unavailable(
            definition,
            period_label,
            inputs,
            RatioStatus.MISSING_INPUT,
            f"Missing required input(s): {', '.join(missing)}.",
        )

    # `missing` is empty, so every fact is present and resolved -- narrow
    # `CanonicalFact | None` to `CanonicalFact` once, here, rather than
    # re-checking `is not None` in `_warnings` for a branch that can no
    # longer occur.
    resolved: dict[str, CanonicalFact] = {}
    values: dict[str, float] = {}
    for concept, fact in inputs.items():
        assert fact is not None and fact.effective_value is not None
        resolved[concept] = fact
        values[concept] = fact.effective_value
    denominator = values[definition.denominator_concept]

    if abs(denominator) < _ZERO_TOLERANCE:
        return _unavailable(
            definition,
            period_label,
            inputs,
            RatioStatus.INVALID_DENOMINATOR,
            f"{definition.denominator_concept} is zero (or within ${_ZERO_TOLERANCE:.0f} of "
            f"zero) for {period_label} -- {definition.name} is undefined.",
        )
    if denominator < 0 and not definition.denominator_may_be_negative:
        return _unavailable(
            definition,
            period_label,
            inputs,
            RatioStatus.INVALID_DENOMINATOR,
            f"{definition.denominator_concept} is negative ({denominator:,.0f}) for "
            f"{period_label}, which is not a valid denominator for {definition.name}.",
        )

    value = definition.compute(values)
    warnings = _warnings(definition, resolved, values, denominator)
    return RatioResult(
        ratio_id=definition.ratio_id,
        name=definition.name,
        category=definition.category,
        period_label=period_label,
        value=value,
        unit=definition.unit,
        status=RatioStatus.CALCULATED,
        formula=definition.formula,
        formula_display=definition.formula_display,
        inputs=inputs,
        warnings=tuple(warnings),
        calculation_method=definition.calculation_method,
    )


def _unavailable(
    definition: RatioDefinition,
    period_label: str,
    inputs: dict[str, CanonicalFact | None],
    status: RatioStatus,
    reason: str,
) -> RatioResult:
    return RatioResult(
        ratio_id=definition.ratio_id,
        name=definition.name,
        category=definition.category,
        period_label=period_label,
        value=None,
        unit=definition.unit,
        status=status,
        formula=definition.formula,
        formula_display=definition.formula_display,
        inputs=inputs,
        reason=reason,
        calculation_method=definition.calculation_method,
    )


def _warnings(
    definition: RatioDefinition,
    facts: dict[str, CanonicalFact],
    values: dict[str, float],
    denominator: float,
) -> list[RatioWarning]:
    warnings: list[RatioWarning] = []
    if denominator < 0 and definition.denominator_may_be_negative:
        warnings.append(
            RatioWarning(
                code=WarningCode.NEGATIVE_EQUITY,
                concept=definition.denominator_concept,
                message=(
                    f"{definition.denominator_concept} is negative ({denominator:,.0f}); the "
                    f"conventional interpretation of {definition.name} does not apply to "
                    "negative equity (interpretation is deferred to later analysis)."
                ),
            )
        )
    if definition.ratio_id == "interest_coverage":
        interest_expense, ebit = values["interest_expense"], values["ebit"]
        if abs(interest_expense) < _INTEREST_COVERAGE_NEAR_ZERO_RATIO * abs(ebit):
            warnings.append(
                RatioWarning(
                    code=WarningCode.NEAR_ZERO_DENOMINATOR,
                    concept="interest_expense",
                    message=(
                        f"interest_expense ({interest_expense:,.0f}) is small relative to "
                        f"EBIT ({ebit:,.0f}); interest coverage is highly sensitive to small "
                        "changes in interest expense at this scale."
                    ),
                )
            )
    for concept, fact in facts.items():
        if fact.confidence.value == "low":
            warnings.append(
                RatioWarning(
                    code=WarningCode.LOW_CONFIDENCE_INPUT,
                    concept=concept,
                    message=(
                        f"{concept} is a low-confidence input ({fact.reason or fact.status.value})."
                    ),
                )
            )
        if fact.origin.value == "derived":
            warnings.append(
                RatioWarning(
                    code=WarningCode.DERIVED_INPUT,
                    concept=concept,
                    message=f"{concept} is a derived value: {fact.formula}.",
                )
            )
        if fact.status is FactStatus.MANUALLY_CORRECTED and fact.correction is not None:
            warnings.append(
                RatioWarning(
                    code=WarningCode.MANUAL_INPUT,
                    concept=concept,
                    message=(
                        f"{concept} was manually corrected from "
                        f"{fact.correction.previous_value} to {fact.correction.value}."
                    ),
                )
            )
    return warnings


def calculate_ratios(
    get_fact: FactGetter,
    period_label: str,
    definitions: Sequence[RatioDefinition] = RATIO_DEFINITIONS,
) -> tuple[RatioResult, ...]:
    """Every ratio in `definitions`, for one period."""
    return tuple(calculate_ratio(get_fact, d, period_label) for d in definitions)


def calculate_ratio_history(
    get_fact: FactGetter,
    period_labels: Sequence[str],
    definitions: Sequence[RatioDefinition] = RATIO_DEFINITIONS,
) -> dict[str, tuple[RatioResult, ...]]:
    """`ratio_id -> RatioResult` per period, in the given period order (§18).
    Each period is calculated independently -- no ratio here depends on
    another period's data, so one missing year never blocks another."""
    by_ratio: dict[str, list[RatioResult]] = {d.ratio_id: [] for d in definitions}
    for period_label in period_labels:
        for definition in definitions:
            by_ratio[definition.ratio_id].append(
                calculate_ratio(get_fact, definition, period_label)
            )
    return {ratio_id: tuple(results) for ratio_id, results in by_ratio.items()}


def ratios_for_filing(
    filing: _FilingLike,
    periods: Sequence[str] | None = None,
    definitions: Sequence[RatioDefinition] = RATIO_DEFINITIONS,
) -> dict[str, tuple[RatioResult, ...]]:
    """Convenience entry point for one filing's own `CanonicalFilingFacts`
    (which already carries every comparative period its XBRL reports -- often
    two to three fiscal years from a single accession, per
    `canonical_schema.md` §5). Structurally typed on `.get`/`.period_labels`
    rather than importing `CanonicalFilingFacts`, keeping this module's only
    dependency on Phase 5 at `financials.models`."""
    period_labels = periods if periods is not None else filing.period_labels
    return calculate_ratio_history(filing.get, period_labels, definitions)


def ratios_from_facts(
    facts: Mapping[tuple[str, str], CanonicalFact],
    period_labels: Sequence[str],
    definitions: Sequence[RatioDefinition] = RATIO_DEFINITIONS,
) -> dict[str, tuple[RatioResult, ...]]:
    """Convenience entry point for `CompanyFinancials.as_of(cutoff)`'s return
    value: a point-in-time, as-filed view across a company's whole filing
    history (D-008). Takes the plain dict rather than `CompanyFinancials`
    itself, so this module never imports `financials.company`."""

    def get_fact(concept: str, period_label: str) -> CanonicalFact | None:
        return facts.get((concept, period_label))

    return calculate_ratio_history(get_fact, period_labels, definitions)


def ratio_history_changes(results: Sequence[RatioResult]) -> tuple[RatioChange, ...]:
    """Period-over-period deltas for one ratio's history, consecutive pairs
    only (§17, §19). Caller supplies `results` in chronological order --
    `calculate_ratio_history`'s per-ratio tuples already are, provided the
    `period_labels` passed to it were. Purely arithmetic: a change is only
    produced when both periods actually calculated a value, and
    `percent_change` is `None` rather than infinite when the prior value is
    zero."""
    changes: list[RatioChange] = []
    for prior, current in zip(results, results[1:], strict=False):
        if (
            prior.status is not RatioStatus.CALCULATED
            or current.status is not RatioStatus.CALCULATED
        ):
            continue
        assert prior.value is not None and current.value is not None
        absolute = current.value - prior.value
        # Ratio values are small floats (multiples or fractions), not dollar
        # amounts, so this uses a plain numerical epsilon rather than the
        # $1 tolerance the dollar-valued checks above use.
        percent = (absolute / prior.value) if abs(prior.value) >= 1e-9 else None
        changes.append(
            RatioChange(
                ratio_id=current.ratio_id,
                from_period=prior.period_label,
                to_period=current.period_label,
                from_value=prior.value,
                to_value=current.value,
                absolute_change=absolute,
                percent_change=percent,
            )
        )
    return tuple(changes)
