"""The DocumentExtractor protocol is the seam Phase 5 will depend on.

Nothing else asserts that the concrete extractors actually satisfy it -- the
protocol is never instantiated, so a drifting signature would go unnoticed
until Phase 5 tried to swap one for the other.
"""

from __future__ import annotations

import inspect

import pytest

from credit_risk_copilot.extraction import (
    DocumentSource,
    HtmlDocumentExtractor,
    PdfDocumentExtractor,
)
from credit_risk_copilot.extraction.base import DocumentExtractor

EXTRACTORS = [HtmlDocumentExtractor, PdfDocumentExtractor]


@pytest.mark.parametrize("extractor_class", EXTRACTORS)
def test_extractor_exposes_the_protocol_surface(extractor_class: type) -> None:
    extractor = extractor_class()

    assert isinstance(extractor.name, str) and extractor.name
    assert isinstance(extractor.version, str) and extractor.version
    assert callable(extractor.extract)


@pytest.mark.parametrize("extractor_class", EXTRACTORS)
def test_extract_signature_matches_the_protocol(extractor_class: type) -> None:
    expected = list(inspect.signature(DocumentExtractor.extract).parameters)
    actual = list(inspect.signature(extractor_class.extract).parameters)

    assert actual == expected


@pytest.mark.parametrize("extractor_class", EXTRACTORS)
def test_extractor_names_are_distinct_and_recorded_on_output(extractor_class: type) -> None:
    """Provenance includes which extractor produced a document (FR-07/SC-01),
    so two extractors must not answer to the same name."""
    names = {cls().name for cls in EXTRACTORS}

    assert len(names) == len(EXTRACTORS)
    assert extractor_class().name in names


def test_document_source_is_required_by_both_paths() -> None:
    """An uploaded PDF has no accession, but always has a uri, so provenance
    never dead-ends."""
    source = DocumentSource(uri="upload.pdf", media_type="application/pdf")

    assert source.uri
    assert source.cik is None and source.accession is None
