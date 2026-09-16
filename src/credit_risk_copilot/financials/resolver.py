"""The core Phase 5 engine: XBRL facts -> canonical financial facts.

1. **Direct-tag resolution.** For every concept and period, the USD-unit,
   annual-period XBRL facts under its tags are combined according to the
   concept's declared `TagResolution`: synonyms that disagree become
   `CONFLICTING`; differently-scoped tags keep the preferred one and record
   the rest as candidates; additive components are summed (or the filer's own
   total is used).
2. **Derivation to a fixpoint, then missing.** Unresolved (concept, period)
   slots are derived from already-resolved inputs, repeatedly until nothing
   new resolves; whatever remains is `MISSING` with a stated reason -- never a
   fabricated 0 (§18).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from credit_risk_copilot.financials.concept_map import (
    CONCEPT_DEFINITIONS,
    ConceptDefinition,
    TagResolution,
)
from credit_risk_copilot.financials.models import (
    CandidateValue,
    CanonicalFact,
    CanonicalFilingFacts,
    Confidence,
    FactStatus,
    FiscalPeriodLabel,
    Origin,
    Period,
    PeriodType,
    Provenance,
    SourceType,
    StatementType,
)
from credit_risk_copilot.financials.periods import is_annual_period, period_from_xbrl_fact
from credit_risk_copilot.financials.validation import run_validations
from credit_risk_copilot.financials.xbrl import XbrlFact, facts_for_accession, index_by_concept

#: The only currency unit this schema accepts. MVP scope is US GAAP filers
#: reporting in dollars (D-002); a fact in any other unit is excluded, never
#: converted, and `CanonicalFact.currency` records the unit actually used.
REPORTING_CURRENCY = "USD"


def _values_agree(a: float, b: float, *, rel_tol: float = 0.001, abs_tol: float = 1.0) -> bool:
    """Whether two reported values are "the same number".

    0.1% relative, not the 1% this started with. Within one XBRL filing two
    genuine synonyms carry the same integer; the only legitimate difference
    is a tag reported at coarser `decimals` (rounded to millions), which is
    far inside 0.1% for any figure large enough to matter. The Phase 5 audit
    found 1% let iHeartMedia's 181M gap between total and noncurrent
    long-term debt (0.9%) pass as "the same number" -- a real difference
    silently absorbed, and its provenance dropped.
    """
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def _xbrl_provenance(fact: XbrlFact) -> Provenance:
    return Provenance(
        source_type=SourceType.XBRL,
        extraction_method="xbrl-companyfacts",
        concept=fact.concept,
        namespace=fact.namespace,
        is_extension_concept=fact.is_extension,
        accession=fact.accn,
        form=fact.form,
        filed=fact.filed,
        document_uri=f"companyfacts:{fact.namespace}:{fact.concept}",
        original_text=str(fact.val),
        original_value=float(fact.val),
    )


def _resolve_direct_tags(
    concept_def: ConceptDefinition,
    index: dict[tuple[str, str], list[XbrlFact]],
    resolved: dict[tuple[str, str], CanonicalFact],
    periods_seen: dict[tuple[PeriodType, str], Period],
    fiscal_month_day: tuple[int, int],
) -> None:
    priority = {tag: i for i, tag in enumerate(concept_def.xbrl_tags)}
    by_period: dict[str, dict[str, list[XbrlFact]]] = {}

    for tag in concept_def.xbrl_tags:
        for entry in index.get(("us-gaap", tag), []):
            # Every concept in this schema is a monetary amount. A fact in
            # any other unit (a foreign currency, "shares", "pure") is not a
            # candidate at all -- silently mixing units is the bug that makes
            # a ratio look plausible while being off by an exchange rate.
            if entry.unit != REPORTING_CURRENCY:
                continue
            period = period_from_xbrl_fact(
                {"start": entry.start, "end": entry.end}, period_type=concept_def.period_nature
            )
            if period is None:
                continue
            # Reject anything that isn't plausibly *this filing's* annual
            # period -- a "selected quarterly financial data" footnote tags
            # each quarter under the same concept and accession, and without
            # this a quarter's value would collide with the annual one under
            # the same "FYnnnn" label (see `periods.is_annual_period`).
            if not is_annual_period(period, *fiscal_month_day):
                continue
            # Keyed by (nature, label): an instant "FY2025" (a balance at
            # year end) and a duration "FY2025" (the year's flow) are
            # different periods that happen to share a label, and a concept
            # must only ever be given the period matching its own nature.
            periods_seen.setdefault((concept_def.period_nature, period.label), period)
            same_tag = by_period.setdefault(period.label, {}).setdefault(tag, [])
            if all(existing.val != entry.val for existing in same_tag):
                same_tag.append(entry)

    for period_label, by_tag in by_period.items():
        period = periods_seen[(concept_def.period_nature, period_label)]
        # One tag carrying two different values for one annual period, in one
        # filing, is a genuine ambiguity (e.g. two contexts the dimensionless
        # companyfacts view collapsed). Never resolve it by "first one wins".
        duplicated = {t: facts for t, facts in by_tag.items() if len(facts) > 1}
        if duplicated:
            tag, facts = next(iter(duplicated.items()))
            resolved[(concept_def.concept, period_label)] = CanonicalFact(
                concept=concept_def.concept,
                statement=concept_def.statement,
                period=period,
                value=None,
                currency=REPORTING_CURRENCY,
                status=FactStatus.CONFLICTING,
                confidence=Confidence.LOW,
                origin=Origin.REPORTED,
                provenance=(_xbrl_provenance(facts[0]),),
                candidates=tuple(
                    CandidateValue(value=f.val, provenance=_xbrl_provenance(f)) for f in facts
                ),
                reason=(
                    f"{tag} reports {len(facts)} different values for {period_label} in "
                    f"one filing: {', '.join(f'{f.val:,.0f}' for f in facts)}."
                ),
            )
            continue
        ordered = [(t, by_tag[t][0]) for t in sorted(by_tag, key=lambda t: priority[t])]
        resolved[(concept_def.concept, period_label)] = _combine_tags(
            concept_def, period, period_label, ordered
        )


def _combine_tags(
    concept_def: ConceptDefinition,
    period: Period,
    period_label: str,
    ordered: list[tuple[str, XbrlFact]],
) -> CanonicalFact:
    """Turn every tag reported for one (concept, period) into one fact,
    according to the concept's declared `TagResolution`."""

    def fact(**fields: Any) -> CanonicalFact:
        return CanonicalFact(
            concept=concept_def.concept,
            statement=concept_def.statement,
            period=period,
            currency=REPORTING_CURRENCY,
            **fields,
        )

    if concept_def.tag_resolution is TagResolution.COMPONENTS:
        present = dict(ordered)
        total_tag = concept_def.total_tag
        if total_tag is not None and total_tag in present:
            return fact(
                value=float(present[total_tag].val),
                status=FactStatus.FOUND,
                confidence=Confidence.HIGH,
                origin=Origin.REPORTED,
                provenance=(_xbrl_provenance(present[total_tag]),),
            )
        used: list[tuple[str, XbrlFact]] = []
        untagged_groups = 0
        for group in concept_def.component_groups:
            alternative = next((alt for alt in group if any(t in present for t in alt)), None)
            if alternative is None:
                untagged_groups += 1
                continue
            used.extend((t, present[t]) for t in alternative if t in present)
        if not used:
            return _missing(concept_def, period_label, period)
        reason = (
            f"{untagged_groups} of {len(concept_def.component_groups)} components of "
            f"{concept_def.concept} untagged -- treated as absent, not confirmed zero."
            if untagged_groups
            else None
        )
        if len(used) == 1:
            return fact(
                value=float(used[0][1].val),
                status=FactStatus.FOUND,
                confidence=Confidence.MEDIUM if untagged_groups else Confidence.HIGH,
                origin=Origin.REPORTED,
                provenance=(_xbrl_provenance(used[0][1]),),
                reason=reason,
            )
        return fact(
            value=float(sum(f.val for _, f in used)),
            status=FactStatus.DERIVED,
            confidence=Confidence.MEDIUM,
            origin=Origin.DERIVED,
            formula=" + ".join(t for t, _ in used),
            provenance=tuple(_xbrl_provenance(f) for _, f in used),
            reason=reason,
        )

    chosen_tag, chosen_fact = ordered[0]
    disagreeing = [(t, f) for t, f in ordered[1:] if not _values_agree(chosen_fact.val, f.val)]
    # Any differently-valued, differently-scoped tag stays visible, even one
    # too close to count as a disagreement: its value is still evidence.
    differing = [(t, f) for t, f in ordered[1:] if f.val != chosen_fact.val]
    confidence = Confidence.HIGH if chosen_tag == concept_def.xbrl_tags[0] else Confidence.MEDIUM
    if chosen_fact.is_extension:
        confidence = Confidence.LOW

    if disagreeing and concept_def.tag_resolution is TagResolution.ALTERNATES:
        return fact(
            value=None,
            status=FactStatus.CONFLICTING,
            confidence=Confidence.LOW,
            origin=Origin.REPORTED,
            provenance=(_xbrl_provenance(chosen_fact),),
            candidates=tuple(
                CandidateValue(value=f.val, provenance=_xbrl_provenance(f)) for _, f in ordered
            ),
            reason=(
                f"XBRL tags for {concept_def.concept} are declared synonyms but disagree for "
                f"{period_label}: {', '.join(f'{t}={f.val:,.0f}' for t, f in ordered)}."
            ),
        )

    if disagreeing or differing:  # PREFERRED_SCOPE: an expected difference, kept visible
        return fact(
            value=float(chosen_fact.val),
            status=FactStatus.FOUND,
            confidence=(
                Confidence.MEDIUM if disagreeing and confidence is Confidence.HIGH else confidence
            ),
            origin=Origin.REPORTED,
            provenance=(_xbrl_provenance(chosen_fact),),
            candidates=tuple(
                CandidateValue(value=f.val, provenance=_xbrl_provenance(f)) for _, f in differing
            ),
            reason=(
                f"{chosen_tag} preferred by scope; differently-scoped "
                f"{', '.join(t for t, _ in differing)} also reported and kept as candidates."
            ),
        )

    return fact(
        value=float(chosen_fact.val),
        status=FactStatus.FOUND,
        confidence=confidence,
        origin=Origin.REPORTED,
        provenance=(_xbrl_provenance(chosen_fact),),
    )


