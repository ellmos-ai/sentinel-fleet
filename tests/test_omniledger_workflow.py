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
    assert any("VAT ID is missing" in v for v in doc.compliance_violations)

    email_draft = DisputeCommunicator.generate_dispute_resolution(doc)
    # The statute reference stays German because it cites German law verbatim
    assert "14 UStG" in email_draft
    assert "corrected invoice" in email_draft.lower() or "invoice correction" in email_draft.lower()


@pytest.mark.asyncio
async def test_dispute_draft_embeds_retrieved_memory_context():
    """M1: retrieved RAG clues must reach the draft instead of being fetched and dropped."""
    extractor = MultimodalExtractor()
    doc = await extractor.extract_invoice(filename="Invoice_MissingVAT_CS.pdf")
    doc = ComplianceAuditor.audit_invoice(doc)

    body = DisputeCommunicator.generate_dispute_resolution(doc)

    assert "Reference context" in body
    # The statute chunk retrieved from the GARDENER corpus must be quoted in the draft
    assert "UStG_Paragraph_14" in body
    assert "[LEGAL_DOC:" in body


@pytest.mark.asyncio
async def test_math_error_triggers_compliance_block():
    extractor = MultimodalExtractor()
    doc = await extractor.extract_invoice(filename="Invoice_MathError_Office.pdf")
    
    doc = ComplianceAuditor.audit_invoice(doc)
    assert doc.compliance_passed is False
    assert any("arithmetically inconsistent" in v for v in doc.compliance_violations)
