"""Multi-filing, multi-period aggregation (§27): a company across fiscal years.

A single `CanonicalFilingFacts` is what one filing reported. Monitoring needs
a company's whole history, and D-008's as-filed rule makes that more than a
merge: for a given (concept, period), several filings can carry a value for
the same period -- the year it was first reported, and again as a comparative
column in the next year or two's 10-K, possibly restated. The point-in-time
rule says the *first-filed* value is the one an "as of that time" assessment
must use; a restatement is real information, not noise, so it is surfaced
rather than silently overwritten (§16, §19).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.financials.models import CanonicalFact, CanonicalFilingFacts


class Restatement(BaseModel):
    """A later filing reported a different value for a period an earlier
    filing already reported -- both are kept, matching every other conflict
    representation in this schema."""

    model_config = ConfigDict(frozen=True)

    concept: str
    period_label: str
    original: CanonicalFact
    restated: tuple[CanonicalFact, ...]


class CompanyFinancials(BaseModel):
    """One company's canonical facts across every filing processed for it."""

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    filings: tuple[CanonicalFilingFacts, ...]

    @property
    def _by_filed_date(self) -> tuple[CanonicalFilingFacts, ...]:
        return tuple(sorted(self.filings, key=lambda f: f.filed))

    def as_of(self, cutoff: date) -> dict[tuple[str, str], CanonicalFact]:
        """The as-filed view for every (concept, period_label): the value
        from the *earliest* filing filed on or before `cutoff` that resolved
        it. Later filings' comparative restatements of the same period are
        never used here (D-008) -- see `restatements` to see them at all.
        """
        result: dict[tuple[str, str], CanonicalFact] = {}
        for filing in self._by_filed_date:
            if date.fromisoformat(filing.filed) > cutoff:
                continue
            for fact in filing.facts:
                if not fact.is_resolved:
                    continue
                key = (fact.concept, fact.period.label)
                if key not in result:
                    result[key] = fact
        return result

    def restatements(self) -> tuple[Restatement, ...]:
        """Every (concept, period) where a later filing's own reported value
        disagrees with the value an earlier filing reported for that same
        period -- made visible, never resolved automatically (§16)."""
        by_key: dict[tuple[str, str], list[CanonicalFact]] = {}
        for filing in self._by_filed_date:
            for fact in filing.facts:
                if fact.status.value != "found" or fact.value is None:
                    continue
                by_key.setdefault((fact.concept, fact.period.label), []).append(fact)

        found: list[Restatement] = []
        for (concept, period_label), facts in by_key.items():
            if len(facts) < 2:
                continue
            original, *rest = facts
            differing = tuple(f for f in rest if f.value != original.value)
            if differing:
                found.append(
                    Restatement(
                        concept=concept,
                        period_label=period_label,
                        original=original,
                        restated=differing,
                    )
                )
        return tuple(found)
