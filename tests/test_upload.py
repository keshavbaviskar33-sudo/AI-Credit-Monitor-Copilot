"""Tests for analyst upload validation (FR-04).

Every rejection path must name a reason: "upload failed" with no explanation is
exactly the silent failure R-09 warns about.
"""

from __future__ import annotations

import pymupdf

from credit_risk_copilot.extraction.render import html_to_pdf
from credit_risk_copilot.extraction.upload import RejectionCode, validate_upload

GOOD_PDF = html_to_pdf("<html><body><p>Consolidated Balance Sheets</p></body></html>")


def scanned_pdf() -> bytes:
    """Pages with no text layer -- what a scan-to-PDF produces."""
    doc = pymupdf.open()
    doc.new_page()
    return bytes(doc.tobytes())


def test_accepts_a_text_based_pdf() -> None:
    result = validate_upload(GOOD_PDF, "statements.pdf")

    assert result.accepted
    assert result.code is None
    assert result.page_count == 1


def test_rejects_an_unsupported_extension() -> None:
    result = validate_upload(b"col1,col2\n1,2\n", "financials.csv")

    assert not result.accepted
    assert result.code == RejectionCode.UNSUPPORTED_TYPE
    assert ".pdf" in (result.reason or "")


def test_rejects_an_empty_file() -> None:
    result = validate_upload(b"", "statements.pdf")

    assert result.code == RejectionCode.EMPTY_FILE


def test_rejects_a_file_over_the_size_limit() -> None:
    result = validate_upload(GOOD_PDF, "statements.pdf", max_bytes=128)

    assert result.code == RejectionCode.TOO_LARGE
    assert "128" in (result.reason or "")


def test_rejects_a_non_pdf_wearing_a_pdf_extension() -> None:
    """Trust the bytes, not the filename (NFR Security)."""
    result = validate_upload(b"#!/bin/sh\nrm -rf /\n", "statements.pdf")

    assert result.code == RejectionCode.UNSUPPORTED_TYPE
    assert "not a PDF" in (result.reason or "")


def test_rejects_a_corrupt_pdf_with_a_parse_reason() -> None:
    result = validate_upload(b"%PDF-1.7\ntruncated garbage", "statements.pdf")

    assert result.code == RejectionCode.NOT_PARSEABLE
    assert result.reason


def test_rejects_a_scanned_pdf_and_says_why() -> None:
    """OCR is explicitly out of MVP scope, so this must fail loudly, not quietly."""
    result = validate_upload(scanned_pdf(), "scan.pdf")

    assert result.code == RejectionCode.NO_EXTRACTABLE_TEXT
    assert "OCR" in (result.reason or "")


def test_extension_check_is_case_insensitive() -> None:
    assert validate_upload(GOOD_PDF, "STATEMENTS.PDF").accepted


def test_size_is_reported_on_every_outcome() -> None:
    accepted = validate_upload(GOOD_PDF, "ok.pdf")
    rejected = validate_upload(b"nope", "ok.txt")

    assert accepted.size_bytes == len(GOOD_PDF)
    assert rejected.size_bytes == 4


def test_limit_defaults_to_the_configured_setting(monkeypatch) -> None:
    import credit_risk_copilot.extraction.upload as upload_module

    class _Settings:
        max_upload_bytes = 10

    monkeypatch.setattr(upload_module, "get_settings", lambda: _Settings())

    assert validate_upload(GOOD_PDF, "statements.pdf").code == RejectionCode.TOO_LARGE
