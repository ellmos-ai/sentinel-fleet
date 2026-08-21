"""Ledger entries retain accounting facts without duplicating full invoices."""

from uuid import uuid4

from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.domains.omniledger.models import (
    InvoiceDocument,
    InvoiceLineItem,
    InvoiceStatus,
)
from sentinel_fleet.domains.omniledger import reconciliation
from sentinel_fleet.memory.bank import memory_bank


def _invoice(*, doc_id: str | None = None) -> InvoiceDocument:
    return InvoiceDocument(
        id=doc_id or f"invoice-{uuid4().hex}",
        filename="confidential-invoice.pdf",
        vendor_name="Sensitive Supplier GmbH",
        vendor_email="billing@example.invalid",
        invoice_number=f"INV-{uuid4().hex}",
        invoice_date="2026-08-21",
        items=[
            InvoiceLineItem(
                description="Confidential consulting engagement",
                unit_price=100.0,
                total_price=100.0,
            )
        ],
        net_amount=100.0,
        tax_rate=19.0,
        tax_amount=19.0,
        gross_amount=119.0,
        currency="EUR",
        compliance_passed=True,
    )


def _reconciler(tmp_path, name: str):
    store = LocalJsonStore(
        name,
        reconciliation.LedgerEntry,
        persistence_path=str(tmp_path / f"{name}.json"),
    )
    return reconciliation.LedgerReconciler(store=store)


def test_booking_persists_only_minimal_accounting_facts_and_scopes_memory(tmp_path):
    reconciler = _reconciler(tmp_path, "minimal-ledger")
    invoice = _invoice()

    returned = reconciler.book_invoice(
        invoice,
        memory_owner="alice",
        organization_id="org-a",
    )

    assert returned is invoice
    assert returned.status == InvoiceStatus.BOOKED
    entry = reconciler.get_booked(
        invoice.id,
        requested_by="alice",
        requested_organization="org-a",
    )
    assert entry is not None
    assert entry.model_dump().keys() == {
        "doc_id",
        "invoice_number",
        "gross_amount",
        "currency",
        "status",
        "owner_id",
        "organization_id",
        "department_id",
        "visibility",
        "booked_at",
    }
    assert "Sensitive Supplier" not in entry.model_dump_json()
    assert "Confidential consulting" not in entry.model_dump_json()
    memory = memory_bank.get_memory(
        f"ledger:invoice:{invoice.invoice_number}",
        requested_by="alice",
        requested_organization="org-a",
    )
    assert memory is not None
    assert memory.organization_id == "org-a"


def test_private_department_and_organization_entries_enforce_acl(tmp_path):
    reconciler = _reconciler(tmp_path, "scoped-ledger")
    private_invoice = _invoice()
    department_invoice = _invoice()
    organization_invoice = _invoice()
    reconciler.book_invoice(
        private_invoice,
        memory_owner="alice",
        organization_id="org-a",
    )
    reconciler.book_invoice(
        department_invoice,
        memory_owner="alice",
        memory_visibility="department",
        department_id="finance",
        organization_id="org-a",
    )
    reconciler.book_invoice(
        organization_invoice,
        memory_owner="alice",
        memory_visibility="organization",
        organization_id="org-a",
    )

    assert reconciler.get_booked(
        private_invoice.id,
        requested_by="bob",
        requested_organization="org-a",
    ) is None
    assert reconciler.get_booked(
        department_invoice.id,
        requested_by="bob",
        requested_department="legal",
        requested_organization="org-a",
    ) is None
    assert reconciler.get_booked(
        department_invoice.id,
        requested_by="bob",
        requested_department="finance",
        requested_organization="org-a",
    ) is not None
    assert reconciler.get_booked(
        organization_invoice.id,
        requested_by="mallory",
        requested_organization="org-b",
    ) is None
    visible = reconciler.list_booked(
        requested_by="bob",
        requested_department="finance",
        requested_organization="org-a",
    )
    assert {entry.doc_id for entry in visible} == {
        department_invoice.id,
        organization_invoice.id,
    }


def test_legacy_full_invoice_loads_as_a_fail_closed_minimal_entry():
    invoice = _invoice(doc_id="legacy-invoice")
    invoice.status = InvoiceStatus.BOOKED

    entry = reconciliation.LedgerEntry.model_validate(invoice.model_dump(mode="json"))

    assert entry.doc_id == "legacy-invoice"
    assert entry.owner_id == "legacy-unassigned"
    assert entry.organization_id == "legacy-unassigned"
    assert entry.visibility == "private"
    assert "filename" not in entry.model_dump()
    assert "vendor_name" not in entry.model_dump()
