"""Nova Audit Pipeline Entry Point: CLI runner for batch ingestion and audit reconciliation.

Usage:
    python -m harness --batch-dir <path> --state-dir <path> --output <results.json>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

# pyrefly: ignore [missing-import]
from pydantic import BaseModel

# Ensure harness directory is in python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load environment variables from .env
try:
    # pyrefly: ignore [missing-import]
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from nova.engine.audit import AuditEngine, InvoiceDiscrepancy
from nova.engine.pipeline import IngestPipeline, load_batch_documents
from nova.store.state import AuditState



class NovaJsonEncoder(json.JSONEncoder):
    """Robust custom JSON encoder handling Pydantic models, Decimals, dates, and Enums."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (set, frozenset)):
            return sorted(list(obj))
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return super().default(obj)


def configure_logging(verbose: bool = False) -> None:
    """Setup clean and readable CLI logging format."""
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]


def run_audit_pipeline(
    batch_dir: str | Path,
    state_dir: str | Path,
    output_path: str | Path,
) -> list[InvoiceDiscrepancy]:
    """Execute the end-to-end audit process and write results.json."""
    logger = logging.getLogger("nova.cli")
    batch_path = Path(batch_dir).resolve()
    state_path = Path(state_dir).resolve()
    out_file = Path(output_path).resolve()

    logger.info("==================================================")
    logger.info("NOVA FREIGHT AUDIT SYSTEM - EXECUTION PIPELINE")
    logger.info("==================================================")
    logger.info("Input Batch Directory:  %s", batch_path)
    logger.info("State Directory:        %s", state_path)
    logger.info("Output File:            %s", out_file)

    # 1. Load or initialize AuditState
    logger.info("Loading central AuditState from %s ...", state_path)
    state = AuditState.load_from_dir(state_path)
    logger.info(
        "Initial State: %d contracts, %d rate rows, %d invoices previously recorded.",
        len(state.contracts),
        len(state.rate_rows),
        len(state.invoices),
    )

    # 2. Ingest batch documents
    logger.info("Discovering and parsing documents from batch %s ...", batch_path.name)
    docs = load_batch_documents(batch_path)
    logger.info("Discovered %d documents and attachments in batch.", len(docs))

    # 3. Run Ingest Pipeline (Router & Extractor Agents)
    logger.info("Routing and extracting facts via IngestPipeline ...")
    pipeline = IngestPipeline()
    state = pipeline.process_batch(docs, state=state)

    # Persist updated state atomically
    state.save_to_dir(state_path)
    logger.info(
        "Ingestion complete. Updated State: %d contracts, %d rate rows, %d invoices.",
        len(state.contracts),
        len(state.rate_rows),
        len(state.invoices),
    )

    # 4. Audit Engine Reconciliation
    logger.info("Executing AuditEngine discrepancy detection ...")
    engine = AuditEngine(state)
    discrepancies = engine.run_audit()

    total_discrepancy_usd = sum(d.total_discrepancy_usd for d in discrepancies)
    logger.info("Audit reconciliation finished:")
    logger.info(" - Invoices Audited:      %d", len(state.invoices))
    logger.info(" - Discrepancies Found:   %d", len(discrepancies))
    logger.info(" - Total Disputed Amount: $%s USD", total_discrepancy_usd)

    # 5. Serialize into output results.json
    logger.info("Serializing findings to %s ...", out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    result_payload = {
        "status": "success",
        "batch": batch_path.name,
        "audited_invoices_count": len(state.invoices),
        "discrepancies_count": len(discrepancies),
        "total_discrepancy_usd": str(total_discrepancy_usd),
        "discrepancies": [d.model_dump(mode="json") for d in discrepancies],
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, cls=NovaJsonEncoder, indent=2)
        f.write("\n")

    logger.info("Successfully wrote results to %s.", out_file)
    logger.info("==================================================")
    return discrepancies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness",
        description="Nova Freight Audit Execution & Discrepancy Reconciliation CLI",
    )
    parser.add_argument(
        "--batch-dir",
        required=True,
        help="Path to the directory containing input batch documents (.eml, PDF, XLSX)",
    )
    parser.add_argument(
        "--state-dir",
        default=".state",
        help="Path to the directory storing persistent AuditState (default: .state)",
    )
    parser.add_argument(
        "--output",
        default="results.json",
        help="Path to the output results file (default: results.json)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)

    try:
        run_audit_pipeline(
            batch_dir=args.batch_dir,
            state_dir=args.state_dir,
            output_path=args.output,
        )
        return 0
    except Exception as e:
        logging.getLogger("nova.cli").error("Fatal error during audit execution: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
