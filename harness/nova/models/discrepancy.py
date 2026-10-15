"""Discrepancy models for freight invoice auditing."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field

from nova.models.common import ChargeType, SourceRef
from nova.models.facts import RateRow



class LineDiscrepancy(BaseModel):
    """Discrepancy detected on a single invoice line item."""
    model_config = ConfigDict(extra="allow")

    line_number: int | None = Field(default=None, description="1-indexed line number if present on invoice")
    description: str = Field(..., description="Line description printed on invoice")
    charge_type: ChargeType = Field(..., description="Classification of the charge")
    billed_amount: Decimal = Field(..., description="Billed amount in original invoice currency")
    expected_amount: Decimal = Field(..., description="Expected contractual amount in invoice currency")
    discrepancy_amount: Decimal = Field(
        ...,
        description="Positive overcharge amount (billed - expected) in invoice currency",
    )
    currency: str = Field(..., description="Currency of the line item ('USD' or 'INR')")
    matched_rate: RateRow | None = Field(
        default=None,
        description="Matching contracted RateRow if found, or None if uncontracted charge",
    )
    is_uncontracted_charge: bool = Field(
        default=False,
        description="True if charge type or fee was not authorized by any active contract rate row",
    )
    evidence_source: SourceRef = Field(..., description="SourceRef citing line item on the invoice")
    rate_source: SourceRef | None = Field(
        default=None,
        description="SourceRef citing the rate clause in the contract if matched",
    )
    notes: str = Field(default="", description="Reconciliation rationale or discrepancy notes")


class InvoiceDiscrepancy(BaseModel):
    """Consolidated discrepancies, conflicts, and findings for an entire InvoiceDoc."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)


    invoice_id: str = Field(..., description="Canonical invoice identifier")
    contract_id: str | None = Field(default=None, description="Governing contract ID")
    carrier: str | None = Field(default=None, description="Carrier issuing invoice")
    shipper: str | None = Field(default=None, description="Shipper billed")
    invoice_date: date = Field(..., description="Invoice issuance date")
    pickup_date: date | None = Field(default=None, description="Shipment pickup date")
    currency: str = Field(..., description="Invoice original currency ('USD' or 'INR')")
    fx_rate_applied: Decimal | None = Field(
        default=None,
        description="Annex F conversion rate (INR per 1 USD) used if invoice currency is INR",
    )
    finding_class: str = Field(
        default="overcharge",
        alias="class",
        description="Discrepancy class ('overcharge', 'duplicate', etc.)",
    )
    verdict: str = Field(
        default="finding",
        description="Verdict: 'finding', 'conflict', 'cannot_determine', or 'no_finding'",
    )
    action: str = Field(
        default="draft:dispute",
        description="Recommended action ('draft:dispute', 'escalate', 'draft:request_document')",
    )
    amount_usd: str | None = Field(
        default=None,
        description="Single overcharge amount in USD string format (e.g. '196.92')",
    )
    amount_range: list[str] | None = Field(
        default=None,
        description="Range of possible amounts [low, high] for conflicts",
    )
    missing_doc: dict[str, Any] | None = Field(
        default=None,
        description="Missing document metadata (e.g. {'name': ..., 'holder': ...}) for cannot_determine",
    )
    discrepancy_lines: list[LineDiscrepancy] = Field(
        default_factory=list,
        description="Individual line discrepancies exceeding contracted amounts",
    )
    total_discrepancy_native: Decimal = Field(
        default=Decimal("0.00"),
        description="Total overcharge sum across lines in native invoice currency",
    )
    total_discrepancy_usd: Decimal = Field(
        default=Decimal("0.00"),
        description="Total overcharge converted to USD per GLOSSARY.md rules",
    )
    evidence: list[SourceRef] = Field(
        default_factory=list,
        description="Combined verifiable evidence citations (invoice lines and contract rates)",
    )

    def get(self, item: str, default: Any = None) -> Any:
        """Dict-like get for evaluation matching compatibility."""
        if hasattr(self, item):
            val = getattr(self, item)
            return val if val is not None else default
        if item == "class":
            return getattr(self, "finding_class", default)
        return default

    def __getitem__(self, item: str) -> Any:
        """Dict-like getitem for evaluation matching compatibility."""
        if hasattr(self, item):
            val = getattr(self, item)
            if val is not None:
                return val
        if item == "class":
            return getattr(self, "finding_class")
        raise KeyError(item)


__all__ = ["LineDiscrepancy", "InvoiceDiscrepancy"]

