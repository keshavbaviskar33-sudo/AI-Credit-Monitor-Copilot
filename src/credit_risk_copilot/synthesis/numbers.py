"""Deciding whether a number in a sentence is a number in the evidence.

This is the load-bearing half of FR-17. "Claims that contain numbers not
present in the evidence are detected by code" sounds like a set membership
test and is not one, because the evidence holds `0.9302` and the draft writes
"93%", "0.93", "roughly 93 percent" or "$199.5 million". A validator that
demands an exact float match rejects every correct draft; one that matches
loosely accepts a fabricated figure that happens to land near a real one.

Three rules do the work.

**Precision comes from the claim, not from a tolerance constant.** A claim
written to two decimals is checked to two decimals: `0.93` matches a stored
`0.9302` because rounding the evidence to the claim's own precision gives
`0.93`, and `0.94` does not. The admissible gap is half a unit in the last
place the *writer* chose to state -- which is what "this number is in the
evidence" means when someone rounds. No epsilon is invented anywhere in this
module.

**A literal can mean more than one thing, so every reading is tried.** "22%"
is `22.0` in a percentile field and `0.22` as a rate, and this layer cannot
know which; both readings are offered and the claim is grounded if either
matches. That is deliberately permissive in one direction only -- it never
invents a *value*, only the scale a human would have read the same glyphs at.

**Anything the evidence literally writes is quotable.** A fiscal period
(`FY2014`), a filing count, an accession -- these are text in a summary, not
floats in `numbers`, and a draft that repeats them is grounded. Checking the
surface form against the cited evidence's own text covers them without
loosening the numeric rule at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Scale words a filing's prose actually uses. `bn`/`m` are included because
#: analysts write them; `lakh`/`crore` are not, because SEC filings do not.
SCALE_WORDS: dict[str, float] = {
    "hundred": 1e2,
    "thousand": 1e3,
    "k": 1e3,
    "million": 1e6,
    "m": 1e6,
    "mm": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
}

#: One numeric literal, with whatever decorates it: an optional currency mark,
#: digits with optional thousands separators, an optional decimal part, an
#: optional scale word, and an optional percent sign. Unicode minus and en
#: dash are accepted because a model writing financial prose uses them.
_LITERAL = re.compile(
    r"""
    (?P<currency>[$€£])?\s*
    (?P<sign>[-+−–])?\s*
    (?P<digits>\d{1,3}(?:,\d{3})+|\d+)
    (?:\.(?P<decimals>\d+))?
    \s*
    (?P<scale>hundred|thousand|million|billion|trillion|bn|mm|[kmb])?
    \s*
    (?P<percent>%|\spercent|\spct)?
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Citation mechanics. Masked before the numeric scan so `EV-MS-77ca0e19` does
#: not contribute a stray `19`, and *not* checked against the evidence text:
#: whether an ID is real is the citation check's job, not this module's.
_CITATION_TOKEN = re.compile(r"EV-[A-Z]{2}-[0-9a-f]{8}", re.IGNORECASE)

