"""Text layer extraction for PDFs, EMLs, and Excel spreadsheets.

Strictly mirrors the reading order logic from grader/extract.py to guarantee that
all text extractions and evidence citations match the grading harness character-for-character.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

SEP = " | "


def norm(s: str) -> str:
    """Collapse all whitespace sequences to a single space, matching grader normalization."""
    return " ".join(s.split())


# ---- PDF ----------------------------------------------------------------------------------------------
def _reading_order(page: Any) -> str:
    """Group words into lines by vertical midpoint baseline, sorted left-to-right.

    Strictly mirrors grader/extract.py: _reading_order(page).
    """
    words = page.get_text("words")
    # w: (x0, y0, x1, y1, word, block_no, line_no, word_no)
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list] = []
    for w in words:
        mid = (w[1] + w[3]) / 2
        if lines and abs(lines[-1][0] - mid) <= 2.5:
            lines[-1][1].append(w)
        else:
            lines.append([mid, [w]])
    return "\n".join(" ".join(x[4] for x in sorted(ws, key=lambda w: w[0])) for _, ws in lines)


def pdf_pages(data: bytes) -> list[str]:
    """Extract text for each PDF page using exact baseline reading order."""
    # pyrefly: ignore [missing-import]
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [_reading_order(p) for p in doc]


def pdf_is_image_only(data: bytes) -> bool:
    """Determine if a PDF is a scanned document with no text layer at all."""
    # pyrefly: ignore [missing-import]
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return all(not p.get_text().strip() for p in doc)


# ---- XLSX ---------------------------------------------------------------------------------------------
def _cell_text(cell: Any) -> str:
    """Format an openpyxl cell value as text according to cell format.

    Strictly mirrors grader/extract.py: _cell_text(cell).
    """
    v = cell.value
    if v is None:
        return ""
    fmt = cell.number_format or "General"
    prefix = ""
    m = re.match(r'^"([^"]*)"(.*)$', fmt)
    if m:
        prefix, fmt = m.group(1), m.group(2)
    if isinstance(v, datetime):
        return prefix + v.date().isoformat()
    if isinstance(v, date):
        return prefix + v.isoformat()
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        dp = len(fmt.split(".")[1]) if "." in fmt else 0
        return prefix + f"{Decimal(str(v)):.{dp}f}"
    return prefix + str(v)


def xlsx_pages(data: bytes) -> list[str]:
    """Extract text from XLSX sheets, one page per sheet, joining non-empty cells with ' | '."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    pages = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows():
            cells = [t for t in (_cell_text(c) for c in row) if t != ""]
            if cells:
                rows.append(SEP.join(cells))
        pages.append("\n".join(rows))
    return pages


# ---- EML / Email --------------------------------------------------------------------------------------
def parse_eml(data: bytes) -> Any:
    """Parse raw bytes of an RFC 822 email message using default policy."""
    return BytesParser(policy=policy.default).parsebytes(data)


def email_lines(msg: Any) -> list[str]:
    """Produce standardized email text lines: From/To/Cc/Date/Subject/Body/Attachments.

    Strictly mirrors grader/extract.py: email_lines(msg).
    """
    name, addr = parseaddr(str(msg["From"]))
    out = [f"From: {name} <{addr}>", f"To: {msg['To']}"]
    if msg["Cc"]:
        out.append(f"Cc: {msg['Cc']}")
    dt = parsedate_to_datetime(str(msg["Date"]))
    out += [f"Date: {dt.strftime('%Y-%m-%dT%H:%M:%SZ')}", f"Subject: {msg['Subject']}", ""]
    body = msg.get_body(preferencelist=("plain",))
    out += body.get_content().replace("\r\n", "\n").rstrip("\n").split("\n") if body else []
    names = [p.get_filename() for p in msg.iter_attachments()]
    if names:
        out.append("Attachments: " + ", ".join(names))
    return out


def attachments(data: bytes) -> list[tuple[str, bytes]]:
    """Extract all attachment (filename, payload_bytes) pairs from an email message."""
    return [(p.get_filename() or "", p.get_content()) for p in parse_eml(data).iter_attachments()]


# ---- Unified Entry Point ------------------------------------------------------------------------------
def pages_of(data: bytes, ext: str) -> list[str]:
    """Extract text pages for a file with the given extension (pdf, xlsx, eml)."""
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return pdf_pages(data)
    if ext == "xlsx":
        return xlsx_pages(data)
    if ext == "eml":
        return ["\n".join(email_lines(parse_eml(data)))]
    raise ValueError(f"can't read .{ext} files")


def is_image_only(data: bytes, ext: str) -> bool:
    """Check if the document is a scanned image without an embedded text layer."""
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return pdf_is_image_only(data)
    return False


def found(pages: list[str], page: int, quote: str) -> bool:
    """Check if quote is present on the specified 1-indexed page after whitespace normalization."""
    return 1 <= page <= len(pages) and norm(quote) in norm(pages[page - 1])


def find_quote_page(pages: list[str], quote: str) -> int | None:
    """Find the first 1-indexed page number containing the quote, or None if not found."""
    norm_q = norm(quote)
    for i, p in enumerate(pages):
        if norm_q in norm(p):
            return i + 1
    return None


@dataclass
class ParsedDocument:
    """Holds parsed page texts and scan status for any supported document."""
    data: bytes
    ext: str
    pages: list[str]
    is_scan: bool

    @classmethod
    def from_bytes(cls, data: bytes, ext: str) -> ParsedDocument:
        ext = ext.lower().lstrip(".")
        pages = pages_of(data, ext)
        scan = is_image_only(data, ext)
        return cls(data=data, ext=ext, pages=pages, is_scan=scan)
