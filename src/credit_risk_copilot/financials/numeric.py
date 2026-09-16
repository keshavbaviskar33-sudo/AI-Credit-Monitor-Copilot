"""Numeric normalisation for raw financial-statement text (§10, §9).

XBRL's `val` is already a clean number -- this module exists for the other
two places raw text still has to become a number: reading a Phase 4 table
cell (upload path, reconciliation) and rendering a resolved value back into
the strings a filing might use (reconciliation's search key).

The one rule that matters more than any regex: **an unparseable or ambiguous
cell is never silently turned into zero.** "-", "N/A" and "12,400" are three
different situations and this module keeps them apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: Cells that mean "explicitly not a number", each for a different reason.
#: Collapsing these into 0 is exactly the fabrication §10 warns against.
_BLANK_MARKERS = {
    "-": "dash: zero, not applicable, or unavailable -- ambiguous, not zero",
    "—": "em dash: same ambiguity as a plain dash",
    "–": "en dash: same ambiguity as a plain dash",
    "n/a": "explicitly marked not applicable",
    "na": "explicitly marked not applicable",
    "nm": "marked 'not meaningful' (common for ratios, occasionally for raw figures)",
    "n/m": "marked 'not meaningful'",
}

#: A bare number, optionally with thousands separators and a decimal part.
_NUMBER_RE = re.compile(r"^\(?\s*\$?\s*-?[\d,]*\.?\d+\s*\)?$")

#: Multi-word scale phrases a units declaration ("$ in millions") may use.
_SCALE_WORDS: tuple[tuple[str, str], ...] = (
    ("thousands", "thousands"),
    ("millions", "millions"),
    ("billions", "billions"),
)


@dataclass(frozen=True)
class NumericParseResult:
    """The outcome of trying to read one table cell as a number.

    `value` is `None` whenever the cell was not a confidently-parsed number --
    check `is_blank_marker` to tell "explicitly ambiguous" from "just not a
    number at all" (e.g. a row label that landed in a numeric column).
    """

    value: Decimal | None
    is_negative_paren: bool = False
    is_blank_marker: bool = False
    reason: str | None = None


def parse_numeric(text: str) -> NumericParseResult:
    """Parse one table cell. Never returns 0 for an ambiguous or absent cell."""
    raw = text.strip()
    if not raw:
        return NumericParseResult(value=None, reason="empty cell")

    lowered = raw.lower().strip("*†‡ ")
    if lowered in _BLANK_MARKERS:
        return NumericParseResult(value=None, is_blank_marker=True, reason=_BLANK_MARKERS[lowered])

    cleaned = raw.replace("$", "").replace(",", "").strip()
    negative_paren = cleaned.startswith("(") and cleaned.endswith(")")
    if negative_paren:
        cleaned = cleaned[1:-1].strip()
    # A row label ("Total assets") must not silently parse as a number.
    if not _NUMBER_RE.match(raw.replace(",", "")):
        return NumericParseResult(value=None, reason="not a recognisable numeric format")

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return NumericParseResult(value=None, reason="not a recognisable numeric format")

    if negative_paren:
        value = -value
    return NumericParseResult(value=value, is_negative_paren=negative_paren)


def detect_scale(units_declaration: str | None) -> str | None:
    """Read a scale word out of a units declaration ("$ in millions, except
    per share amounts") -- the text `Table.context` carries (extraction.md §2a).
    Returns `None` rather than guessing "units" when nothing is stated;
    callers should treat that as unknown, not as confirmed unscaled.
    """
    if not units_declaration:
        return None
    lowered = units_declaration.lower()
    for word, scale in _SCALE_WORDS:
        if word in lowered:
            return scale
    return None


#: Multiplier from a stated scale to plain units.
SCALE_MULTIPLIERS: dict[str, int] = {
    "units": 1,
    "thousands": 1_000,
    "millions": 1_000_000,
    "billions": 1_000_000_000,
}


def render_candidates(value: float) -> set[str]:
    """How a filing might print `value` in a table cell.

    Used only by `reconciliation.py` to search for independent corroboration
    of an already-resolved XBRL value inside a document's own tables --
    never to parse a cell (that is `parse_numeric`'s job). Adapted from
    `scripts/table_extraction_spike.py`'s R-19 measurement, which established
    that filings vary both the scale (units/thousands/millions) and the
    decimal precision they print at, and that `Decimal` arithmetic is needed
    to scale exactly rather than drift onto values like 14133.399999999998.
    """
    out: set[str] = set()
    amount = Decimal(str(value))
    negative = amount < 0
    magnitude = abs(amount)

    for scale in (1, 1_000, 1_000_000):
        scaled = magnitude / Decimal(scale)
        if scaled != 0 and scaled < 1:
            continue
        for places in (0, 1, 2):
            quantised = scaled.quantize(Decimal(1).scaleb(-places))
            if quantised != scaled:
                continue
            rendered = f"{quantised:,.{places}f}"
            out.add(rendered)
            if negative:
                out.add(f"({rendered})")
                out.add(f"-{rendered}")
    return out
