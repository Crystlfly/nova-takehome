"""Nova Orchestration Engine: Batch ingestion and extractor dispatch pipeline.

Orchestrates Phase 5 document ingestion:
1. Iterates over a batch of ingested documents (emails and attachments).
2. Uses IngestRouter to classify document kind based strictly on content semantics.
3. Dispatches 'msa' and 'amendment' documents to ContractExtractor.
4. Dispatches 'invoice' documents to InvoiceExtractor.
5. Aggregates all extracted facts into the central AuditState model.
6. Implements robust batch-level error isolation: failures on individual documents
   are logged without interrupting processing of subsequent documents.
"""
from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from nova.ingest.extractors.contract import ContractExtractor
from nova.ingest.extractors.invoice import InvoiceExtractor
from nova.ingest.router import ClassificationResult, DocumentKind, IngestRouter
from nova.ingest.text_layer import (
    attachments,
    email_lines,
    is_image_only,
    pages_of,
    parse_eml,
)
from nova.llm.client import NovaLLMClient
from nova.models.documents import DocumentRecord, Page
from nova.store.state import AuditState

logger = logging.getLogger(__name__)


def load_batch_documents(batch_dir: str | Path) -> list[DocumentRecord]:
    """Parse all mailbox files and attachments in a batch folder into DocumentRecords.
    Handles recursive subdirectories for scenario test runners.
    """
    batch_path = Path(batch_dir).resolve()
    batch_name = batch_path.name
    documents: list[DocumentRecord] = []

    # 1. Recursively process all .eml files
    eml_files = sorted(batch_path.rglob("*.eml"))
    seen_standalone: set[str] = {f.name for f in eml_files}

    for eml_path in eml_files:
        try:
            raw_data = eml_path.read_bytes()
            msg = parse_eml(raw_data)

            received_dt = None
            if msg.get("Date"):
                try:
                    received_dt = parsedate_to_datetime(str(msg["Date"]))
                except Exception:
                    received_dt = None

            lines = email_lines(msg)
            body_text = "\n".join(lines)
            eml_doc_id = f"{batch_name}/{eml_path.relative_to(batch_path)}"
            email_record = DocumentRecord(
                doc_id=eml_doc_id,
                batch=batch_name,
                filename=eml_path.name,
                ext="eml",
                received_date=received_dt,
                is_scan=False,
                pages=[Page(page_number=1, text=body_text, is_empty=not body_text.strip())],
                parent_doc=None,
            )
            documents.append(email_record)

            for att_name, att_bytes in attachments(raw_data):
                if not att_name:
                    continue
                ext = att_name.rsplit(".", 1)[-1].lower() if "." in att_name else ""
                try:
                    pages_text = pages_of(att_bytes, ext)
                    scan = is_image_only(att_bytes, ext)
                except Exception as e:
                    logger.warning("Could not extract text for attachment %s in %s: %s", att_name, eml_path.name, e)
                    pages_text = []
                    scan = False

                pages = [
                    Page(page_number=i + 1, text=txt, is_empty=not txt.strip())
                    for i, txt in enumerate(pages_text)
                ]
                att_doc_id = f"{batch_name}/{eml_path.relative_to(batch_path)}#{att_name}"
                att_record = DocumentRecord(
                    doc_id=att_doc_id,
                    batch=batch_name,
                    filename=att_name,
                    ext=ext,
                    received_date=received_dt,
                    is_scan=scan,
                    pages=pages,
                    parent_doc=eml_doc_id,
                )
                documents.append(att_record)
        except Exception as e:
            logger.error("Error reading EML file %s: %s", eml_path.name, e, exc_info=True)

    # 2. Recursively process any loose PDF or XLSX files
    for loose_file in sorted(batch_path.rglob("*")):
        if loose_file.is_file() and loose_file.name not in seen_standalone:
            ext = loose_file.suffix.lstrip(".").lower()
            if ext in ("pdf", "xlsx"):
                try:
                    data = loose_file.read_bytes()
                    pages_text = pages_of(data, ext)
                    scan = is_image_only(data, ext)
                    pages = [
                        Page(page_number=i + 1, text=txt, is_empty=not txt.strip())
                        for i, txt in enumerate(pages_text)
                    ]
                    doc_id = f"{batch_name}/{loose_file.relative_to(batch_path)}"
                    record = DocumentRecord(
                        doc_id=doc_id,
                        batch=batch_name,
                        filename=loose_file.name,
                        ext=ext,
                        is_scan=scan,
                        pages=pages,
                        parent_doc=None,
                    )
                    documents.append(record)
                except Exception as e:
                    logger.error("Error reading loose file %s: %s", loose_file.name, e, exc_info=True)

    return documents


