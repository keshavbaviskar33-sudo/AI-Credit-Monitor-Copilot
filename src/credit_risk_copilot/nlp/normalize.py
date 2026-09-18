"""A matching view of filing text that does not move any character.

Patterns are written in plain lower-case ASCII. Filing text is not: it is full
of typographic quotes (`’`, `“`), en and em dashes, and non-breaking
spaces, and the same phrase appears with different ones in different filings.

The obvious fix -- normalise the text and match against that -- breaks SC-03,
because an offset into normalised text no longer indexes the document and the
quote can no longer be verified against the source. Unless the normalisation
is **length-preserving**, which is the whole design here: every substitution
maps exactly one character to exactly one character, so `match_view(text)` has
the same length as `text` and offset *i* means the same position in both.

That constraint is enforced by a test, not just documented, because a single
one-to-many mapping added later (a ligature, an ellipsis, a fraction) would
silently shift every quote after it in the document.
"""

from __future__ import annotations

#: One character to one character, always. Anything needing a different length
#: does not belong here -- it belongs in the pattern.
_SUBSTITUTIONS = {
    # Quotes and apostrophes.
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "´": "'",
    "`": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "″": '"',
    # Dashes and hyphens.
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    # Spaces.
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "﻿": " ",
    # Bullets, which filings use as clause separators inside a block.
    "•": "-",
    "·": "-",
}

_TABLE = str.maketrans(_SUBSTITUTIONS)


def match_view(text: str) -> str:
    """Lower-cased, punctuation-normalised, **same length** as `text`.

    Use this for every regex in `nlp/`, and slice the *original* text for every
    quote. `len(match_view(t)) == len(t)` for all `t`.

    `str.lower` is *almost* length-preserving, and the exception is real rather
    than theoretical: `"İ".lower()` (Latin capital I with dot above, which
    turns up in Turkish company and place names) returns two characters. One
    such character anywhere in a 10-K would shift every quote after it by one,
    producing evidence that is subtly and invisibly wrong -- exactly the
    failure SC-03 exists to make impossible. So the fast path is taken only
    when it is verified not to have changed the length.
    """
    translated = text.translate(_TABLE)
    lowered = translated.lower()
    if len(lowered) == len(translated):
        return lowered
    return "".join(_safe_lower(character) for character in translated)


def _safe_lower(character: str) -> str:
    """Lower-case one character, or keep it if lowering would resize it."""
    lowered = character.lower()
    return lowered if len(lowered) == 1 else character
