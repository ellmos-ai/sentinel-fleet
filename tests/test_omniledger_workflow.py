"""Unit tests for OmniLedger Extraction, Tax Compliance & Dispute Loop."""

import pytest
from sentinel_fleet.domains.omniledger.extractor import MultimodalExtractor
from sentinel_fleet.domains.omniledger.compliance import ComplianceAuditor
from sentinel_fleet.domains.omniledger.dispute_loop import DisputeCommunicator
from sentinel_fleet.domains.omniledger.reconciliation import LedgerReconciler
from sentinel_fleet.domains.omniledger.models import InvoiceStatus


@pytest.mark.asyncio
async def test_valid_invoice_flow():
    extractor = MultimodalExtractor()
    doc = await extractor.extract_invoice(filename="CleanInvoice.pdf", text_content="Acme Tech Supplies GmbH")
    
    doc = ComplianceAuditor.audit_invoice(doc)
    assert doc.compliance_passed is True
    assert doc.status == InvoiceStatus.COMPLIANCE_VERIFIED

    reconciler = LedgerReconciler()
    doc = reconciler.book_invoice(doc)
    assert doc.status == InvoiceStatus.BOOKED


@pytest.mark.asyncio
async def test_missing_vat_triggers_dispute_loop():
    extractor = MultimodalExtractor()
    doc = await extractor.extract_invoice(filename="Invoice_MissingVAT_CS.pdf")
    
    doc = ComplianceAuditor.audit_invoice(doc)
    assert doc.compliance_passed is False
    assert doc.status == InvoiceStatus.DISPUTED
    assert any("Steuernummer" in v for v in doc.compliance_violations)

    email_draft = DisputeCommunicator.generate_dispute_resolution(doc)
    assert "14 UStG" in email_draft
    assert "korrigiert" in email_draft.lower() or "korrektur" in email_draft.lower()


@pytest.mark.asyncio
async def test_math_error_triggers_compliance_block():
    extractor = MultimodalExtractor()
    doc = await extractor.extract_invoice(filename="Invoice_MathError_Office.pdf")
    
    doc = ComplianceAuditor.audit_invoice(doc)
    assert doc.compliance_passed is False
    assert any("mathematisch inkonsistent" in v for v in doc.compliance_violations)
