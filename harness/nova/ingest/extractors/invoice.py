"""Invoice Extractor Agent: Extracts InvoiceDoc and InvoiceLine facts from freight billing documents.

Uses the Nova LLM client tool calling to guarantee strict Pydantic model validation.
Handles multi-page invoice line tables, links each line item to its exact page number,
normalizes invoice numbers, and strictly classifies ChargeType enums.
"""
from __future__ import annotations

import logging
from typing import Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field

from nova.llm.client import NovaLLMClient, StructuredExtractionError
from nova.models.common import Authority, ChargeType, SourceRef
from nova.models.documents import DocumentRecord, Page
from nova.models.facts import InvoiceDoc, InvoiceLine

logger = logging.getLogger(__name__)


class InvoiceExtractionResult(BaseModel):
    """Pydantic container for invoices extracted from billing documents."""
    model_config = ConfigDict(extra="forbid")

    invoices: list[InvoiceDoc] = Field(
        default_factory=list,
        description="Extracted invoice documents or credit notes.",
    )


INVOICE_SYSTEM_PROMPT = """You are an expert freight audit billing extraction agent.
Your task is to analyze freight invoices, credit notes, and billing statements, and extract structured InvoiceDoc and InvoiceLine models.

CRITICAL INSTRUCTIONS & CONSTRAINTS:

1. INVOICE IDENTIFIER CANONICALIZATION:
   - 'invoice_id' must be canonical uppercase without spaces or '#' or ':' (e.g. 'TX-US-2032-5394', 'INV-2040-0012').
   - For credit notes, set 'is_credit_note=True' and extract 'credited_invoice_id' if an original invoice number is cited.

2. MULTI-PAGE LINE ITEMS & PAGE CITATIONS:
   - Invoice line tables frequently continue across multiple pages.
   - For every line item in 'lines', its 'source' must be a SourceRef with:
     - 'doc': The exact document identifier provided in the prompt.
     - 'page': The EXACT 1-indexed page number (from the '=== PAGE n ===' header) where that specific line item is printed.
     - 'quote': An exact, verbatim substring (minimum 12 non-whitespace characters) from that specific line item. NEVER paraphrase.
   - The invoice header 'source' must cite the invoice title/number on the first page it appears.

3. CHARGE TYPE CLASSIFICATION:
   - Map each line item's 'charge_type' strictly to one of the following ChargeType enum values:
     - 'base_freight': Air freight, ocean freight, linehaul, road freight per kg or flat.
     - 'fuel_surcharge': Fuel adjustment, FSC, fuel surcharge percentage or amount.
     - 'security_surcharge': Security fee, screening fee, airline security charge.
     - 'accessorial': Documentation fee, handling fee, delivery surcharge, pickup fee, airwaybill fee, terminal charges.
     - 'customs_duty': Customs clearance, duties, import taxes.
     - 'disbursement': Carrier disbursement fee or advancement fee.
     - 'tax': Value added tax (VAT), GST, sales tax.
     - 'late_fee': Interest, late payment charges, overdue penalty fee.
     - 'rebate': Volume rebate credit or deduction.
     - 'margin_step_down': Handling margin discount or reduction.
     - 'promised_credit': Annual credit, incentive credit, service credit.
     - 'other': Unclassified fee.

4. CURRENCY & NUMERIC VALUES:
   - Currency must be an ISO 3-letter code (e.g. 'USD', 'INR', 'EUR').
   - Strip all currency symbols ('$', '₹', 'Rs.', '€'), commas, and unit suffixes.
   - Total amounts, quantities, unit rates, and line amounts must be parsed as clean numeric Decimals.

5. DATES & METADATA:
   - Extract 'invoice_date' (ISO format YYYY-MM-DD), 'due_date', 'pickup_date' (ship date), 'shipment_id' (AWB or tracking number), 'origin', 'destination', and 'chargeable_weight_kg'.
   - CRITICAL: If shipment_id, origin, destination, pickup_date, or chargeable_weight_kg are missing from the top-level invoice header but are printed inside the line items, you MUST extract them and place them in the top-level InvoiceDoc fields.
   - Authority rank: Must default to Authority.RECORD (3).

6. GRACEFUL EMPTY EXTRACTIONS:
   - If the document contains no invoice or billing data, return invoices=[]. Do NOT invent line items or amounts."""


class InvoiceExtractor:
    """Agent for extracting InvoiceDoc and InvoiceLine facts from invoice documents."""

    def __init__(self, client: NovaLLMClient | None = None, model: str | None = None) -> None:
        self.client = client or NovaLLMClient()
        self.model = model

    def extract_document(self, doc: DocumentRecord) -> list[InvoiceDoc]:
        """Extract invoice documents and their line items from a DocumentRecord."""
        if not doc.pages:
            logger.info("Document %s has no pages; returning empty invoice list.", doc.doc_id)
            return []

        # Build multi-page text representation with explicit page demarcations
        pages_content: list[str] = []
        for p in doc.pages:
            if not p.text.strip():
                continue
            pages_content.append(f"=== PAGE {p.page_number} ===\n{p.text}")

        if not pages_content:
            logger.info("Document %s has only empty pages; returning empty invoice list.", doc.doc_id)
            return []

        full_doc_text = "\n\n".join(pages_content)

        prompt = (
            f"Document Identifier: {doc.doc_id}\n"
            f"Filename: {doc.filename}\n"
            f"Extension: {doc.ext}\n\n"
            f"Document Pages Content:\n"
            f"{full_doc_text}\n\n"
            f"Extract all InvoiceDoc items and itemized InvoiceLine items using the invoice_extraction tool."
        )

        try:
            result = self.client.extract_structured(
                schema=InvoiceExtractionResult,
                prompt=prompt,
                system=INVOICE_SYSTEM_PROMPT,
                model=self.model,
                tool_name="invoice_extraction",
                tool_description="Extract structured freight invoices and line items from billing document.",
            )
            return result.invoices
        except StructuredExtractionError as e:
            logger.warning("Invoice extraction returned no valid structured facts for %s: %s", doc.doc_id, e)
            return []
        except Exception as e:
            logger.error("Unexpected error during invoice extraction for %s: %s", doc.doc_id, e)
            return []


def extract_invoice_facts(
    doc: DocumentRecord,
    client: NovaLLMClient | None = None,
    model: str | None = None,
) -> list[InvoiceDoc]:
    """Convenience functional entry point for invoice extraction."""
    extractor = InvoiceExtractor(client=client, model=model)
    return extractor.extract_document(doc)