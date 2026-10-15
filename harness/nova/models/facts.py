"""Fact models extracted from contracts, invoices, emails, tracking logs, and ledgers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Union
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field

from nova.models.common import Authority, Category, ChargeType, SourceRef


class Schedule1Contact(BaseModel):
    """An authorized representative listed in Schedule 1 of a contract."""
    model_config = ConfigDict(extra="forbid")

    party: str = Field(..., description="Entity name (carrier, shipper, etc.)")
    person: str = Field(..., description="Contact person full name")
    role: str | None = Field(default=None, description="Job title or functional role")
    email: str | None = Field(default=None, description="Email address")
    category: Category = Field(..., description="Authorized decision category")
    source: SourceRef = Field(..., description="Verifiable evidence citation")


class RateRow(BaseModel):
    """An individual freight rate entry from an MSA, amendment, or rate schedule."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rate_row"] = "rate_row"
    contract_id: str = Field(..., description="Contract ID, e.g. 'CTR-2040-001'")
    origin: str | None = Field(default=None, description="Origin location or airport code (if lane-specific)")
    destination: str | None = Field(default=None, description="Destination location or airport code (if lane-specific)")
    lane: str | None = Field(default=None, description="Lane identifier (e.g. 'BOM-ORD')")
    charge_type: ChargeType = Field(default=ChargeType.BASE_FREIGHT, description="Charge classification")
    min_weight_kg: Decimal | None = Field(default=None, description="Minimum weight bracket in kg")
    max_weight_kg: Decimal | None = Field(default=None, description="Maximum weight bracket in kg")
    rate_per_kg: Decimal | None = Field(default=None, description="Rate per kg in currency")
    flat_fee: Decimal | None = Field(default=None, description="Flat rate fee if applicable")
    percentage_rate: Decimal | None = Field(default=None, description="Percentage rate (e.g. 15.5 for 15.5%)")
    currency: str = Field(default="USD", description="Currency of the rate ('USD' or 'INR')")
    effective_date: date | None = Field(default=None, description="Rate validity start date")
    expiration_date: date | None = Field(default=None, description="Rate validity end date")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.CONTRACT, description="Document authority rank")


class ContractInstrument(BaseModel):
    """An agreement, Master Services Agreement (MSA), amendment, or annex."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["contract_instrument"] = "contract_instrument"
    contract_id: str = Field(..., description="Unique contract identifier")
    instrument_type: str = Field(..., description="Instrument type: 'msa', 'amendment', 'annex_d', etc.")
    title: str | None = Field(default=None, description="Formal document title")
    parties: list[str] = Field(default_factory=list, description="Named contracting parties")
    effective_date: date | None = Field(default=None, description="Agreement effective date")
    expiration_date: date | None = Field(default=None, description="Agreement expiration date")
    auto_renewal: bool = Field(default=False, description="Whether agreement renews automatically")
    renewal_notice_days: int | None = Field(
        default=None,
        description="Notice window days before expiration required for non-renewal",
    )
    payment_terms_days: int | None = Field(default=None, description="Net payment terms in days (e.g. 30)")
    grace_period_days: int = Field(default=0, description="Grace period days before late fees accrue")
    late_fee_rate_pct: Decimal | None = Field(
        default=None,
        description="Late fee percentage per 30-day period (e.g. 1.5 for 1.5%)",
    )
    late_fee_compounds: bool = Field(default=False, description="Whether late fee compounds onto unpaid fees")
    schedule1_contacts: list[Schedule1Contact] = Field(
        default_factory=list,
        description="Authorized contacts from Schedule 1",
    )
    amendment_number: str | None = Field(default=None, description="Amendment designation if applicable")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.CONTRACT, description="Document authority rank")


class FxRateRow(BaseModel):
    """Foreign exchange conversion rate row from Annex F (INR per 1 USD)."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fx_rate_row"] = "fx_rate_row"
    contract_id: str = Field(..., description="Governing contract ID")
    month_key: str = Field(..., description="Calendar month formatted 'YYYY-MM', e.g. '2040-05'")
    inr_per_usd: Decimal = Field(..., gt=0, description="Exchange rate (INR per 1 USD)")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.CONTRACT, description="Document authority rank")


