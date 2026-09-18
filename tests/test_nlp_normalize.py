"""The normalisation view must never move a character.

Every quote SC-03 guarantees is a slice of the original document taken at an
offset found in the normalised view. If normalisation resized anything, every
offset after that point would be wrong -- and wrong quietly, producing quotes
that look plausible and are off by one or two characters.
"""

from __future__ import annotations

import pytest

from credit_risk_copilot.nlp.normalize import match_view


class TestLengthIsPreserved:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "plain ascii text",
            "“Going concern” — the Company’s ability",
            "non breaking spaces throughout",
            "• bullet · midpoint – en — em",
            "MIXED Case With CAPITALS",
            "İstanbul Holding A.Ş.",  # dotted capital I: lower() resizes it
            "﻿leading byte order mark",
        ],
    )
    def test_the_view_has_the_same_length_as_its_input(self, text: str) -> None:
        assert len(match_view(text)) == len(text)

    def test_the_turkish_dotted_capital_does_not_shift_later_offsets(self) -> None:
        """`"İ".lower()` returns two characters. One of these in a filing
        would shift every quote after it by one, so the fast path is taken only
        when it is verified not to have resized the string."""
        text = "İ substantial doubt about our ability to continue as a going concern"
        view = match_view(text)

        assert len(view) == len(text)
        index = view.index("going concern")
        assert text[index : index + len("going concern")] == "going concern"


class TestFolding:
    def test_typographic_quotes_become_ascii(self) -> None:
        assert match_view("the Company’s “ability”") == 'the company\'s "ability"'

    def test_dashes_are_folded_to_hyphen(self) -> None:
        assert match_view("A–B—C−D") == "a-b-c-d"

    def test_text_is_lower_cased(self) -> None:
        assert match_view("SUBSTANTIAL DOUBT") == "substantial doubt"

    def test_an_offset_found_in_the_view_indexes_the_original(self) -> None:
        text = "The Company’s auditors raised “SUBSTANTIAL DOUBT” about it."
        view = match_view(text)

        start = view.index("substantial doubt")
        assert text[start : start + len("substantial doubt")] == "SUBSTANTIAL DOUBT"
