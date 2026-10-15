"""Nova ingestion package."""
from nova.ingest.router import (
    ClassificationResult,
    DocumentKind,
    IngestRouter,
    classify_document,
    classify_text,
)
from nova.ingest.text_layer import (
    ParsedDocument,
    attachments,
    email_lines,
    find_quote_page,
    found,
    is_image_only,
    norm,
    pages_of,
    parse_eml,
    pdf_is_image_only,
    pdf_pages,
    xlsx_pages,
)

__all__ = [
    "ClassificationResult",
    "DocumentKind",
    "IngestRouter",
    "classify_document",
    "classify_text",
    "ParsedDocument",
    "attachments",
    "email_lines",
    "find_quote_page",
    "found",
    "is_image_only",
    "norm",
    "pages_of",
    "parse_eml",
    "pdf_is_image_only",
    "pdf_pages",
    "xlsx_pages",
]