class TrackingEvent(BaseModel):
    """Milestone event from tracking export or carrier status notifications."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tracking_event"] = "tracking_event"
    shipment_id: str = Field(..., description="Shipment reference, AWB number, or tracking code")
    event_type: str = Field(
        ...,
        description="Milestone code: 'PICKED_UP', 'DELIVERED', 'CUSTOMS_CLEARED', etc.",
    )
    event_date: date = Field(..., description="Date event occurred")
    weight_kg: Decimal | None = Field(default=None, description="Actual or chargeable weight in kg")
    pieces: int | None = Field(default=None, description="Piece count")
    origin: str | None = Field(default=None, description="Origin airport/city")
    destination: str | None = Field(default=None, description="Destination airport/city")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.RECORD, description="Document authority rank")


class InvoiceLine(BaseModel):
    """An individual billed line item on an invoice or credit note."""
    model_config = ConfigDict(extra="forbid")

    line_number: int | None = Field(default=None, description="Printed line index")
    description: str = Field(..., description="Description as printed on invoice")
    charge_type: ChargeType = Field(default=ChargeType.BASE_FREIGHT, description="Charge classification")
    quantity: Decimal | None = Field(default=None, description="Chargeable weight, pieces, or days")
    unit_rate: Decimal | None = Field(default=None, description="Unit rate billed")
    amount: Decimal = Field(..., description="Total line amount billed")
    currency: str = Field(default="USD", description="Currency of line item ('USD' or 'INR')")
    source: SourceRef = Field(..., description="Verifiable evidence citation")


class InvoiceDoc(BaseModel):
    """A freight invoice or credit note document."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["invoice_doc"] = "invoice_doc"
    invoice_id: str = Field(
        ...,
        description="Canonical uppercase invoice number without spaces, #, or :, e.g. 'INV-2040-0012'",
    )
    is_credit_note: bool = Field(default=False, description="True if credit note, False if invoice")
    credited_invoice_id: str | None = Field(
        default=None,
        description="Original invoice ID referenced if this is a credit note",
    )
    contract_id: str | None = Field(default=None, description="Contract ID referenced on invoice")
    carrier: str | None = Field(default=None, description="Issuing carrier name")
    shipper: str | None = Field(default=None, description="Billed customer/shipper name")
    invoice_date: date = Field(..., description="Invoice issuance date")
    due_date: date | None = Field(default=None, description="Payment due date printed on invoice")
    total_amount: Decimal = Field(..., description="Total billed invoice amount")
    currency: str = Field(default="USD", description="Invoice currency ('USD' or 'INR')")
    shipment_id: str | None = Field(default=None, description="AWB or tracking reference number")
    pickup_date: date | None = Field(default=None, description="Shipment pickup date printed on invoice")
    origin: str | None = Field(default=None, description="Origin code")
    destination: str | None = Field(default=None, description="Destination code")
    chargeable_weight_kg: Decimal | None = Field(default=None, description="Chargeable weight in kg")
    lines: list[InvoiceLine] = Field(default_factory=list, description="Extracted line items")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.RECORD, description="Document authority rank")


class PaymentRecord(BaseModel):
    """Payment transaction or scheduled payment from the shipper's payment ledger."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["payment_record"] = "payment_record"
    invoice_id: str = Field(..., description="Invoice ID matched to payment")
    paid_date: date = Field(..., description="Date payment was settled or scheduled")
    amount_paid: Decimal = Field(..., description="Settled or scheduled payment amount")
    currency: str = Field(default="USD", description="Payment currency")
    status: str = Field(default="PAID", description="Payment status: 'PAID', 'SCHEDULED', or 'PENDING'")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.RECORD, description="Document authority rank")


class WaiverGrant(BaseModel):
    """A formal fee or charge waiver communication."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["waiver_grant"] = "waiver_grant"
    contract_id: str | None = Field(default=None, description="Governing contract ID")
    granted_by_person: str = Field(..., description="Name of person granting the waiver")
    granted_by_email: str | None = Field(default=None, description="Email address of grantor")
    granted_date: date = Field(..., description="Date waiver was granted")
    shipment_id: str | None = Field(default=None, description="Specific shipment AWB/tracking ID waived")
    invoice_id: str | None = Field(default=None, description="Specific invoice ID waived")
    charge_type: ChargeType | None = Field(default=None, description="Specific charge type waived")
    scope_description: str = Field(..., description="Text summary of waiver scope")
    condition: str | None = Field(default=None, description="Stated condition required for waiver")
    condition_met: bool = Field(default=True, description="Whether all stated conditions were verified met")
    is_quoted_text: bool = Field(
        default=False,
        description="True if waiver is only seen quoted in a forwarded email without original",
    )
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.SCHEDULE_1, description="Document authority rank")


class CashbackRule(BaseModel):
    """Terms governing volume rebates, margin step-downs, or promised credits."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["cashback_rule"] = "cashback_rule"
    contract_id: str = Field(..., description="Governing contract ID")
    credit_type: str = Field(
        ...,
        description="'rebate' (quarterly), 'margin_step_down' (quarterly), or 'promised_credit' (annual CYn)",
    )
    period_type: str = Field(default="quarterly", description="'quarterly' or 'contract_year'")
    qualifying_threshold_usd: Decimal | None = Field(default=None, description="Qualifying spend threshold in USD")
    rebate_pct: Decimal | None = Field(default=None, description="Rebate percentage applied to spend")
    credit_amount_usd: Decimal | None = Field(default=None, description="Fixed promised credit amount in USD")
    source: SourceRef = Field(..., description="Verifiable evidence citation")
    authority: Authority = Field(default=Authority.CONTRACT, description="Document authority rank")


# Discriminated union of all extracted fact types
ExtractedFacts = Annotated[
    Union[
        RateRow,
        ContractInstrument,
        FxRateRow,
        TrackingEvent,
        InvoiceDoc,
        PaymentRecord,
        WaiverGrant,
        CashbackRule,
    ],
    Field(discriminator="kind"),
]


class ExtractedFactCollection(BaseModel):
    """Container grouping all extracted facts for a document or batch."""
    model_config = ConfigDict(extra="forbid")

    rate_rows: list[RateRow] = Field(default_factory=list)
    contracts: list[ContractInstrument] = Field(default_factory=list)
    fx_rates: list[FxRateRow] = Field(default_factory=list)
    tracking_events: list[TrackingEvent] = Field(default_factory=list)
    invoices: list[InvoiceDoc] = Field(default_factory=list)
    payments: list[PaymentRecord] = Field(default_factory=list)
    waivers: list[WaiverGrant] = Field(default_factory=list)
    cashback_rules: list[CashbackRule] = Field(default_factory=list)
