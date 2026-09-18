"""Sentence segmentation over filing text, as spans rather than strings.

Everything here returns offsets into the original document. A segmenter that
returned cleaned strings would make SC-03 unverifiable -- you cannot check a
quote against the source if the quote has been reformatted on the way out.

## Why not an off-the-shelf sentence splitter

`nltk`/`spaCy`/`pysbd` would each be a heavy dependency, and none of them is
tuned for the two things that actually break segmentation in a 10-K:

1. **Tabular text.** `html_extractor` mirrors table cells into the document
   text so Item 8 is not empty and so quotes stay locatable. Item 7 is full of
   them. A tab-joined row of figures is not prose, and running a sentence
   splitter over it produces "quotes" that are strings of numbers.
2. **Money and legal citations.** "$1.5 million." and "Item 1A." and "No. 2015-01"
   all end in a period that is not a sentence boundary, and they are far more
   common here than the honorifics a general-purpose splitter is tuned for.

The rules below are short, inspectable and testable, which matters more than
linguistic completeness for a layer whose output must be defensible sentence by
sentence. A-15 also commits this project to rules and classical methods first.
"""

from __future__ import annotations

import re

#: A line holding a tab came from a table row (`html_extractor` joins cells
#: with tabs). Prose never does.
_TABULAR = "\t"

#: Below this a "sentence" is a heading fragment, a page number or a stray
#: cell, never a statement worth quoting to an analyst.
MIN_SENTENCE_CHARS = 25

#: Above this the "sentence" is almost always an unpunctuated run of a filing's
#: list items or a table that escaped the tab check. Quoting 4,000 characters
#: at an analyst is not evidence, it is a document.
MAX_SENTENCE_CHARS = 1_200

#: Tokens ending in a period that do not end a sentence. Deliberately short:
#: every entry is one this corpus actually contains, and a long speculative
#: list would be untestable. Matched case-insensitively against the word
#: immediately before the period.
_ABBREVIATIONS = frozenset(
    {
        # Corporate forms, which end a great many filing sentences' subjects.
        "inc",
        "corp",
        "co",
        "ltd",
        "llc",
        "lp",
        "llp",
        "plc",
        "sa",
        "nv",
        "ag",
        # Citations and cross references -- the biggest single source of false
        # boundaries in a 10-K.
        "no",
        "nos",
        "art",
        "sec",
        "reg",
        "para",
        "pp",
        "vs",
        "cf",
        "ch",
        # Units and quantities.
        "approx",
        "mm",
        "bn",
        "mtpa",
        "cwt",
        # Geography and government, heavily used in risk factors.
        "us",
        "u.s",
        "uk",
        "u.k",
        "eu",
        "st",
        "mt",
        "ft",
        # Dates.
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sept",
        "sep",
        "oct",
        "nov",
        "dec",
    }
)

#: The word (letters, digits and interior dots) immediately before a period.
_PRECEDING_TOKEN = re.compile(r"([A-Za-z][A-Za-z.]*|\d+)$")

#: A candidate boundary: sentence-ending punctuation, then whitespace, then
#: something that can begin a sentence. Requiring the *next* character to be an
#: opening quote, a digit or an upper-case letter removes "$1.5 million" and
#: "Section 7.2" without needing to understand either.
_BOUNDARY = re.compile(r'[.!?]["”’)]?\s+(?=["“‘(]?[A-Z0-9])')


def _is_false_boundary(text: str, period_index: int) -> bool:
    """Whether the punctuation at `period_index` is not a sentence end."""
    if text[period_index] != ".":
        return False  # "!" and "?" are not used in abbreviations here

    before = text[:period_index]
    match = _PRECEDING_TOKEN.search(before)
    if match is None:
        return False
    token = match.group(0)

    if token.isdigit():
        # A numbered list marker ("1. We operate...") only at the start of a
        # line. Anywhere else a digit before a period is overwhelmingly a year
        # ending a sentence -- "...at the close of business on January 23,
        # 2026." -- and treating those as false boundaries fuses two sentences
        # into one. That is not cosmetic: it let a dividend *declaration* and
        # the phrase "349th consecutive quarterly dividend" land in the same
        # sentence, where a pattern meant for dividend cuts matched them.
        return match.start() == 0
    # A single initial: "J. Smith", "U. S."
    if len(token) == 1 and token.isalpha():
        return True
    return token.rstrip(".").lower() in _ABBREVIATIONS


def split_sentences(text: str, offset: int = 0) -> tuple[tuple[int, int], ...]:
    """Sentence spans in `text`, as `(start, end)` offsets shifted by `offset`.

    `offset` exists so a caller can segment one section sliced out of a
    document and still receive spans that index the *document*, which is what
    an `EvidenceQuote` has to carry.

    Line breaks are always boundaries: `html_extractor` emits one line per
    block element, so a newline is the document's own paragraph break and is
    more reliable than any punctuation rule.
    """
    spans: list[tuple[int, int]] = []

    for line_start, line in _lines(text):
        if _TABULAR in line:
            continue
        for start, end in _split_line(line):
            piece = line[start:end].strip()
            if not piece:
                continue
            # Re-derive the trimmed span so the quote has no leading or
            # trailing whitespace, while still indexing the original text.
            lead = len(line[start:end]) - len(line[start:end].lstrip())
            absolute = offset + line_start + start + lead
            spans.append((absolute, absolute + len(piece)))

    return tuple(
        (start, end)
        for start, end in spans
        if MIN_SENTENCE_CHARS <= end - start <= MAX_SENTENCE_CHARS
    )


def _lines(text: str) -> list[tuple[int, str]]:
    """Every line with its start offset, keeping empty lines out."""
    out: list[tuple[int, str]] = []
    position = 0
    for line in text.split("\n"):
        if line.strip():
            out.append((position, line))
        position += len(line) + 1
    return out


def _split_line(line: str) -> list[tuple[int, int]]:
    """Sentence spans within one line, using the punctuation rules."""
    cuts: list[int] = []
    for match in _BOUNDARY.finditer(line):
        if _is_false_boundary(line, match.start()):
            continue
        cuts.append(match.end())

    spans: list[tuple[int, int]] = []
    previous = 0
    for cut in cuts:
        spans.append((previous, cut))
        previous = cut
    spans.append((previous, len(line)))
    return spans