def _try_derivation(
    concept_def: ConceptDefinition,
    period_label: str,
    period: Period,
    resolved: dict[tuple[str, str], CanonicalFact],
) -> CanonicalFact | None:
    """The first derivation rule whose inputs are all resolved, or None."""
    for rule in concept_def.derivations:
        inputs: dict[str, float] = {}
        for name in rule.inputs:
            input_fact = resolved.get((name, period_label))
            if input_fact is None or input_fact.effective_value is None:
                break
            inputs[name] = input_fact.effective_value
        else:
            return CanonicalFact(
                concept=concept_def.concept,
                statement=concept_def.statement,
                period=period,
                value=rule.compute(inputs),
                currency=REPORTING_CURRENCY,
                status=FactStatus.DERIVED,
                confidence=Confidence.MEDIUM,
                origin=Origin.DERIVED,
                formula=rule.formula,
                provenance=tuple(
                    p for name in rule.inputs for p in resolved[(name, period_label)].provenance
                ),
                derived_from=tuple(rule.inputs),
            )
    return None


def _missing(concept_def: ConceptDefinition, period_label: str, period: Period) -> CanonicalFact:
    if concept_def.xbrl_tags:
        reason = (
            f"No sufficiently reliable source found: none of "
            f"{', '.join(concept_def.xbrl_tags)} reported for {period_label}"
            + (", and derivation inputs were also unavailable." if concept_def.derivations else ".")
        )
    else:
        reason = (
            f"No direct XBRL tag exists for {concept_def.concept}, and derivation "
            f"inputs were unavailable for {period_label}."
        )
    return CanonicalFact(
        concept=concept_def.concept,
        statement=concept_def.statement,
        period=period,
        value=None,
        currency=REPORTING_CURRENCY,
        status=FactStatus.MISSING,
        confidence=Confidence.LOW,
        origin=Origin.REPORTED,
        reason=reason,
    )