#: Identifiers that are factual claims about the filing -- a fiscal period, an
#: accession. They are not quantities, so they are masked from the numeric
#: scan, but they *are* assertions, so they are checked against the cited
#: evidence's own text. Without this, "over FY2011" against an FY2014 filing
#: would pass unexamined, which is a fabrication the numeric path cannot see.
_FACT_TOKEN = re.compile(
    r"\b\d{10}-\d{2}-\d{6}\b|\bFY\s?\d{4}\b|\bQ[1-4]\s?\d{4}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumberMention:
    """One numeric literal found in a draft, and what it could mean.

    `readings` is ordered from the most literal interpretation outward. A
    mention is grounded when *any* reading matches, which is why the tolerance
    has to be per-reading: `22%` read as `0.22` admits half a unit in the last
    decimal place of `0.22`, not of `22`.
    """

    text: str
    start: int
    end: int
    #: `(value, half_ulp)` pairs -- the candidate value and the largest gap
    #: that still counts as the same number at the precision written.
    readings: tuple[tuple[float, float], ...]

    def matches(self, value: float) -> bool:
        return any(abs(value - reading) <= tolerance for reading, tolerance in self.readings)


def _half_ulp(decimals: int, scale: float) -> float:
    """Half a unit in the last place the writer stated.

    `1.42` admits 0.005; `1.4` admits 0.05; `199.5 million` admits 50,000. An
    integer with no decimal part admits 0.5, which is what rounding to a whole
    number means -- and is why a claim of "37 filings" matches a stored 37.0
    and not a stored 37.6.
    """
    return 0.5 * (10.0**-decimals) * scale


def mentions(text: str) -> tuple[NumberMention, ...]:
    """Every numeric literal in `text`, with its candidate readings.

    Evidence IDs, accession numbers and fiscal period labels are masked first:
    they are checked as *strings* against the cited evidence, and letting their
    digits through here would ground a fabricated figure on the coincidence of
    an ID's hex tail.
    """
    masked = _CITATION_TOKEN.sub(lambda m: " " * len(m.group(0)), text)
    masked = _FACT_TOKEN.sub(lambda m: " " * len(m.group(0)), masked)
    found: list[NumberMention] = []

    for match in _LITERAL.finditer(masked):
        digits = match.group("digits").replace(",", "")
        decimals = match.group("decimals") or ""
        magnitude = float(f"{digits}.{decimals}") if decimals else float(digits)
        if match.group("sign") in ("-", "−", "–"):
            magnitude = -magnitude

        scale_word = (match.group("scale") or "").strip().lower()
        scale = SCALE_WORDS.get(scale_word, 1.0)
        places = len(decimals)

        readings: list[tuple[float, float]] = [
            (magnitude * scale, _half_ulp(places, scale)),
        ]
        if scale != 1.0:
            # "$199.5 million" is 199,500,000 in a raw field and 199.5 in a
            # field already denominated in millions -- filings use both.
            readings.append((magnitude, _half_ulp(places, 1.0)))
        if match.group("sign") is None:
            # An unsigned literal carries its direction in the verb: "fell
            # 0.31" restates a stored -0.31 correctly. This is the one
            # deliberate permissiveness in the module -- it also grounds "the
            # change was 0.31" against -0.31 -- and it is accepted because
            # rejecting it would fail on ordinary correct prose, while the
            # magnitude itself still has to be real.
            readings.append((-magnitude * scale, _half_ulp(places, scale)))
        if match.group("percent"):
            # "22%" is 22.0 where the evidence stores a percentile and 0.22
            # where it stores a rate. Both are offered; neither is invented.
            readings.append((magnitude * scale / 100.0, _half_ulp(places + 2, scale)))

        found.append(
            NumberMention(
                text=match.group(0).strip(),
                start=match.start(),
                end=match.end(),
                readings=tuple(readings),
            )
        )
    return tuple(found)


def fact_tokens(text: str) -> frozenset[str]:
    """Fiscal periods and accessions asserted in `text`.

    Facts the evidence states in words rather than in `numbers`. Extracted
    separately so the numeric path never has to loosen to accommodate them,
    and checked as strings because that is what they are.
    """
    return frozenset(
        " ".join(match.group(0).upper().split()) for match in _FACT_TOKEN.finditer(text)
    )


def ungrounded(text: str, values: frozenset[float], evidence_text: str) -> tuple[str, ...]:
    """The literals in `text` that no supplied value or evidence text supports.

    `values` are the floats the cited evidence carries; `evidence_text` is the
    concatenated prose of those same items. A literal passes if it matches a
    value at its own precision, or if the evidence writes those characters
    itself -- the second clause is what lets a draft say "3 of 4 ratios" when
    the summary said exactly that and no ratio count was ever a float.
    """
    normalised = " ".join(evidence_text.split())
    failures: list[str] = []
    for mention in mentions(text):
        if any(mention.matches(value) for value in values):
            continue
        if mention.text and mention.text in normalised:
            continue
        failures.append(mention.text)

    available = fact_tokens(normalised)
    failures.extend(token for token in sorted(fact_tokens(text)) if token not in available)
    return tuple(failures)
