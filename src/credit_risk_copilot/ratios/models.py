"""Ratio result schema: the Phase 6 typed output.

Deliberately imports only `financials.models` -- the Phase 5 -> 6 interface
(`docs/canonical_schema.md` §16) -- and nothing about how a `CanonicalFact`
was produced. A `RatioResult` references the `CanonicalFact` objects it
consumed directly rather than re-deriving a parallel set of fields: full
provenance (XBRL tag, accession, derivation formula) is already on those
objects, and duplicating it here would be a second copy to keep in sync.

Design principles carried over from `financials/models.py`:

- **A ratio is not a float.** `value=None` is normal and expected; `status`
  says why, `inputs` says what was actually available.
- **Missing is not zero, invalid is not missing.** A ratio whose denominator
  is a filing's own reported zero is a different fact from a ratio whose
  input was never resolved -- `RatioStatus` keeps them apart.
- **Caveats are warnings, not statuses.** A `CALCULATED` ratio built from a
  `DERIVED` or low-confidence input is still `CALCULATED`; the caveat travels
  in `warnings`, never silently, never by refusing to compute.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.financials.models import CanonicalFact, FactStatus


class RatioStatus(str, Enum):
    """Whether, and why, a ratio could be calculated.

    Kept to four states -- the minimum this engine's callers actually need to
    branch on (§9 of the phase brief). Everything else that matters about a
    calculated value (a derived input, a negative-equity denominator, a
    manual correction) is a `warnings` entry, not a fifth status.
    """

    #: Every required input resolved and the denominator was usable.
    CALCULATED = "calculated"
    #: At least one required concept has no resolvable value for this period
    #: (absent from the filing, or a Phase 5 `MISSING` fact).
    MISSING_INPUT = "missing_input"
    #: The denominator is zero (within $1) or, for a ratio whose denominator
    #: is conventionally non-negative, negative.
    INVALID_DENOMINATOR = "invalid_denominator"
    #: At least one required concept is a Phase 5 `CONFLICTING` fact: a value
    #: exists but disagreeing sources were never resolved to one number.
    CONFLICTING_INPUT = "conflicting_input"


class WarningCode(str, Enum):
    """The caveat category behind a `RatioWarning` (Phase 6 audit §17).

    A plain-English `message` alone forces a downstream consumer to substring-
    match it to act programmatically -- exactly the "no hidden magic" failure
    this schema otherwise avoids. Five codes, one per caveat this engine
    actually raises today; a new caveat type gets a new code, not a reused
    one with different meanings buried in `message`.
    """

    #: The denominator is a legitimately negative equity concept
    #: (`debt_to_equity`, `roe`) -- calculated anyway, per §10 of the brief.
    NEGATIVE_EQUITY = "negative_equity"
    #: The denominator is nonzero but small enough, relative to the
    #: numerator, that the ratio is dominated by noise in the smaller figure
    #: (currently: `interest_coverage` only -- see `engine.py`).
    NEAR_ZERO_DENOMINATOR = "near_zero_denominator"
    #: The input has no direct source tag and was computed by Phase 5 from
    #: other canonical facts.
    DERIVED_INPUT = "derived_input"
    #: The input's Phase 5 `Confidence` is `LOW`.
    LOW_CONFIDENCE_INPUT = "low_confidence_input"
    #: The input was overwritten by an analyst; the original value is on the
    #: underlying `CanonicalFact.correction`.
    MANUAL_INPUT = "manual_input"


class RatioWarning(BaseModel):
    """One structured caveat on an otherwise `CALCULATED` ratio.

    `code` is what Phase 7 (or any other caller) should branch on;
    `concept` names which input the caveat is about; `message` is the same
    human-readable text `explain()` prints, kept so nothing is lost by
    structuring this.
    """

    model_config = ConfigDict(frozen=True)

    code: WarningCode
    concept: str
    message: str


class RatioResult(BaseModel):
    """One ratio, for one period, for one filing (or as-of view).

    `inputs` is keyed by canonical concept id, in the ratio definition's
    formula order, and holds the actual `CanonicalFact` consumed -- or `None`
    when the filing had no fact for that concept at all (as opposed to a
    Phase 5 `MISSING` placeholder, which is still a fact, just with
    `value=None`). Both cases contribute to `MISSING_INPUT`; keeping the
    distinction in `inputs` costs nothing and preserves the "why" for the
    caller who wants it.
    """

    model_config = ConfigDict(frozen=True)

    ratio_id: str
    name: str
    category: str
    period_label: str
    value: float | None
    unit: str
    status: RatioStatus
    #: Machine-readable, e.g. "total_debt / shareholders_equity" -- matches
    #: `RatioDefinition.formula` exactly, for programmatic use.
    formula: str
    #: Human-readable, e.g. "Total Debt / Shareholders' Equity" -- what
    #: `explain()` prints.
    formula_display: str
    inputs: dict[str, CanonicalFact | None]
    warnings: tuple[RatioWarning, ...] = ()
    #: Populated whenever `status != CALCULATED`; explains which concept(s)
    #: were the problem and why.
    reason: str | None = None
    #: `None` for every ratio with exactly one calculation method. Explicit
    #: only where a documented choice exists between methods -- currently
    #: `"ending_balance"` on `roa`/`roe` (D-020), so a caller can never
    #: mistake these for an average-balance figure without reading the code.
    calculation_method: str | None = None

    @property
    def missing_concepts(self) -> tuple[str, ...]:
        """Which required concepts had no resolvable value, when
        `status is MISSING_INPUT`. Machine-readable alternative to parsing
        `reason` (Phase 6 audit §13)."""
        if self.status is not RatioStatus.MISSING_INPUT:
            return ()
        return tuple(c for c, f in self.inputs.items() if f is None or f.effective_value is None)

    @property
    def conflicting_concepts(self) -> tuple[str, ...]:
        """Which required concepts are Phase 5 `CONFLICTING` facts, when
        `status is CONFLICTING_INPUT`."""
        if self.status is not RatioStatus.CONFLICTING_INPUT:
            return ()
        return tuple(
            c
            for c, f in self.inputs.items()
            if f is not None and f.status is FactStatus.CONFLICTING
        )

    def explain(self) -> str:
        """A deterministic, purely factual explanation: formula and the input
        values that produced (or failed to produce) `value`. Never a
        financial judgement (§17) -- that is Phase 7's job."""
        header = f"{self.name} = {_format_value(self.value, self.unit)} ({self.period_label})"
        if self.status is not RatioStatus.CALCULATED:
            lines = [header, f"Status: {self.status.value}"]
            if self.reason:
                lines.append(f"Reason: {self.reason}")
        else:
            lines = [header, "", f"Formula: {self.formula_display}"]
        lines.append("")
        for concept, fact in self.inputs.items():
            if fact is None or fact.effective_value is None:
                lines.append(f"  {concept} = (no value)")
            else:
                lines.append(
                    f"  {concept} = {_format_value(fact.effective_value, '$')} "
                    f"({fact.status.value}, {fact.confidence.value} confidence)"
                )
        if self.warnings:
            lines.append("")
            lines.extend(f"Warning: {w.message}" for w in self.warnings)
        return "\n".join(lines)


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "null"
    if unit == "%":
        return f"{value * 100:,.1f}%"
    if unit == "x":
        return f"{value:,.2f}x"
    return f"${value:,.0f}"


class RatioChange(BaseModel):
    """A deterministic period-over-period delta for one ratio (§17, §19).

    Pure arithmetic on two already-calculated `RatioResult`s -- no threshold,
    no "improving"/"worsening" label, no early-warning judgement. That
    interpretation is explicitly Phase 7's job; this is the same class of
    fact as the ratio calculation itself, just applied across two periods.
    """

    model_config = ConfigDict(frozen=True)

    ratio_id: str
    from_period: str
    to_period: str
    from_value: float | None
    to_value: float | None
    absolute_change: float | None
    #: `None` when `from_value` is `None` or zero -- a percent change against
    #: zero is undefined, not a silently manufactured infinity.
    percent_change: float | None
