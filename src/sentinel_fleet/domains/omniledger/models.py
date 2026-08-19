"""Data models for OmniLedger Invoice & Compliance Domain."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class InvoiceStatus(str, Enum):
    RECEIVED = "received"
    EXTRACTED = "extracted"
    COMPLIANCE_VERIFIED = "compliance_verified"
    DISPUTED = "disputed"
    BOOKED = "booked"
    PAID = "paid"


class ExtractionMode(str, Enum):
    """Declares which backend produced an extraction. Never claim a live model for demo data."""
    GEMINI = "gemini-3.5"
    # Read locally out of the document's own text layer - real values, but only what the text
    # states: no vision, no OCR, no line items.
    LOCAL_TEXT_LAYER = "local-text-layer"
    DETERMINISTIC_DEMO = "deterministic-demo"


class InvoiceLineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    total_price: float


class InvoiceDocument(BaseModel):
    id: str
    filename: str
    vendor_name: str
    vendor_vat_id: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_email: Optional[str] = None
    invoice_number: str
    invoice_date: str
    delivery_date: Optional[str] = None
    items: List[InvoiceLineItem] = Field(default_factory=list)
    net_amount: float
    tax_rate: float
    tax_amount: float
    gross_amount: float
    currency: str = "EUR"
    status: InvoiceStatus = InvoiceStatus.RECEIVED
    extraction_mode: ExtractionMode = ExtractionMode.DETERMINISTIC_DEMO
    # How this document was read and what the reader could not do: the privacy verdict of the
    # pre-model screen, the backend that read the text layer, the fields it did not find. Free
    # evidence lines rather than typed flags - nothing here is a state another field derives from.
    extraction_notes: List[str] = Field(default_factory=list)
    compliance_passed: bool = False
    compliance_violations: List[str] = Field(default_factory=list)
    dispute_email_draft: Optional[str] = None
