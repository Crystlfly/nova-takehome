"""Common enums, types, and references for the Nova audit system."""
from __future__ import annotations

from enum import Enum, IntEnum
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field


class Authority(IntEnum):
    """Hierarchical document authority rank (GLOSSARY.md: Which document wins).

    Lower numeric values represent strictly higher legal authority:
    1: Signed MSA, signed amendments, schedules, and annexes.
    2: Schedule 1 authorized contact email/letter or confirmed human feedback.
    3: Official transaction records: tracking export, milestone emails, AWBs, ledger, invoices.
    4: Unauthorized emails, unsigned drafts, proposals.
    5: Quoted text without original, external or automated text.
    """
    CONTRACT = 1
    SCHEDULE_1 = 2
    RECORD = 3
    UNAUTHORIZED = 4
    UNTRUSTED = 5

    def takes_precedence_over(self, other: Authority) -> bool:
        """Return True if this authority strictly outranks another."""
        return self.value < other.value


class Category(str, Enum):
    """Decision category for Schedule 1 authorized contacts."""
    RATES = "rates"
    WAIVERS = "waivers"
    PAYMENT_TERMS = "payment_terms"
    NOTICES = "notices"
    TREASURY = "treasury"
    BILLING_DISPUTES = "billing_disputes"
    KEY_ACCOUNT_MANAGER = "key_account_manager"


class ChargeType(str, Enum):
    """Classification of line item charges on freight contracts and invoices."""
    BASE_FREIGHT = "base_freight"
    FUEL_SURCHARGE = "fuel_surcharge"
    SECURITY_SURCHARGE = "security_surcharge"
    ACCESSORIAL = "accessorial"
    CUSTOMS_DUTY = "customs_duty"
    DISBURSEMENT = "disbursement"
    TAX = "tax"
    LATE_FEE = "late_fee"
    REBATE = "rebate"
    MARGIN_STEP_DOWN = "margin_step_down"
    PROMISED_CREDIT = "promised_credit"
    OTHER = "other"


class SourceRef(BaseModel):
    """Verifiable citation linking an extracted fact or finding to the mailbox source.

    Directly maps to the grader evidence schema:
    - doc: Relative mailbox path e.g. 'batch_01/0014.eml#INV-1.pdf' or 'batch_01/0014.eml'
    - page: 1-indexed page in PDF, 1-indexed sheet in XLSX, 1 for email body
    - quote: Exact verbatim string (minimum 12 non-whitespace characters)
    """
    model_config = ConfigDict(extra="forbid")

    doc: str = Field(
        ...,
        description="The document path in the mailbox (e.g., 'batch_01/0014.eml' or 'batch_01/0014.eml#INV-1.pdf')",
    )
    page: int = Field(
        ...,
        ge=1,
        description="1-indexed PDF page number, XLSX sheet index, or 1 for email body",
    )
    quote: str = Field(
        ...,
        min_length=1,
        description="Exact quote copied from the page for citation verification",
    )
