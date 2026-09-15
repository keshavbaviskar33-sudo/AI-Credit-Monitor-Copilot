"""Document extraction: filing HTML and uploaded PDFs into located content.

See docs/extraction.md for the design and its limits.
"""

from credit_risk_copilot.extraction.base import DocumentExtractionError, DocumentExtractor
from credit_risk_copilot.extraction.html_extractor import HtmlDocumentExtractor
from credit_risk_copilot.extraction.models import (
    DocumentLocation,
    DocumentSection,
    DocumentSource,
    ExtractedDocument,
    ExtractionError,
    Table,
    TextBlock,
)
from credit_risk_copilot.extraction.pdf_extractor import PdfDocumentExtractor
from credit_risk_copilot.extraction.sections import detect_sections
from credit_risk_copilot.extraction.upload import (
    RejectionCode,
    UploadValidation,
    validate_upload,
)

__all__ = [
    "DocumentExtractionError",
    "DocumentExtractor",
    "DocumentLocation",
    "DocumentSection",
    "DocumentSource",
    "ExtractedDocument",
    "ExtractionError",
    "HtmlDocumentExtractor",
    "PdfDocumentExtractor",
    "RejectionCode",
    "Table",
    "TextBlock",
    "UploadValidation",
    "detect_sections",
    "validate_upload",
]
