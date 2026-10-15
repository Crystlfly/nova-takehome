"""Document models representing parsed mailbox files and page contents."""
from __future__ import annotations

from datetime import date, datetime
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field


class Page(BaseModel):
    """A single page of a PDF document, sheet of an Excel spreadsheet, or email body."""
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(
        ...,
        ge=1,
        description="1-indexed page number in PDF, sheet number in XLSX, or 1 for email",
    )
    text: str = Field(
        ...,
        description="Text content of the page extracted following exact reading order",
    )
    is_empty: bool = Field(
        default=False,
        description="True if page contained no readable text characters",
    )


class DocumentRecord(BaseModel):
    """Metadata and extracted text content for an email or attached document in the mailbox."""
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(
        ...,
        description="Canonical identifier in mailbox, e.g. 'batch_01/0014.eml' or 'batch_01/0014.eml#INV-1.pdf'",
    )
    batch: str = Field(
        ...,
        description="Batch directory name where the document was discovered (e.g. 'batch_01')",
    )
    filename: str = Field(
        ...,
        description="Base filename or attachment filename",
    )
    ext: str = Field(
        ...,
        description="Normalized file extension without leading dot ('pdf', 'xlsx', 'eml')",
    )
    received_date: datetime | date | None = Field(
        default=None,
        description="Document arrival timestamp, taken from email RFC 822 Date header",
    )
    is_scan: bool = Field(
        default=False,
        description="True if document is a scanned PDF with no native text layer",
    )
    pages: list[Page] = Field(
        default_factory=list,
        description="List of extracted text pages in reading order",
    )
    parent_doc: str | None = Field(
        default=None,
        description="Parent email doc_id if this document is an email attachment",
    )