class IngestPipeline:
    """Orchestration engine coordinating Router classification and Extractor agents."""

    def __init__(
        self,
        client: NovaLLMClient | None = None,
        router: IngestRouter | None = None,
        contract_extractor: ContractExtractor | None = None,
        invoice_extractor: InvoiceExtractor | None = None,
    ) -> None:
        self.client = client or NovaLLMClient()
        self.router = router or IngestRouter(client=self.client)
        self.contract_extractor = contract_extractor or ContractExtractor(client=self.client)
        self.invoice_extractor = invoice_extractor or InvoiceExtractor(client=self.client)

    def process_document(
        self,
        doc: DocumentRecord,
        state: AuditState,
    ) -> ClassificationResult:
        """Classify a single document and route it to the appropriate extractor."""
        classification = self.router.classify_document(doc)
        logger.info(
            "Document %s classified as '%s' (confidence: %.2f)",
            doc.doc_id,
            classification.kind.value,
            classification.confidence,
        )

        if classification.kind in (DocumentKind.MSA, DocumentKind.AMENDMENT):
            logger.info("Routing %s to ContractExtractor", doc.doc_id)
            extraction = self.contract_extractor.extract_document(doc)
            for instrument in extraction.instruments:
                state.add_contract(instrument)
            if extraction.rate_rows:
                state.add_rate_rows(extraction.rate_rows)
            logger.info(
                "Extracted %d contract instrument(s) and %d rate row(s) from %s",
                len(extraction.instruments),
                len(extraction.rate_rows),
                doc.doc_id,
            )

        elif classification.kind == DocumentKind.INVOICE:
            logger.info("Routing %s to InvoiceExtractor", doc.doc_id)
            invoices = self.invoice_extractor.extract_document(doc)
            for inv in invoices:
                state.add_invoice(inv)
            total_lines = sum(len(inv.lines) for inv in invoices)
            logger.info(
                "Extracted %d invoice(s) with %d line items from %s",
                len(invoices),
                total_lines,
                doc.doc_id,
            )

        else:
            logger.debug(
                "Document %s kind '%s' currently has no specialized extractor assigned.",
                doc.doc_id,
                classification.kind.value,
            )

        state.mark_processed(doc.doc_id)
        return classification

    def process_batch(
        self,
        docs: list[DocumentRecord],
        state: AuditState | None = None,
    ) -> AuditState:
        """Process a batch of documents with error isolation per document."""
        if state is None:
            state = AuditState()

        for doc in docs:
            try:
                self.process_document(doc, state)
            except Exception as e:
                # Batch-level error handling: log and proceed with the remaining documents
                logger.error(
                    "Error processing document %s in batch %s: %s",
                    doc.doc_id,
                    doc.batch,
                    e,
                    exc_info=True,
                )

        return state


def run_pipeline(
    batch_dir: str | Path,
    state_dir: str | Path,
    client: NovaLLMClient | None = None,
) -> AuditState:
    """Execute complete ingestion pipeline for a batch folder and persist updated AuditState."""
    logger.info("Starting batch ingestion for %s (state_dir: %s)", batch_dir, state_dir)
    state = AuditState.load_from_dir(state_dir)
    docs = load_batch_documents(batch_dir)
    logger.info("Discovered %d documents/attachments in %s", len(docs), batch_dir)

    pipeline = IngestPipeline(client=client)
    updated_state = pipeline.process_batch(docs, state=state)

    updated_state.save_to_dir(state_dir)
    logger.info(
        "Batch ingestion complete. AuditState has %d contracts, %d rate rows, %d invoices.",
        len(updated_state.contracts),
        len(updated_state.rate_rows),
        len(updated_state.invoices),
    )
    return updated_state
