"""Run the catalog over a filing's narrative sections.

The shape of the work: for each narrative section that was located, segment it
into sentences, match every catalog pattern against the normalised view of each
sentence, classify the mood of each match, and emit the ones the definition
asks for -- each carrying the exact characters it was found in.

## Which sections, and why not all of them

Item 1A (Risk Factors), Item 7 (MD&A) and Item 3 (Legal Proceedings). Item 7 is
where a filer describes its actual condition and is where nearly every asserted
signal is found. Item 1A is overwhelmingly hypothetical, which is precisely why
it is read: a *newly asserted* statement inside risk factors is a strong
signal, and there is no way to notice one without reading the section. Item 3
carries litigation and, in distressed filers, the bankruptcy petition itself.

Item 1 (Business) and Item 8 (Financial Statements) are excluded. Item 1 is
descriptive and its distress-adjacent language is about markets rather than the
filer. Item 8 is mostly tables mirrored into the text, and the notes that do
carry going-concern language are cross-referenced from Item 7 anyway -- reading
it would multiply near-duplicate quotes without adding a finding. Both are
reconsidered if the measured recall says so, not before.

## Deduplication

Filings repeat themselves, heavily: Frontier states its going-concern
conclusion in Item 1A, again in Item 7, and again under an "Going Concern"
heading within Item 7. Emitting all of them would make a signal's *count* a
measure of the filer's drafting style. Signals are therefore deduplicated on
`(code, normalised sentence)`, keeping the first occurrence -- so the count is
the number of distinct statements, and the quote points at the first place an
analyst would find it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from credit_risk_copilot.extraction.models import ExtractedDocument
from credit_risk_copilot.nlp.catalog import CATALOG, CATALOG_VERSION, RiskSignalDefinition
from credit_risk_copilot.nlp.models import (
    Assertion,
    EvidenceQuote,
    NarrativeRiskReport,
    NarrativeRiskSignal,
    SectionCoverage,
)
from credit_risk_copilot.nlp.normalize import match_view
from credit_risk_copilot.nlp.segment import split_sentences

logger = logging.getLogger(__name__)

#: The narrative sections read, in the order a reader would meet them.
NARRATIVE_SECTIONS: tuple[str, ...] = ("item_1a", "item_3", "item_7")

#: Sentences longer than this are truncated *for the quote only*, never for
#: matching. Filings contain legitimate 900-character sentences, and handing an
#: analyst one of those as "evidence" defeats the purpose; the span stays exact
#: so the full sentence is one slice away.
MAX_QUOTE_CHARS = 400


def _quote_span(
    sentence_start: int, sentence_end: int, trigger_start: int, trigger_end: int
) -> tuple[int, int]:
    """Narrow an over-long sentence to a window around its trigger.

    Kept symmetrical around the trigger rather than truncated from the left, so
    the quote reads as a clause rather than a fragment that begins mid-word.
    The result is still an exact span of the document -- shortening the window
    cannot make the quote non-verbatim, only less complete.
    """
    if sentence_end - sentence_start <= MAX_QUOTE_CHARS:
        return sentence_start, sentence_end
    slack = MAX_QUOTE_CHARS - (trigger_end - trigger_start)
    if slack <= 0:  # a trigger longer than the window: quote the trigger
        return trigger_start, trigger_end
    start = max(sentence_start, trigger_start - slack // 2)
    return start, min(sentence_end, start + MAX_QUOTE_CHARS)


def _matches_in_sentence(
    definition: RiskSignalDefinition, view: str, sentence_start: int
) -> Iterable[tuple[str, int, int]]:
    """Every pattern hit in one sentence, as `(pattern_id, start, end)`.

    Offsets returned are absolute (document-relative), because that is what an
    `EvidenceQuote` stores and converting once here avoids every caller doing
    the same arithmetic.
    """
    if definition.compiled_context is not None and not definition.compiled_context.search(view):
        return
    if definition.compiled_exclusion is not None and definition.compiled_exclusion.search(view):
        return
    for pattern in definition.patterns:
        match = pattern.compiled.search(view)
        if match is None:
            continue
        yield pattern.pattern_id, sentence_start + match.start(), sentence_start + match.end()
        # One hit per pattern per sentence. A pattern matching twice in one
        # sentence is one statement, not two.


def extract_from_text(
    text: str,
    *,
    section_id: str | None = None,
    accession: str | None = None,
    form: str | None = None,
    filed: str | None = None,
    offset: int = 0,
    emit_hypothetical: bool = False,
    catalog: Sequence[RiskSignalDefinition] = CATALOG,
) -> tuple[NarrativeRiskSignal, ...]:
    """Signals in one run of text.

    `offset` shifts every emitted span, so a caller may pass a section sliced
    out of a document and still receive offsets that index the document.
    `text` itself must be the *original* characters -- the normalised view is
    built here and used only for matching.
    """
    view = match_view(text)
    signals: list[NarrativeRiskSignal] = []

    for start, end in split_sentences(text, offset=0):
        sentence_view = view[start:end]
        for definition in catalog:
            for pattern_id, absolute_start, absolute_end in _matches_in_sentence(
                definition, sentence_view, start
            ):
                # `classify` needs offsets relative to the sentence it reads.
                assertion = classify_match(
                    sentence_view, absolute_start - start, absolute_end - start
                )
                wanted = definition.emit | (
                    {Assertion.HYPOTHETICAL} if emit_hypothetical else frozenset()
                )
                if assertion not in wanted:
                    continue

                quote_start, quote_end = _quote_span(start, end, absolute_start, absolute_end)
                signals.append(
                    NarrativeRiskSignal(
                        code=definition.code,
                        label=definition.label,
                        assertion=assertion,
                        specificity=definition.specificity,
                        pattern_id=pattern_id,
                        quote=EvidenceQuote(
                            text=text[quote_start:quote_end],
                            char_start=offset + quote_start,
                            char_end=offset + quote_end,
                            section_id=section_id,
                            trigger_start=absolute_start - quote_start,
                            trigger_end=absolute_end - quote_start,
                            accession=accession,
                            form=form,
                            filed=filed,
                        ),
                    )
                )
    return tuple(signals)


def classify_match(sentence_view: str, trigger_start: int, trigger_end: int) -> Assertion:
    """Indirection kept so `assertion` can be swapped without touching this."""
    from credit_risk_copilot.nlp.assertion import classify

    return classify(sentence_view, trigger_start, trigger_end)


def deduplicate(signals: Sequence[NarrativeRiskSignal]) -> tuple[NarrativeRiskSignal, ...]:
    """One signal per distinct statement, first occurrence kept."""
    seen: set[tuple[str, str]] = set()
    unique: list[NarrativeRiskSignal] = []
    for signal in signals:
        key = (signal.code.value, " ".join(match_view(signal.quote.text).split()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(signal)
    return tuple(unique)


def analyze_document(
    document: ExtractedDocument,
    *,
    company: str | None = None,
    sections: Sequence[str] = NARRATIVE_SECTIONS,
    emit_hypothetical: bool = False,
) -> NarrativeRiskReport:
    """Every narrative risk signal in one extracted filing.

    A section that could not be located is recorded in `coverage` with a
    reason, never skipped silently -- "we found no signals" and "we could not
    read the section" are different answers and the caller must be able to tell
    them apart (the fail-safe NFR).
    """
    collected: list[NarrativeRiskSignal] = []
    coverage: list[SectionCoverage] = []

    for section_id in sections:
        section = document.section(section_id)
        if section is None:
            coverage.append(
                SectionCoverage(
                    section_id=section_id,
                    located=False,
                    reason="section not located in this document",
                )
            )
            continue

        start = section.location.char_start
        end = section.location.char_end
        body = document.text[start:end]
        coverage.append(
            SectionCoverage(
                section_id=section_id,
                located=True,
                characters=len(body),
                sentences=len(split_sentences(body)),
            )
        )
        collected.extend(
            extract_from_text(
                body,
                section_id=section_id,
                accession=document.source.accession,
                form=document.source.form,
                filed=document.source.filed,
                offset=start,
                emit_hypothetical=emit_hypothetical,
            )
        )

    return NarrativeRiskReport(
        cik=document.source.cik,
        company=company,
        accession=document.source.accession,
        form=document.source.form,
        filed=document.source.filed,
        signals=deduplicate(collected),
        coverage=tuple(coverage),
        catalog_version=CATALOG_VERSION,
    )


def verify_quotes(report: NarrativeRiskReport, document: ExtractedDocument) -> tuple[str, ...]:
    """SC-03, as a function rather than a promise.

    Returns a message per quote that does not appear verbatim at the span it
    claims. An empty result is the invariant holding. Exposed here so the
    pipeline, the evaluation script and the test suite all check the same
    thing rather than three similar things.
    """
    failures: list[str] = []
    for signal in report.signals:
        quote = signal.quote
        actual = document.text[quote.char_start : quote.char_end]
        if actual != quote.text:
            failures.append(
                f"{signal.code.value} ({signal.pattern_id}) at [{quote.char_start}, "
                f"{quote.char_end}): document holds {actual[:60]!r}, quote says "
                f"{quote.text[:60]!r}"
            )
    return tuple(failures)
