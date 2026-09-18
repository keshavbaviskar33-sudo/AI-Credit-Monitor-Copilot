"""Extraction mechanics, and SC-03.

SC-03 ("100% of NLP evidence quotes are present verbatim in the cited source
text") is the phase's hard invariant, so it is tested three ways: on
synthesised text where the offsets are known, on a document assembled through
the real `ExtractedDocument` path, and -- in `test_nlp_golden_set.py` -- on
every signal found in all twelve real filings.
"""

from __future__ import annotations

import pytest

from credit_risk_copilot.extraction.models import (
    DocumentLocation,
    DocumentSection,
    DocumentSource,
    ExtractedDocument,
)
from credit_risk_copilot.nlp.extract import (
    analyze_document,
    deduplicate,
    extract_from_text,
    verify_quotes,
)
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode

BREACH = (
    "As of December 31, 2015 we were not in compliance with the leverage ratio covenant "
    "under our 2013 Credit Facility."
)
GOING_CONCERN = (
    "These conditions create substantial doubt about the Company's ability to continue as a "
    "going concern."
)


def _document(text: str, sections: dict[str, tuple[int, int]]) -> ExtractedDocument:
    return ExtractedDocument(
        source=DocumentSource(
            uri="test://filing",
            media_type="text/html",
            cik=1234,
            accession="0001234567-16-000001",
            form="10-K",
            filed="2016-03-30",
        ),
        extractor="test",
        extractor_version="1.0",
        text=text,
        sections=tuple(
            DocumentSection(
                section_id=section_id,
                title=section_id,
                heading_text=section_id,
                location=DocumentLocation(char_start=start, char_end=end, section_id=section_id),
            )
            for section_id, (start, end) in sections.items()
        ),
    )


class TestQuotesAreVerbatim:
    def test_a_quote_slices_back_out_of_its_source(self) -> None:
        signals = extract_from_text(BREACH)

        assert signals
        for signal in signals:
            quote = signal.quote
            assert BREACH[quote.char_start : quote.char_end] == quote.text

    def test_an_offset_is_applied_to_every_span(self) -> None:
        """A caller passing a section sliced out of a document must get back
        offsets that index the document, not the slice."""
        plain = extract_from_text(BREACH)
        shifted = extract_from_text(BREACH, offset=5_000)

        assert [s.quote.char_start + 5_000 for s in plain] == [s.quote.char_start for s in shifted]
        assert [s.quote.text for s in plain] == [s.quote.text for s in shifted]

    def test_the_trigger_offsets_index_the_quote(self) -> None:
        signal = extract_from_text(BREACH)[0]

        assert signal.quote.trigger_text
        assert signal.quote.trigger_text in signal.quote.text

    def test_verify_quotes_passes_on_a_real_document(self) -> None:
        text = f"Some preamble.\n{BREACH}\n{GOING_CONCERN}\n"
        document = _document(text, {"item_7": (0, len(text))})

        report = analyze_document(document)

        assert report.signals
        assert verify_quotes(report, document) == ()

    def test_verify_quotes_catches_a_tampered_quote(self) -> None:
        """The check has to be capable of failing, or it proves nothing."""
        text = f"{BREACH}\n"
        document = _document(text, {"item_7": (0, len(text))})
        report = analyze_document(document)
        tampered = report.model_copy(
            update={
                "signals": (
                    report.signals[0].model_copy(
                        update={
                            "quote": report.signals[0].quote.model_copy(
                                update={"text": "we were in compliance"}
                            )
                        }
                    ),
                )
            }
        )

        assert verify_quotes(tampered, document) != ()

    def test_an_over_long_sentence_is_narrowed_but_stays_exact(self) -> None:
        filler = "The Company continued to evaluate strategic alternatives. " * 8
        text = f"{filler}{BREACH.rstrip('.')} and {filler}"

        signals = extract_from_text(text)

        assert signals
        for signal in signals:
            quote = signal.quote
            assert text[quote.char_start : quote.char_end] == quote.text
            assert len(quote.text) <= 400


