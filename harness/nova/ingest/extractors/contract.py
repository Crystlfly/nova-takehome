"""Contract Extractor Agent: Extracts ContractInstrument and RateRow facts from MSAs and amendments.

Uses the Nova LLM client tool calling to guarantee strict Pydantic model validation.
Enforces exact verbatim quotes for evidence citations and ISO currency normalization.
"""
from __future__ import annotations

import logging
from typing import Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field

from nova.llm.client import NovaLLMClient, StructuredExtractionError
from nova.models.common import Authority, Category, ChargeType, SourceRef
from nova.models.documents import DocumentRecord, Page
from nova.models.facts import ContractInstrument, RateRow, Schedule1Contact

logger = logging.getLogger(__name__)


class ContractExtractionResult(BaseModel):
    """Pydantic container for facts extracted from contract documents (MSAs, Amendments)."""
    model_config = ConfigDict(extra="forbid")

    instruments: list[ContractInstrument] = Field(
        default_factory=list,
        description="Master agreements, amendments, or formal contract instruments found.",
    )
    rate_rows: list[RateRow] = Field(
        default_factory=list,
        description="Individual lane rate entries extracted from rate schedules, annexes, or tables.",
    )


CONTRACT_SYSTEM_PROMPT = """You are an expert legal and freight contract extraction agent.
Your task is to analyze Master Services Agreements (MSAs), amendments, annexes, and rate schedules, and extract structured facts: ContractInstrument and RateRow models.

CRITICAL INSTRUCTIONS & CONSTRAINTS:

1. SOURCE CITATIONS & VERBATIM QUOTES:
   - For every extracted fact or contact, 'source' must be a SourceRef containing:
     - 'doc': The exact document identifier provided in the prompt (e.g. 'batch_01/0002.eml#MSA.pdf').
     - 'page': The exact 1-indexed page number where the evidence appears.
     - 'quote': An exact, verbatim substring (minimum 12 non-whitespace characters) copied character-for-character from that page's text. NEVER paraphrase or invent quotes.

2. CURRENCY & MONETARY VALUES:
   - Currency must be an ISO 3-letter code (e.g. 'USD', 'INR', 'EUR').
   - Strip all currency symbols ('$', '₹', 'Rs.', '€'), commas, and formatting from numeric rates, percentages, and fees. Convert to pure numbers/decimals (e.g. '$6.01/kg' -> rate_per_kg=6.01, currency='USD').
   - For percentage rates (e.g. late fees or surcharges), record the numeric percentage (e.g. '1.5%' -> 1.5).

3. CHARGE TYPES & CATEGORIES:
   - Match charge types strictly to: 'base_freight', 'fuel_surcharge', 'security_surcharge', 'accessorial', 'customs_duty', 'disbursement', 'tax', 'late_fee', 'rebate', 'margin_step_down', 'promised_credit', 'other'.
   - For Schedule 1 contacts, map the authorized decision category strictly to: 'rates', 'waivers', 'payment_terms', 'notices', 'treasury', 'billing_disputes', 'key_account_manager'.

4. CONTRACT INSTRUMENT DETAILS:
   - instrument_type: 'msa', 'amendment', 'annex_a', etc.
   - Extract effective_date, expiration_date (or null), auto_renewal (true/false), renewal_notice_days, payment_terms_days, grace_period_days, late_fee_rate_pct, and late_fee_compounds.
   - Schedule 1 contacts: Extract named persons, roles, emails, and their authorized category with exact source quotes.
   - Authority rank: Must default to Authority.CONTRACT (1).

5. RATE ROWS:
   - Extract EVERY rate from ALL annexes: Annex A (base freight), Annex B (security/delivery/accessorials), and Annex C (fuel surcharges).
   - Capture min_weight_kg, max_weight_kg, rate_per_kg, flat_fee, percentage_rate, effective_date, and expiration_date.
   - For global surcharges (like Fuel or Security), leave origin, destination, and lane as null.

6. GRACEFUL EMPTY EXTRACTIONS:
   - If the document contains no contract terms or rate tables, return empty lists: instruments=[] and rate_rows=[]. Do NOT hallucinate."""


class ContractExtractor:
    """Agent for extracting ContractInstrument and RateRow facts from contract documents."""

    def __init__(self, client: NovaLLMClient | None = None, model: str | None = None) -> None:
        self.client = client or NovaLLMClient()
        self.model = model

    def extract_document(self, doc: DocumentRecord) -> ContractExtractionResult:
        """Extract contract instruments and rate rows from a DocumentRecord."""
        if not doc.pages:
            logger.info("Document %s has no pages; returning empty extraction.", doc.doc_id)
            return ContractExtractionResult()

        # Build multi-page text representation with explicit page boundaries
        pages_content: list[str] = []
        for p in doc.pages:
            if not p.text.strip():
                continue
            pages_content.append(f"=== PAGE {p.page_number} ===\n{p.text}")

        if not pages_content:
            logger.info("Document %s has only empty pages; returning empty extraction.", doc.doc_id)
            return ContractExtractionResult()

        full_doc_text = "\n\n".join(pages_content)

        prompt = (
            f"Document Identifier: {doc.doc_id}\n"
            f"Filename: {doc.filename}\n"
            f"Extension: {doc.ext}\n\n"
            f"Document Pages Content:\n"
            f"{full_doc_text}\n\n"
            f"Extract all ContractInstrument and RateRow facts using the contract_extraction tool."
        )

        try:
            result = self.client.extract_structured(
                schema=ContractExtractionResult,
                prompt=prompt,
                system=CONTRACT_SYSTEM_PROMPT,
                model=self.model,
                tool_name="contract_extraction",
                tool_description="Extract structured ContractInstrument and RateRow facts from contract document.",
                max_tokens=65536,
            )
            return result
        except StructuredExtractionError as e:
            logger.warning("Contract extraction returned no valid structured facts for %s: %s", doc.doc_id, e)
            return ContractExtractionResult()
        except Exception as e:
            logger.error("Unexpected error during contract extraction for %s: %s", doc.doc_id, e)
            return ContractExtractionResult()


def extract_contract_facts(
    doc: DocumentRecord,
    client: NovaLLMClient | None = None,
    model: str | None = None,
) -> ContractExtractionResult:
    """Convenience functional entry point for contract extraction."""
    extractor = ContractExtractor(client=client, model=model)
    return extractor.extract_document(doc)
