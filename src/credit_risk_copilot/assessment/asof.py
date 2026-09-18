"""The point-in-time gate (FR-05), enforced rather than assumed.

An assessment "as of 2015-03-02" is worth exactly as much as the guarantee
that nothing in it was known after 2015-03-02. Phase 8 learned this the
expensive way and ended up with three independent enforcement layers on the
training panel (D-026); this module is the same discipline applied at the
product boundary, where a user -- not a script -- picks the date.

## Why a gate object and not a filter call

The tempting shape is "filter the filings before you start", and it is the
shape that fails. By the time four layers have each fetched what they need,
the assessment contains a model explanation stamped with a prediction date, a
narrative report stamped with an accession, and a health report built from a
window of filings nobody kept a list of. A filter at the top cannot see any of
that. `AsOfGate.verify` runs at the *bottom*, over the assembled evidence, and
asks every item for its filing date -- so a layer that fetched too much is
caught by the assessment it produced, not by the discipline of its caller.

## Undated evidence fails closed

`verify` rejects an evidence item with no `filed` date instead of admitting it.
An item with no provenance is precisely the shape leakage takes -- a value that
arrived from somewhere nobody recorded -- and a gate that waves those through
guarantees only the filings it could see. The cost of failing closed is that a
new evidence kind must state its filing date to pass, which is the requirement,
not an inconvenience.

## The date that counts is the filing date

Not the fiscal period end. A company's FY2014 figures are not public on
2014-12-31; they are public when the 10-K is accepted, often two or three
months later, and a backtest that uses the period end is reading the future by
a quarter. Every comparison here is against `filed`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from credit_risk_copilot.assessment.models import EvidenceItem


class AsOfViolation(AssertionError):
    """Evidence dated after the assessment's as-of date reached the assembly.

    An `AssertionError` subclass for the same reason `LeakageError` is one in
    `modeling/contract.py`: this is a broken invariant, not a recoverable
    condition, and code that catches it broadly is code that has decided to
    ship a leaking backtest.
    """


@dataclass(frozen=True)
class AsOfGate:
    """Admits information available on `as_of` and nothing later."""

    as_of: date
    #: When False, evidence with no filing date is admitted. Off by default and
    #: intended only for unit tests of layers that legitimately have no filing
    #: behind them; production assembly never sets it.
    require_filed: bool = True

    def admits(self, filed: date | None) -> bool:
        if filed is None:
            return not self.require_filed
        return filed <= self.as_of

    def verify(self, items: Sequence[EvidenceItem]) -> None:
        """Raise on the first evidence that could not have been known.

        The message names the offending item, its date and the gap, because a
        leakage failure discovered in a 200-item assessment is unactionable
        without knowing which layer produced it.
        """
        for item in items:
            if self.admits(item.filed):
                continue
            if item.filed is None:
                raise AsOfViolation(
                    f"{item.evidence_id} ({item.layer.value}/{item.kind.value}) carries no"
                    f" filing date, so it cannot be shown to predate {self.as_of.isoformat()}"
                )
            raise AsOfViolation(
                f"{item.evidence_id} ({item.layer.value}/{item.kind.value}) was filed"
                f" {item.filed.isoformat()}, {(item.filed - self.as_of).days} day(s) after the"
                f" as-of date {self.as_of.isoformat()}"
            )

    def admissible(self, items: Sequence[EvidenceItem]) -> tuple[EvidenceItem, ...]:
        """The subset that predates `as_of`.

        Offered for callers assembling a replay from a cached superset of
        evidence. It is not what `assemble_assessment` uses: silently dropping
        an item there would hide a layer that over-fetched, and the point of
        this module is that such a layer is a defect to surface.
        """
        return tuple(item for item in items if self.admits(item.filed))
