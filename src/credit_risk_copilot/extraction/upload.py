"""Validation for analyst-uploaded financial statements (FR-04).

FR-04 requires uploads to be checked for type, size and parseability *before*
processing. Uploaded documents are untrusted input (NFR Security, R-16): this
module inspects bytes and never executes, renders or resolves anything inside
the file.

Rejections carry a reason the analyst can act on, because "upload failed" with
no explanation is the kind of silent failure R-09 warns about.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.config import get_settings
from credit_risk_copilot.extraction.base import DocumentExtractionError
from credit_risk_copilot.extraction.pdf_extractor import PDF_MAGIC, open_pdf

#: MVP accepts text-based PDFs only. HTML/XBRL for SEC filers comes from EDGAR
#: directly, and scanned documents need OCR, which is explicitly post-MVP
#: (scope.md §4).
ALLOWED_SUFFIXES = frozenset({".pdf"})


class RejectionCode(StrEnum):
    UNSUPPORTED_TYPE = "unsupported_type"
    EMPTY_FILE = "empty_file"
    TOO_LARGE = "too_large"
    NOT_PARSEABLE = "not_parseable"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"


class UploadValidation(BaseModel):
    """Outcome of validating one uploaded file."""

    model_config = ConfigDict(frozen=True)

    filename: str
    size_bytes: int
    accepted: bool
    code: RejectionCode | None = None
    reason: str | None = None
    page_count: int | None = None

    @classmethod
    def reject(
        cls, filename: str, size_bytes: int, code: RejectionCode, reason: str
    ) -> UploadValidation:
        return cls(
            filename=filename, size_bytes=size_bytes, accepted=False, code=code, reason=reason
        )


def validate_upload(
    content: bytes, filename: str, *, max_bytes: int | None = None
) -> UploadValidation:
    """Check an uploaded file before anything else touches it.

    `max_bytes` defaults to `Settings.max_upload_bytes`.
    """
    limit = max_bytes if max_bytes is not None else get_settings().max_upload_bytes
    size = len(content)
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        return UploadValidation.reject(
            filename,
            size,
            RejectionCode.UNSUPPORTED_TYPE,
            f"'{suffix or filename}' is not a supported upload type. "
            f"Accepted: {', '.join(sorted(ALLOWED_SUFFIXES))}.",
        )

    if size == 0:
        return UploadValidation.reject(
            filename, size, RejectionCode.EMPTY_FILE, "The file is empty."
        )

    if size > limit:
        return UploadValidation.reject(
            filename,
            size,
            RejectionCode.TOO_LARGE,
            f"The file is {size:,} bytes; the limit is {limit:,} bytes.",
        )

    # Trust the bytes, not the extension: a renamed file must not reach a parser
    # that assumes the suffix told the truth.
    if not content.startswith(PDF_MAGIC):
        return UploadValidation.reject(
            filename,
            size,
            RejectionCode.UNSUPPORTED_TYPE,
            "The file is named .pdf but its contents are not a PDF.",
        )

    try:
        with open_pdf(content) as pdf:
            page_count = len(pdf.pages)
            has_text = any((page.extract_text() or "").strip() for page in pdf.pages)
    except DocumentExtractionError as exc:
        return UploadValidation.reject(filename, size, RejectionCode.NOT_PARSEABLE, str(exc))

    if page_count == 0:
        return UploadValidation.reject(
            filename, size, RejectionCode.NOT_PARSEABLE, "The PDF contains no pages."
        )

    if not has_text:
        return UploadValidation.reject(
            filename,
            size,
            RejectionCode.NO_EXTRACTABLE_TEXT,
            "No extractable text found -- this looks like a scanned PDF. "
            "Scanned documents need OCR, which is not supported in this version.",
        )

    return UploadValidation(
        filename=filename, size_bytes=size, accepted=True, page_count=page_count
    )