class TestSectionHandling:
    def test_signals_carry_the_section_they_were_found_in(self) -> None:
        text = f"{GOING_CONCERN}\n{BREACH}\n"
        document = _document(
            text,
            {"item_1a": (0, len(GOING_CONCERN) + 1), "item_7": (len(GOING_CONCERN) + 1, len(text))},
        )

        report = analyze_document(document)
        by_code = {s.code: s.quote.section_id for s in report.signals}

        assert by_code[RiskSignalCode.GOING_CONCERN_DOUBT] == "item_1a"
        assert by_code[RiskSignalCode.COVENANT_BREACH] == "item_7"

    def test_a_missing_section_is_reported_not_skipped(self) -> None:
        """ "no signals" and "could not read the section" are different
        answers, and a caller must be able to tell them apart."""
        text = f"{BREACH}\n"
        document = _document(text, {"item_7": (0, len(text))})

        report = analyze_document(document)

        assert "item_7" in report.sections_read
        assert "item_1a" in report.sections_missing
        missing = next(c for c in report.coverage if c.section_id == "item_1a")
        assert missing.reason is not None

    def test_coverage_counts_what_was_read(self) -> None:
        text = f"{GOING_CONCERN}\n{BREACH}\n"
        document = _document(text, {"item_7": (0, len(text))})

        coverage = next(c for c in analyze_document(document).coverage if c.section_id == "item_7")

        assert coverage.located
        assert coverage.characters == len(text)
        assert coverage.sentences == 2

    def test_signals_carry_the_filings_identity(self) -> None:
        text = f"{BREACH}\n"
        document = _document(text, {"item_7": (0, len(text))})

        signal = analyze_document(document).signals[0]

        assert signal.quote.accession == "0001234567-16-000001"
        assert signal.quote.filed == "2016-03-30"
        assert signal.quote.form == "10-K"


class TestDeduplication:
    def test_the_same_statement_in_two_sections_is_reported_once(self) -> None:
        """Frontier states its going-concern conclusion in Item 1A and again
        in Item 7. Counting both would make the signal count a measure of the
        filer's drafting style."""
        text = f"{GOING_CONCERN}\n{GOING_CONCERN}\n"
        document = _document(
            text,
            {
                "item_1a": (0, len(GOING_CONCERN) + 1),
                "item_7": (len(GOING_CONCERN) + 1, len(text)),
            },
        )

        report = analyze_document(document)

        assert len(report.by_code(RiskSignalCode.GOING_CONCERN_DOUBT)) == 1

    def test_deduplication_keeps_the_first_occurrence(self) -> None:
        text = f"{GOING_CONCERN}\n{GOING_CONCERN}\n"
        document = _document(text, {"item_1a": (0, len(text))})

        signal = analyze_document(document).signals[0]

        assert signal.quote.char_start == 0

    def test_two_different_statements_both_survive(self) -> None:
        signals = deduplicate(extract_from_text(f"{GOING_CONCERN}\n{BREACH}\n"))

        assert {s.code for s in signals} == {
            RiskSignalCode.GOING_CONCERN_DOUBT,
            RiskSignalCode.COVENANT_BREACH,
        }

    def test_two_patterns_for_one_code_on_one_sentence_are_one_signal(self) -> None:
        """ "create substantial doubt ... continue as a going concern" matches
        both `gc.raise_doubt` and `gc.substantial_doubt`. That is one
        statement, so it is one signal -- otherwise the count would measure
        how many of our own patterns overlap."""
        raw = extract_from_text(GOING_CONCERN)

        assert len(raw) > 1
        assert len(deduplicate(raw)) == 1


class TestReportAccessors:
    def test_asserted_excludes_other_moods(self) -> None:
        text = (
            f"{BREACH}\n"
            "As of December 31, 2019 we were in compliance with all covenants under our "
            "credit agreement.\n"
        )
        document = _document(text, {"item_7": (0, len(text))})

        report = analyze_document(document)

        assert {s.assertion for s in report.signals} == {
            Assertion.ASSERTED,
            Assertion.NEGATED,
        }
        assert all(s.is_asserted for s in report.asserted)

    def test_codes_defaults_to_asserted_only(self) -> None:
        text = "As of 2019 we were in compliance with all covenants under our credit agreement.\n"
        document = _document(text, {"item_7": (0, len(text))})

        report = analyze_document(document)

        assert report.codes() == frozenset()
        assert RiskSignalCode.COVENANT_BREACH in report.codes(asserted_only=False)

    @pytest.mark.parametrize("emit", [True, False])
    def test_a_report_is_produced_even_with_no_sections(self, emit: bool) -> None:
        document = _document("nothing here at all, really nothing\n", {})

        report = analyze_document(document, emit_hypothetical=emit)

        assert report.signals == ()
        assert len(report.sections_missing) == 3
