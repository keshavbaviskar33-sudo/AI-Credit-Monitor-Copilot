"""Typed reading of SEC's `companyfacts` XBRL payload (§12).

`SecEdgarClient.company_facts()` returns the raw JSON untouched -- this module
is where it becomes typed facts. Two things this deliberately gets right
because getting them wrong would corrupt everything downstream:

- **Point-in-time filtering by accession**, not by date. `companyfacts`
  accumulates every value SEC has ever seen for a concept, including what
  later filings restated. Filtering on `accn` (as `build_golden_set.py`
  already does for the golden set) returns exactly what *one filing*
  reported -- its own comparatives included -- which is what D-008 requires
  and what a document extractor of that same filing would find.
- **Not treating XBRL as automatically correct.** This module only reads the
  facts faithfully; `is_extension` flags anything outside the standard
  taxonomies so `resolver.py` can treat it with appropriately less trust.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict

#: Taxonomies SEC's own filer support treats as standard. Anything else
#: (typically a company's own ticker-prefixed namespace) is a genuine
#: extension concept -- rare in the golden set (none of its 12 filings use
#: one), but real for smaller/older filers, and §12 asks it to be tracked
#: rather than assumed away.
STANDARD_NAMESPACES = frozenset({"us-gaap", "dei", "srt", "ecd", "ffd", "invest", "ifrs-full"})


class XbrlFact(BaseModel):
    """One entry from one concept's `units` array in `companyfacts`."""

    model_config = ConfigDict(frozen=True)

    namespace: str
    concept: str
    unit: str
    val: float
    start: str | None
    end: str | None
    fy: int | None
    fp: str | None
    form: str | None
    filed: str | None
    accn: str | None
    frame: str | None = None

    @property
    def is_extension(self) -> bool:
        return self.namespace not in STANDARD_NAMESPACES


def iter_facts(company_facts: dict[str, Any]) -> Iterator[XbrlFact]:
    """Every fact in a `companyfacts` payload, across every namespace."""
    facts = company_facts.get("facts", {})
    for namespace, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept, concept_data in concepts.items():
            units = concept_data.get("units", {})
            for unit, entries in units.items():
                for entry in entries:
                    yield XbrlFact(
                        namespace=namespace,
                        concept=concept,
                        unit=unit,
                        val=entry["val"],
                        start=entry.get("start"),
                        end=entry.get("end"),
                        fy=entry.get("fy"),
                        fp=entry.get("fp"),
                        form=entry.get("form"),
                        filed=entry.get("filed"),
                        accn=entry.get("accn"),
                        frame=entry.get("frame"),
                    )


def facts_for_accession(company_facts: dict[str, Any], accession: str) -> tuple[XbrlFact, ...]:
    """Only the facts filed under `accession` -- what that filing reported,
    comparatives included (D-008)."""
    return tuple(f for f in iter_facts(company_facts) if f.accn == accession)


def index_by_concept(
    facts: tuple[XbrlFact, ...],
) -> dict[tuple[str, str], list[XbrlFact]]:
    """Group facts by `(namespace, concept)` for fallback-chain lookups."""
    index: dict[tuple[str, str], list[XbrlFact]] = {}
    for fact in facts:
        index.setdefault((fact.namespace, fact.concept), []).append(fact)
    return index
