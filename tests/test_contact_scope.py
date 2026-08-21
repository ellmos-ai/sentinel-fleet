"""Tenant-isolation regressions for contacts and dispute context."""

import time

from sentinel_fleet.core.privacy_contacts import PrivacyContact, PrivacyContactHub
from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.domains.omniledger.models import InvoiceDocument
from sentinel_fleet.memory.bank import MemoryBank, MemoryEntry


def _contact_hub() -> PrivacyContactHub:
    hub = object.__new__(PrivacyContactHub)
    hub._store = LocalJsonStore("contact-scope-test", PrivacyContact)
    return hub


def _invoice(email: str) -> InvoiceDocument:
    return InvoiceDocument(
        id="INV-SCOPE",
        filename="scope.pdf",
        vendor_name="Scoped Vendor",
        vendor_email=email,
        invoice_number="SCOPE-1",
        invoice_date="2026-08-21",
        net_amount=100,
        tax_rate=19,
        tax_amount=19,
        gross_amount=119,
        compliance_violations=["VAT ID is missing"],
    )


def test_personal_opt_out_is_private_to_its_owner_and_not_a_global_suppression():
    hub = _contact_hub()
    contact = hub.add_contact(
        name="Alice private vendor",
        email="same@example.test",
        organization="Vendor GmbH",
        visibility="personal",
        owner_id="alice",
        organization_id="org-a",
    )
    hub.mark_opt_out(
        contact.contact_id,
        "Alice does not want mail",
        requested_by="alice",
        requested_organization="org-a",
    )

    alice = hub.validate_send_permission(
        contact.email,
        requested_by="alice",
        requested_organization="org-a",
    )
    bob = hub.validate_send_permission(
        contact.email,
        requested_by="bob",
        requested_organization="org-a",
    )

    assert alice["allowed"] is False
    assert alice["scope"] == "personal"
    assert "global" not in alice["reason"].lower()
    assert bob == {
        "allowed": True,
        "reason": "New transaction contact (Ad-hoc B2B) in organization org-a",
        "scope": None,
    }
    assert hub.get_contact_by_email(
        contact.email,
        requested_by="bob",
        requested_organization="org-a",
    ) is None


def test_department_and_organization_blocks_stop_only_their_visible_tenant_scope():
    department_hub = _contact_hub()
    department = department_hub.add_contact(
        name="Finance suppression",
        email="department@example.test",
        organization="Vendor GmbH",
        visibility="department",
        department_id="finance",
        organization_id="org-a",
    )
    department_hub.mark_opt_out(
        department.contact_id,
        requested_by="finance-manager",
        requested_department="finance",
        requested_organization="org-a",
        can_manage_department=True,
    )

    assert department_hub.validate_send_permission(
        department.email, "bob", "finance", "org-a"
    )["allowed"] is False
    assert department_hub.validate_send_permission(
        department.email, "carol", "operations", "org-a"
    )["allowed"] is True
    assert department_hub.validate_send_permission(
        department.email, "dave", "finance", "org-b"
    )["allowed"] is True

    organization_hub = _contact_hub()
    organization_hub.add_contact(
        name="Active duplicate",
        email="organization@example.test",
        organization="Vendor GmbH",
        visibility="organization",
        organization_id="org-a",
    )
    organization = organization_hub.add_contact(
        name="Organization suppression",
        email="organization@example.test",
        organization="Vendor GmbH",
        visibility="organization",
        organization_id="org-a",
    )
    organization_hub.mark_opt_out(
        organization.contact_id,
        requested_by="org-admin",
        requested_organization="org-a",
        can_manage_organization=True,
    )

    same_org = organization_hub.validate_send_permission(
        organization.email, "bob", "finance", "org-a"
    )
    other_org = organization_hub.validate_send_permission(
        organization.email, "dave", "finance", "org-b"
    )
    assert same_org["allowed"] is False and same_org["scope"] == "organization"
    assert other_org["allowed"] is True


def test_dispute_resolution_passes_scope_to_contact_and_memory_boundaries(monkeypatch):
    from sentinel_fleet.domains.omniledger import dispute_loop
    from sentinel_fleet.memory import hooker as hooker_module

    hub = _contact_hub()
    email = "shared-vendor@example.test"
    alice_contact = hub.add_contact(
        name="Alice private suppression",
        email=email,
        organization="Vendor GmbH",
        visibility="personal",
        owner_id="alice",
        organization_id="org-a",
    )
    hub.mark_opt_out(
        alice_contact.contact_id,
        requested_by="alice",
        requested_organization="org-a",
    )

    bank = object.__new__(MemoryBank)
    bank._store = LocalJsonStore("dispute-memory-scope-test", MemoryEntry)
    bank.store_memory(
        "facts",
        "alice-dispute-secret",
        "invoice audit § 14 UStG correction request ALICE_PRIVATE",
        owner="alice",
        visibility="personal",
        organization_id="org-a",
    )
    monkeypatch.setattr(dispute_loop, "privacy_contact_hub", hub)
    monkeypatch.setattr(hooker_module, "memory_bank", bank)

    draft = dispute_loop.DisputeCommunicator.generate_dispute_resolution(
        _invoice(email),
        requested_by="bob",
        requested_department="finance",
        requested_organization="org-a",
    )

    assert not draft.startswith("BLOCKED BY PRIVACY GATE")
    assert "ALICE_PRIVATE" not in draft
    assert "UStG_Paragraph_14" in draft  # ordinary legal RAG context remains available


def test_retention_audit_reports_only_visible_due_records_without_deleting_them():
    hub = _contact_hub()
    now = time.time()
    alice_due = hub.add_contact(
        name="Alice old contact",
        email="alice-old@example.test",
        organization="Old Vendor",
        protection_level="S1",
        visibility="personal",
        owner_id="alice",
        organization_id="org-a",
    )
    alice_due.last_contacted_at = now - (184 * 24 * 60 * 60)
    hub._store.put(alice_due.contact_id, alice_due)
    hub.add_contact(
        name="Bob old contact",
        email="bob-old@example.test",
        organization="Old Vendor",
        protection_level="S1",
        visibility="personal",
        owner_id="bob",
        organization_id="org-a",
    )

    audit = hub.run_dsgvo_retention_audit(
        "alice",
        requested_organization="org-a",
        now=now,
    )

    assert audit["status"] == "ACTION_REQUIRED"
    assert [row["contact_id"] for row in audit["retention_due"]] == [
        alice_due.contact_id
    ]
    assert hub.get_contact_by_id(alice_due.contact_id) is not None


def test_retention_audit_keeps_suppression_tombstones_out_of_deletion_queue():
    hub = _contact_hub()
    now = time.time()
    tombstone = hub.add_contact(
        name="Suppressed",
        email="suppressed@example.test",
        organization="Vendor",
        protection_level="S1",
        visibility="personal",
        owner_id="alice",
        organization_id="org-a",
    )
    tombstone.last_contacted_at = now - (400 * 24 * 60 * 60)
    hub._store.put(tombstone.contact_id, tombstone)
    hub.mark_opt_out(
        tombstone.contact_id,
        requested_by="alice",
        requested_organization="org-a",
    )

    audit = hub.run_dsgvo_retention_audit(
        "alice",
        requested_organization="org-a",
        now=now,
    )

    assert audit["retention_due"] == []
    assert audit["tombstones_protected"] == 1
    assert audit["status"] == "COMPLIANT"
