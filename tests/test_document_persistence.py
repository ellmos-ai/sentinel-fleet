"""Structured document records survive a new web process facade."""

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.core.access import RequestPrincipal
from sentinel_fleet.core.structured_documents import (
    PersistentInvoiceWorkspace,
    StoredInvoiceRecord,
)
from sentinel_fleet.domains.omniledger.models import InvoiceDocument
from sentinel_fleet.web.server import (
    app,
    processed_invoices,
)


def test_extracted_invoice_record_survives_workspace_restart(tmp_path):
    path = tmp_path / "processed-documents.json"
    first = PersistentInvoiceWorkspace(
        LocalJsonStore("processed_documents", StoredInvoiceRecord, str(path))
    )
    invoice = InvoiceDocument(
        id="INV-PERSIST-1",
        filename="source.pdf",
        vendor_name="Persistence Vendor",
        invoice_number="P-1",
        invoice_date="2026-08-21",
        net_amount=100.0,
        tax_rate=19.0,
        tax_amount=19.0,
        gross_amount=119.0,
    )
    first[invoice.id] = invoice

    restarted = PersistentInvoiceWorkspace(
        LocalJsonStore("processed_documents", StoredInvoiceRecord, str(path))
    )
    assert restarted[invoice.id].invoice_number == "P-1"
    assert [item.id for item in restarted.values()] == [invoice.id]


def test_private_extracted_record_and_department_share_are_enforced_after_restart(tmp_path):
    path = tmp_path / "processed-documents-scoped.json"
    first = PersistentInvoiceWorkspace(
        LocalJsonStore("processed_documents", StoredInvoiceRecord, str(path))
    )
    alice = RequestPrincipal("alice", "alice", True, department="finance")
    bob = RequestPrincipal("bob", "bob", True, department="finance")
    outsider = RequestPrincipal("carol", "carol", True, department="operations")
    invoice = InvoiceDocument(
        id="INV-SCOPED-1",
        filename="private.pdf",
        vendor_name="Scoped Vendor",
        invoice_number="S-1",
        invoice_date="2026-08-21",
        net_amount=100.0,
        tax_rate=19.0,
        tax_amount=19.0,
        gross_amount=119.0,
    )
    first.put_scoped(invoice, alice)
    assert first.get_visible(invoice.id, bob) is None

    first.update_sharing(invoice.id, alice, "department")
    restarted = PersistentInvoiceWorkspace(
        LocalJsonStore("processed_documents", StoredInvoiceRecord, str(path))
    )
    assert restarted.get_visible(invoice.id, bob).invoice_number == "S-1"
    assert restarted.get_visible(invoice.id, outsider) is None


@pytest.mark.asyncio
async def test_structured_document_api_is_private_then_creator_shareable():
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as alice,
        AsyncClient(transport=transport, base_url="http://test") as bob,
    ):
        alice_access = (await alice.get("/api/access/me")).json()
        invoice = InvoiceDocument(
            id="INV-API-SCOPE-1",
            filename="api-private.pdf",
            vendor_name="Private Vendor",
            invoice_number="API-S-1",
            invoice_date="2026-08-21",
            net_amount=100.0,
            tax_rate=19.0,
            tax_amount=19.0,
            gross_amount=119.0,
        )
        processed_invoices.put_scoped(
            invoice,
            RequestPrincipal(
                "member:demo",
                alice_access["share_id"],
                department=alice_access["department"],
            ),
        )
        try:
            assert any(
                row["doc_id"] == invoice.id
                for row in (await alice.get("/api/omniledger/documents")).json()
            )
            assert not any(
                row["doc_id"] == invoice.id
                for row in (await bob.get("/api/omniledger/documents")).json()
            )

            shared = await alice.put(
                f"/api/omniledger/documents/{invoice.id}/sharing",
                json={"visibility": "department"},
            )
            assert shared.status_code == 200
            assert any(
                row["doc_id"] == invoice.id
                for row in (await bob.get("/api/omniledger/documents")).json()
            )
            assert (await bob.put(
                f"/api/omniledger/documents/{invoice.id}/sharing",
                json={"visibility": "organization"},
            )).status_code == 403
        finally:
            processed_invoices._store.delete(invoice.id)
