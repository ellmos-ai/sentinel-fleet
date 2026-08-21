"""Unit tests for the vendor correction letter: the schema binding, the PDF and the endpoint."""

import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from sentinel_fleet.core.privacy_contacts import privacy_contact_hub
from sentinel_fleet.domains.omniledger.letter import (
    CORRECTION_DEADLINE_DAYS,
    build_correction_letter,
    letter_filename,
    render_correction_letter_pdf,
)
from sentinel_fleet.domains.omniledger.models import InvoiceDocument, InvoiceStatus
from sentinel_fleet.uas.ticket_master import ticket_master
from sentinel_fleet.web.server import app, processed_invoices

# 2026-08-04 12:00:00 UTC, so the derived deadline is a fixed, checkable date
ISSUED_AT = 1785844800.0


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _defective_invoice(email="finance@vendor-under-test.example") -> InvoiceDocument:
    return InvoiceDocument(
        id="INV-LETTERTEST",
        filename="Invoice_MissingVAT.pdf",
        vendor_name="Cloud Solutions Global Inc.",
        vendor_vat_id="",
        vendor_address="100 Tech Blvd, Mountain View, CA",
        vendor_email=email,
        invoice_number="CS-2026-9912",
        invoice_date="2026-08-15",
        net_amount=1200.0,
        tax_rate=19.0,
        tax_amount=228.0,
        gross_amount=1428.0,
        currency="EUR",
        status=InvoiceStatus.DISPUTED,
        compliance_violations=["Issuer VAT ID is missing (§ 14 Abs. 4 Nr. 2 UStG)"],
    )


def _pdf_text(payload: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(payload)).pages)


def test_schema_binds_only_what_the_letter_may_state():
    letter = build_correction_letter(_defective_invoice(), ISSUED_AT)

    assert letter.invoice_number == "CS-2026-9912"
    assert letter.defects == ["Issuer VAT ID is missing (§ 14 Abs. 4 Nr. 2 UStG)"]
    assert letter.issued_on == "2026-08-04"
    assert letter.deadline_on == "2026-08-18"


def test_deadline_is_the_stated_period_after_the_issue_date():
    from datetime import date

    letter = build_correction_letter(_defective_invoice(), ISSUED_AT)
    span = date.fromisoformat(letter.deadline_on) - date.fromisoformat(letter.issued_on)

    assert span.days == CORRECTION_DEADLINE_DAYS


def test_render_produces_a_real_pdf_carrying_the_letter_content():
    payload = render_correction_letter_pdf(build_correction_letter(_defective_invoice(), ISSUED_AT))

    assert payload.startswith(b"%PDF")
    text = _pdf_text(payload)
    assert "CS-2026-9912" in text
    assert "Cloud Solutions Global Inc." in text
    assert "2026-08-18" in text
    assert "VAT ID is missing" in text
    # The core fonts have no euro glyph; the substitution keeps the amount readable
    assert "1428.00 EUR" in text


def test_render_is_reproducible_for_the_same_ticket():
    """A letter that moved its own deadline between downloads would be useless as evidence."""
    invoice = _defective_invoice()

    first = render_correction_letter_pdf(build_correction_letter(invoice, ISSUED_AT))
    second = render_correction_letter_pdf(build_correction_letter(invoice, ISSUED_AT))

    assert _pdf_text(first) == _pdf_text(second)


def test_letter_without_defects_says_so_instead_of_leaving_a_gap():
    invoice = _defective_invoice()
    invoice.compliance_violations = []

    text = _pdf_text(render_correction_letter_pdf(build_correction_letter(invoice, ISSUED_AT)))

    assert "no defects recorded" in text


def test_filename_is_derived_from_the_invoice_number():
    letter = build_correction_letter(_defective_invoice(), ISSUED_AT)

    assert letter_filename(letter) == "correction-letter-CS-2026-9912.pdf"


@pytest.mark.asyncio
async def test_endpoint_serves_the_letter_for_a_dispute_ticket(client):
    invoice = _defective_invoice()
    processed_invoices[invoice.id] = invoice
    ticket = ticket_master.create_approval_ticket(
        title="Approval: correction request",
        description="letter endpoint test",
        agent_id="agent:vendor-dispute",
        tool_name="send_external_email",
        payload={"doc_id": invoice.id, "vendor_email": invoice.vendor_email},
    )

    response = await client.get(f"/api/tickets/{ticket.ticket_id}/letter.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "correction-letter-CS-2026-9912.pdf" in response.headers["content-disposition"]
    assert response.headers["x-sentinel-artifact-id"].startswith("artifact-")
    assert response.content.startswith(b"%PDF")
    assert "CS-2026-9912" in _pdf_text(response.content)


@pytest.mark.asyncio
async def test_letter_render_appears_on_the_gate_ledger(client):
    """The render is a tool call like any other, so it leaves a row an auditor can find."""
    from sentinel_fleet.core.telemetry import telemetry

    invoice = _defective_invoice()
    processed_invoices[invoice.id] = invoice
    ticket = ticket_master.create_approval_ticket(
        title="Approval: correction request",
        description="ledger test",
        agent_id="agent:vendor-dispute",
        tool_name="send_external_email",
        payload={"doc_id": invoice.id},
    )

    await client.get(f"/api/tickets/{ticket.ticket_id}/letter.pdf")

    assert any(
        span.name == "tool_call:render_dispute_letter"
        for span in telemetry.get_recent_spans(30)
    )


@pytest.mark.asyncio
async def test_approval_card_offers_the_download(client):
    invoice = _defective_invoice()
    processed_invoices[invoice.id] = invoice
    ticket = ticket_master.create_approval_ticket(
        title="Approval: correction request",
        description="console rendering test",
        agent_id="agent:vendor-dispute",
        tool_name="send_external_email",
        payload={"doc_id": invoice.id},
    )

    body = (await client.get("/")).text

    assert f"/api/tickets/{ticket.ticket_id}/letter.pdf" in body
    assert "Download letter (PDF)" in body


@pytest.mark.asyncio
async def test_unknown_ticket_is_a_404(client):
    response = await client.get("/api/tickets/TICK-NOSUCH/letter.pdf")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ticket_without_an_invoice_has_no_letter(client):
    ticket = ticket_master.create_approval_ticket(
        title="Operator ticket",
        description="not a dispute",
        agent_id="agent:orchestrator",
        tool_name="operator_manual_ticket",
        payload={},
    )

    response = await client.get(f"/api/tickets/{ticket.ticket_id}/letter.pdf")

    assert response.status_code == 404
    assert "not an invoice dispute" in response.json()["detail"]


@pytest.mark.asyncio
async def test_opted_out_vendor_gets_no_letter_rendered(client):
    """A letter is outbound correspondence too; the opt-out gate has to hold for it as well."""
    contact = privacy_contact_hub.add_contact(
        name="Opted Out Vendor",
        email="optout@vendor-under-test.example",
        organization="Opted Out Vendor Ltd",
        category="vendor",
    )
    privacy_contact_hub.mark_opt_out(contact.contact_id, "test opt-out")

    invoice = _defective_invoice(email=contact.email)
    invoice.id = "INV-LETTERTEST-OPTOUT"
    processed_invoices[invoice.id] = invoice
    ticket = ticket_master.create_approval_ticket(
        title="Approval: correction request",
        description="opt-out test",
        agent_id="agent:vendor-dispute",
        tool_name="send_external_email",
        payload={"doc_id": invoice.id},
    )

    response = await client.get(f"/api/tickets/{ticket.ticket_id}/letter.pdf")

    assert response.status_code == 403