#: Concepts a filing reports for periods *before* its presented statements:
#: a statement of equity opens with the equity balance three years back, and
#: a cash-flow statement opens with the prior year's cash. A period where only
#: these appear was never presented as a balance sheet.
_ROLL_FORWARD_CONCEPTS = frozenset(
    {"cash", "shareholders_equity", "noncontrolling_interest", "total_equity"}
)


def _presented_statements(
    resolved: dict[tuple[str, str], CanonicalFact],
) -> set[tuple[StatementType, str]]:
    """(statement, period) pairs the filing actually presented.

    Without this, every roll-forward opening balance created a full column of
    `MISSING` placeholders for a balance sheet that does not exist: the audit
    found 17 of 45 balance-sheet period slots in the golden set were such
    phantoms (no total assets at all), deflating completeness and handing
    Phase 6 periods it could never compute anything for. The real
    roll-forward facts are kept; only the fabricated gaps around them go.
    """
    return {
        (fact.statement, period_label)
        for (concept, period_label), fact in resolved.items()
        if concept not in _ROLL_FORWARD_CONCEPTS
    }


def resolve_filing(
    company_facts: dict[str, Any],
    *,
    cik: int,
    company: str,
    accession: str,
    form: str,
    filed: str,
    period_end: str,
) -> CanonicalFilingFacts:
    """Resolve every canonical concept, for every period, from one filing's
    own XBRL facts (point-in-time filtered by `accession`, per D-008).

    `period_end` is this filing's own declared fiscal period end (SEC's
    `reportDate` / `FilingRef.period`, e.g. "2025-12-31") -- it anchors which
    facts count as *this* filing's annual periods rather than one of the
    quarterly sub-periods a "selected quarterly data" footnote can tag under
    the same concept and accession (`periods.is_annual_period`).
    """
    facts = facts_for_accession(company_facts, accession)
    index = index_by_concept(facts)

    fiscal_year, fiscal_period = _filing_fiscal_context(facts)
    anchor = date.fromisoformat(period_end)
    fiscal_month_day = (anchor.month, anchor.day)

    resolved: dict[tuple[str, str], CanonicalFact] = {}
    periods_seen: dict[tuple[PeriodType, str], Period] = {}

    for concept_def in CONCEPT_DEFINITIONS:
        _resolve_direct_tags(concept_def, index, resolved, periods_seen, fiscal_month_day)

    # Derivation runs to a fixpoint rather than once: `total_liabilities`
    # derives from `total_equity`, which may itself be derived. A single pass
    # would make correctness depend on the declaration order of
    # CONCEPT_DEFINITIONS -- a silent ordering landmine.
    presented = _presented_statements(resolved)
    pending = [
        (concept_def, period_label, period)
        for concept_def in CONCEPT_DEFINITIONS
        for (period_nature, period_label), period in periods_seen.items()
        if period_nature is concept_def.period_nature
        and (concept_def.concept, period_label) not in resolved
    ]
    progressed = True
    while pending and progressed:
        progressed = False
        still_pending = []
        for concept_def, period_label, period in pending:
            derived = _try_derivation(concept_def, period_label, period, resolved)
            if derived is None:
                still_pending.append((concept_def, period_label, period))
            else:
                resolved[(concept_def.concept, period_label)] = derived
                progressed = True
        pending = still_pending
    # A MISSING placeholder is only meaningful inside a statement the filing
    # actually presented for that period; outside one it is a fabricated gap.
    for concept_def, period_label, period in pending:
        if (concept_def.statement, period_label) in presented:
            resolved[(concept_def.concept, period_label)] = _missing(
                concept_def, period_label, period
            )

    filing_facts = CanonicalFilingFacts(
        cik=cik,
        company=company,
        accession=accession,
        form=form,
        filed=filed,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        facts=tuple(resolved.values()),
    )
    return filing_facts.model_copy(update={"validations": run_validations(filing_facts)})


def _filing_fiscal_context(
    facts: tuple[XbrlFact, ...],
) -> tuple[int | None, FiscalPeriodLabel | None]:
    """The filing's own declared fiscal year/period (§27's per-filing header),
    read from whichever fact happens to carry it -- one filing reports one
    `fy`/`fp` pair across all its facts (golden_set.md §2)."""
    for fact in facts:
        if fact.fy is not None and fact.fp is not None:
            return fact.fy, fact.fp  # type: ignore[return-value]
    return None, None
