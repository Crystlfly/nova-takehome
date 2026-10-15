"""State store for persisting intermediate facts and batch state with atomic writes."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field

from nova.config import DEFAULT_STATE_DIR
from nova.models.facts import (
    CashbackRule,
    ContractInstrument,
    FxRateRow,
    InvoiceDoc,
    PaymentRecord,
    RateRow,
    TrackingEvent,
    WaiverGrant,
)


class DecimalJsonEncoder(json.JSONEncoder):
    """JSON Encoder that handles Decimals, dates, and sets."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, set):
            return list(obj)
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return super().default(obj)


class StateStore:
    """Handles saving and loading JSON files to a state directory with atomic writes."""

    def __init__(self, state_dir: str | Path = DEFAULT_STATE_DIR):
        self.state_dir = Path(state_dir).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, rel_path: str | Path) -> Path:
        """Resolve a relative path inside the state directory."""
        return self.state_dir / rel_path

    def exists(self, rel_path: str | Path) -> bool:
        """Check if a file exists in the state directory."""
        return self.get_path(rel_path).is_file()

    def save_json(self, rel_path: str | Path, data: Any, indent: int = 2) -> Path:
        """Atomically write JSON data to a relative path within state_dir.

        Writes to a temporary file in the target directory first, then renames it
        using os.replace to guarantee atomic updates and prevent partially written files.
        """
        target = self.get_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory to ensure it is on the same filesystem
        temp_fd, temp_path = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, cls=DecimalJsonEncoder, indent=indent)
                f.write("\n")
            # os.replace is atomic on both POSIX and Windows (Python 3.3+)
            os.replace(temp_path, target)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

        return target

    def load_json(self, rel_path: str | Path, default: Any = None) -> Any:
        """Load JSON data from a relative path within state_dir, or return default if missing."""
        target = self.get_path(rel_path)
        if not target.is_file():
            return default

        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_files(self, pattern: str = "*.json") -> list[Path]:
        """List files matching a glob pattern inside the state directory."""
        return sorted(self.state_dir.glob(pattern))


class AuditState(BaseModel):
    """Central repository of all facts and records extracted across mailbox batches."""
    model_config = ConfigDict(extra="allow")

    contracts: list[ContractInstrument] = Field(
        default_factory=list,
        description="Master agreements, amendments, and contract instruments.",
    )
    rate_rows: list[RateRow] = Field(
        default_factory=list,
        description="Extracted rate table rows from agreements and amendments.",
    )
    invoices: list[InvoiceDoc] = Field(
        default_factory=list,
        description="Extracted billing invoices and credit notes.",
    )
    payments: list[PaymentRecord] = Field(
        default_factory=list,
        description="Settled and scheduled payment records.",
    )
    tracking_events: list[TrackingEvent] = Field(
        default_factory=list,
        description="Operational milestone tracking events.",
    )
    waivers: list[WaiverGrant] = Field(
        default_factory=list,
        description="Fee and rate waiver grants.",
    )
    cashback_rules: list[CashbackRule] = Field(
        default_factory=list,
        description="Rebate and cashback terms.",
    )
    fx_rates: list[FxRateRow] = Field(
        default_factory=list,
        description="Annex F exchange rates (INR per 1 USD).",
    )
    processed_doc_ids: list[str] = Field(
        default_factory=list,
        description="Canonical doc_ids that have already been ingested.",
    )
    feedback_decisions: dict[str, Any] = Field(
        default_factory=dict,
        description="Decisions received from human feedback files.",
    )

    def add_contract(self, instrument: ContractInstrument) -> None:
        """Add or update a contract instrument."""
        self.contracts.append(instrument)

    def add_rate_rows(self, rows: list[RateRow]) -> None:
        """Add a batch of rate rows."""
        self.rate_rows.extend(rows)

    def add_invoice(self, invoice: InvoiceDoc) -> None:
        """Add or update an invoice document."""
        # Replace existing invoice with same ID if re-processed, otherwise append
        for i, existing in enumerate(self.invoices):
            if existing.invoice_id == invoice.invoice_id:
                self.invoices[i] = invoice
                return
        self.invoices.append(invoice)

    def mark_processed(self, doc_id: str) -> None:
        """Mark document ID as processed."""
        if doc_id not in self.processed_doc_ids:
            self.processed_doc_ids.append(doc_id)

    def save_to_dir(self, state_dir: str | Path) -> Path:
        """Persist this AuditState to audit_state.json in state_dir."""
        store = StateStore(state_dir)
        return store.save_json("audit_state.json", self.model_dump(mode="json"))

    @classmethod
    def load_from_dir(cls, state_dir: str | Path) -> AuditState:
        """Load AuditState from state_dir, or return fresh AuditState if not found."""
        store = StateStore(state_dir)
        data = store.load_json("audit_state.json")
        if data is None:
            return cls()
        return cls.model_validate(data)
