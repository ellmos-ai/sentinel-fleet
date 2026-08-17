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
    compliance_passed: bool = False
    compliance_violations: List[str] = Field(default_factory=list)
    dispute_email_draft: Optional[str] = None
