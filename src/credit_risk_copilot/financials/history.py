"""Assembling one company's whole filing history into `CompanyFinancials`.

`resolver.resolve_filing` answers "what did *this* filing report".
`CompanyFinancials.as_of` answers "what was known by date T", given several
resolved filings. This module is the missing middle: it turns a company's
cached `companyfacts` payload plus its list of annual filings into those
resolved filings, and reports exactly which accessions it could not use and
why -- because a silently dropped filing is a silently missing year of
history, and Phase 8 builds features out of those years.

## Why the diagnostics are part of the return value

The Phase 8 data audit needs to distinguish three very different reasons a
filing contributes nothing:

- the accession carries no facts in `companyfacts` at all (common for
  pre-2011 filings, from the XBRL phase-in);
- the filing's own `reportDate` is absent or unparseable, so there is no
  anchor to decide which facts are its annual periods (`periods.is_annual_period`);
- the resolver ran but resolved nothing usable.

Collapsing those into "fewer filings than expected" would make a data-coverage
problem look like a code problem, or worse, the reverse.

## What this module deliberately does *not* do

It does not fetch. It takes an already-loaded `companyfacts` payload and an
already-listed sequence of filing references, so it stays testable offline and
usable from cached data. `SecEdgarClient.annual_filings()` produces exactly the
sequence shape it wants, but this module never imports it -- the reference is
structurally typed, the same way `ratios/engine.py` structurally types its
Phase 5 input.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.financials.company import CompanyFinancials
from credit_risk_copilot.financials.models import CanonicalFilingFacts
from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.financials.xbrl import iter_facts


class FilingRefLike(Protocol):
    """Structurally `sec_edgar.FilingRef` -- named rather than imported so
    `financials/` keeps its independence from the HTTP client."""

    @property
    def cik(self) -> int: ...

    @property
    def accession(self) -> str: ...

    @property
    def form(self) -> str: ...

    @property
    def filed(self) -> str: ...

    @property
    def period(self) -> str: ...


class SkippedFiling(BaseModel):
    """One accession that could not become a `CanonicalFilingFacts`, and why."""

    model_config = ConfigDict(frozen=True)

    accession: str
    form: str
    filed: str
    #: `no_xbrl_facts` | `no_period_end` | `resolver_error` | `no_periods_resolved`
    reason_code: str
    message: str


class CompanyHistory(BaseModel):
    """A company's resolved filing history plus the diagnostics behind it."""

    model_config = ConfigDict(frozen=True)

    financials: CompanyFinancials
    skipped: tuple[SkippedFiling, ...]

    @property
    def resolved_count(self) -> int:
        return len(self.financials.filings)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def skip_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.skipped:
            counts[entry.reason_code] = counts.get(entry.reason_code, 0) + 1
        return dict(sorted(counts.items()))


def accessions_with_facts(company_facts: dict[str, Any]) -> frozenset[str]:
    """Every accession that appears on at least one fact in the payload.

    `companyfacts` only carries facts from filings SEC actually rendered XBRL
    for. A company's `submissions` index lists 10-Ks going back decades; the
    ones before its XBRL phase-in have no facts here at all, and asking the
    resolver for them would return an empty filing rather than an error.
    """
    return frozenset(fact.accn for fact in iter_facts(company_facts) if fact.accn)


def resolve_company_history(
    company_facts: dict[str, Any],
    filings: Sequence[FilingRefLike],
    *,
    cik: int,
    company: str,
    filed_on_or_before: str | None = None,
) -> CompanyHistory:
    """Resolve every filing in `filings` that `company_facts` can support.

    `filed_on_or_before` (an ISO date string) drops filings SEC received after
    it, *before* any resolution happens. This is the point-in-time gate at its
    earliest possible point: a filing excluded here can never contribute a
    fact, a period or a provenance entry to anything downstream, which is a
    stronger guarantee than filtering the resulting facts (D-008).

    Filings are returned in `filed` order. A duplicate accession is resolved
    once.
    """
    available = accessions_with_facts(company_facts)
    resolved: list[CanonicalFilingFacts] = []
    skipped: list[SkippedFiling] = []
    seen: set[str] = set()

    for ref in sorted(_eligible(filings, filed_on_or_before), key=lambda r: (r.filed, r.accession)):
        if ref.accession in seen:
            continue
        seen.add(ref.accession)

        if ref.accession not in available:
            skipped.append(
                SkippedFiling(
                    accession=ref.accession,
                    form=ref.form,
                    filed=ref.filed,
                    reason_code="no_xbrl_facts",
                    message=(
                        "No fact in companyfacts carries this accession -- the filing predates "
                        "this filer's XBRL phase-in or was never rendered."
                    ),
                )
            )
            continue

        if not ref.period:
            skipped.append(
                SkippedFiling(
                    accession=ref.accession,
                    form=ref.form,
                    filed=ref.filed,
                    reason_code="no_period_end",
                    message=(
                        "Filing has no reportDate, so there is no fiscal anchor to decide which "
                        "of its facts are annual periods."
                    ),
                )
            )
            continue

        try:
            filing = resolve_filing(
                company_facts,
                cik=cik,
                company=company,
                accession=ref.accession,
                form=ref.form,
                filed=ref.filed,
                period_end=ref.period,
            )
        except (ValueError, KeyError, TypeError) as exc:
            skipped.append(
                SkippedFiling(
                    accession=ref.accession,
                    form=ref.form,
                    filed=ref.filed,
                    reason_code="resolver_error",
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        if not filing.period_labels:
            skipped.append(
                SkippedFiling(
                    accession=ref.accession,
                    form=ref.form,
                    filed=ref.filed,
                    reason_code="no_periods_resolved",
                    message=(
                        "The accession carries facts but none resolved to an annual period for "
                        "this filing's fiscal anchor."
                    ),
                )
            )
            continue

        resolved.append(filing)

    return CompanyHistory(
        financials=CompanyFinancials(cik=cik, company=company, filings=tuple(resolved)),
        skipped=tuple(skipped),
    )


def _eligible(
    filings: Sequence[FilingRefLike], filed_on_or_before: str | None
) -> Iterable[FilingRefLike]:
    if filed_on_or_before is None:
        return filings
    # ISO dates compare correctly as strings, and `filed` is always ISO here
    # (SEC's `filingDate`), so this avoids parsing thousands of dates.
    return [ref for ref in filings if ref.filed <= filed_on_or_before]
