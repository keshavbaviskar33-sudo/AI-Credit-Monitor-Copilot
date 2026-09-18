"""Sentence segmentation, including the cases that produced real defects.

The regression tests here are built from filings in the Phase 4 golden set, not
invented: the year-boundary test reproduces the exact Pfizer sentence pair that
a too-eager numeric rule fused into one.
"""

from __future__ import annotations

from credit_risk_copilot.nlp.segment import (
    MAX_SENTENCE_CHARS,
    MIN_SENTENCE_CHARS,
    split_sentences,
)


def _texts(text: str, offset: int = 0) -> list[str]:
    return [text[start - offset : end - offset] for start, end in split_sentences(text, offset)]


class TestSpansIndexTheSource:
    def test_every_span_slices_back_to_its_own_text(self) -> None:
        text = (
            "We were not in compliance with the leverage covenant at year end. "
            "Our lenders granted a waiver in February."
        )
        for start, end in split_sentences(text):
            assert text[start:end].strip() == text[start:end]

    def test_an_offset_shifts_every_span(self) -> None:
        text = "We breached the covenant during the year ended December 31, 2015. " * 2
        plain = split_sentences(text)
        shifted = split_sentences(text, offset=1000)

        assert [(s + 1000, e + 1000) for s, e in plain] == list(shifted)

    def test_spans_carry_no_surrounding_whitespace(self) -> None:
        text = "   We breached the covenant during the year ended December 2015.   "
        for start, end in split_sentences(text):
            assert not text[start:end].startswith(" ")
            assert not text[start:end].endswith(" ")


class TestBoundaries:
    def test_a_year_ends_a_sentence(self) -> None:
        """The Pfizer defect. A bare number before a period was treated as a
        list marker everywhere, so a sentence ending in a date fused with the
        next one -- and a dividend declaration merged with the words
        "consecutive quarterly dividend"."""
        text = (
            "The dividend is payable to shareholders of record at the close of business "
            "on January 23, 2026. The first-quarter 2026 cash dividend will be our 349th "
            "consecutive quarterly dividend."
        )
        sentences = _texts(text)

        assert len(sentences) == 2
        assert sentences[0].endswith("2026.")
        assert sentences[1].startswith("The first-quarter")

    def test_a_numbered_list_marker_at_line_start_does_not_split(self) -> None:
        text = "1. The Company operates in a single reportable segment across the region."
        assert len(split_sentences(text)) == 1

    def test_a_corporate_suffix_does_not_split(self) -> None:
        text = (
            "The obligations are guaranteed by Peabody Investments Corp. and its "
            "subsidiaries under the credit agreement."
        )
        assert len(split_sentences(text)) == 1

    def test_a_money_amount_does_not_split(self) -> None:
        text = "We recorded an impairment charge of $1.5 million during the year ended 2015."
        assert len(split_sentences(text)) == 1

    def test_a_line_break_always_ends_a_sentence(self) -> None:
        """`html_extractor` emits one line per block element, so a newline is
        the document's own paragraph break -- more reliable than punctuation."""
        text = (
            "There exists substantial doubt about our ability to continue\n"
            "We obtained a waiver from our lenders in February of that year"
        )
        assert len(_texts(text)) == 2


class TestNonProse:
    def test_a_tabular_line_is_not_segmented(self) -> None:
        """Table cells are mirrored into the document text so Item 8 is not
        empty. They are not prose, and quoting a row of figures at an analyst
        is not evidence."""
        text = "Total debt\t1,240\t2,180\t3,004\tand more columns of figures here"
        assert split_sentences(text) == ()

    def test_prose_beside_a_table_still_segments(self) -> None:
        text = (
            "Revenue\t100\t200\n"
            "We were not in compliance with the fixed charge coverage ratio covenant."
        )
        sentences = _texts(text)

        assert len(sentences) == 1
        assert sentences[0].startswith("We were not")

    def test_a_fragment_shorter_than_the_floor_is_dropped(self) -> None:
        assert split_sentences("Going Concern") == ()
        assert all(
            end - start >= MIN_SENTENCE_CHARS
            for start, end in split_sentences("Going Concern. " + "x" * 80)
        )

    def test_an_unpunctuated_run_longer_than_the_ceiling_is_dropped(self) -> None:
        assert split_sentences("word " * 400) == ()

    def test_the_ceiling_and_floor_bound_every_emitted_span(self) -> None:
        text = (
            "We were not in compliance with the leverage covenant. "
            + "The Company continued to evaluate strategic alternatives throughout the period. "
            * 30
        )
        for start, end in split_sentences(text):
            assert MIN_SENTENCE_CHARS <= end - start <= MAX_SENTENCE_CHARS
