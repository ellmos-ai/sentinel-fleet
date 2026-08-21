"""Tenant-safe persistence and lifecycle rules for structured invoices."""

from __future__ import annotations

import time

import pytest

from sentinel_fleet.core.access import RequestPrincipal
from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.core.structured_documents import (
    PersistentInvoiceWorkspace,
    StoredInvoiceRecord,
)
from sentinel_fleet.domains.omniledger.models import InvoiceDocument


def _invoice(doc_id: str = "INV-STRUCTURED") -> InvoiceDocument:
    return InvoiceDocument(
        id=doc_id,
        filename=f"{doc_id}.pdf",
        vendor_name="Scoped Vendor GmbH",
        invoice_number=doc_id,
        invoice_date="2026-08-21",
        net_amount=100.0,
        tax_rate=19.0,
        tax_amount=19.0,
        gross_amount=119.0,
    )


def _principal(
    owner: str,
    organization: str = "org-a",
    department: str | None = None,
) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=owner,
        data_owner_id=owner,
        authenticated=True,
        organization_id=organization,
        department=department,
    )


def _workspace(tmp_path) -> tuple[PersistentInvoiceWorkspace, LocalJsonStore]:
    store = LocalJsonStore(
        "structured-documents-test",
        StoredInvoiceRecord,
        persistence_path=str(tmp_path / "structured-documents.json"),
    )
    return PersistentInvoiceWorkspace(store=store), store


def test_raw_and_wrapped_legacy_records_fail_closed() -> None:
    raw = StoredInvoiceRecord.model_validate(_invoice("legacy-raw").model_dump(mode="json"))
    wrapped = StoredInvoiceRecord.model_validate(
        {
            "doc_id": "legacy-wrapped",
            "document": _invoice("legacy-wrapped").model_dump(mode="json"),
            "owner_id": "system",
            "visibility": "organization",
        }
    )

    for record in (raw, wrapped):
        assert record.owner_id == "legacy-unassigned"
        assert record.organization_id == "legacy-unassigned"
        assert record.visibility == "private"
        assert record.department_id is None


def test_visibility_is_always_bound_to_the_record_organization(tmp_path) -> None:
    workspace, _ = _workspace(tmp_path)
    owner = _principal("owner-a", department="finance")
    peer = _principal("peer-a", department="finance")
    other_department = _principal("peer-b", department="legal")
    same_owner_other_org = _principal("owner-a", organization="org-b", department="finance")

    workspace.put_scoped(_invoice("private"), owner)
    workspace.put_scoped(_invoice("department"), owner, visibility="department")
    workspace.put_scoped(_invoice("organization"), owner, visibility="organization")

    assert workspace.get_visible("private", owner) is not None
    assert workspace.get_visible("private", peer) is None
    assert workspace.get_visible("private", same_owner_other_org) is None
    assert workspace.get_visible("department", peer) is not None
    assert workspace.get_visible("department", other_department) is None
    assert workspace.get_visible("department", same_owner_other_org) is None
    assert workspace.get_visible("organization", peer) is not None
    assert workspace.get_visible("organization", same_owner_other_org) is None
    assert {doc.id for doc in workspace.values_visible(peer)} == {
        "department",
        "organization",
    }


def test_creator_controls_sharing_and_existing_ids_cannot_be_hijacked(tmp_path) -> None:
    workspace, _ = _workspace(tmp_path)
    owner = _principal("owner-a", department="finance")
    peer = _principal("peer-a", department="finance")
    cross_org_owner = _principal("owner-a", organization="org-b", department="finance")
    no_department = _principal("owner-a")
    workspace.put_scoped(_invoice(), owner)

    with pytest.raises(PermissionError):
        workspace.update_sharing(_invoice().id, peer, "organization")
    with pytest.raises(PermissionError):
        workspace.update_sharing(_invoice().id, cross_org_owner, "organization")
    with pytest.raises(ValueError):
        workspace.update_sharing(_invoice().id, no_department, "department")
    with pytest.raises(PermissionError):
        workspace.put_scoped(_invoice(), cross_org_owner)

    shared = workspace.update_sharing(_invoice().id, owner, "department")
    assert shared.visibility == "department"
    assert shared.department_id == "finance"


def test_scoped_record_and_encryption_metadata_survive_store_restart(tmp_path) -> None:
    workspace, _ = _workspace(tmp_path)
    owner = _principal("owner-a", department="finance")
    workspace.put_scoped(
        _invoice(),
        owner,
        visibility="department",
        encryption_scheme="provider-managed",
    )

    reloaded_store = LocalJsonStore(
        "structured-documents-test",
        StoredInvoiceRecord,
        persistence_path=str(tmp_path / "structured-documents.json"),
    )
    reloaded = PersistentInvoiceWorkspace(store=reloaded_store)
    record = reloaded.get_record(_invoice().id, owner)

    assert record.organization_id == "org-a"
    assert record.department_id == "finance"
    assert record.encryption_scheme == "provider-managed"
    assert record.created_at > 0


def test_retention_can_only_be_extended_by_owner_or_explicit_manager(tmp_path) -> None:
    workspace, _ = _workspace(tmp_path)
    owner = _principal("owner-a")
    manager = _principal("manager-a")
    outsider = _principal("manager-b", organization="org-b")
    workspace.put_scoped(_invoice(), owner)
    first_deadline = time.time() + 120
    later_deadline = first_deadline + 120

    with pytest.raises(PermissionError):
        workspace.set_retention(
            _invoice().id,
            manager,
            policy="retain_until",
            retain_until=first_deadline,
        )
    with pytest.raises(PermissionError):
        workspace.set_retention(
            _invoice().id,
            outsider,
            policy="retain_until",
            retain_until=first_deadline,
            can_manage=True,
        )

    retained = workspace.set_retention(
        _invoice().id,
        owner,
        policy="retain_until",
        retain_until=first_deadline,
    )
    assert retained.retain_until == first_deadline

    extended = workspace.set_retention(
        _invoice().id,
        manager,
        policy="retain_until",
        retain_until=later_deadline,
        can_manage=True,
    )
    assert extended.retain_until == later_deadline
    with pytest.raises(PermissionError):
        workspace.set_retention(
            _invoice().id,
            owner,
            policy="retain_until",
            retain_until=first_deadline,
        )
    with pytest.raises(PermissionError):
        workspace.set_retention(
            _invoice().id,
            owner,
            policy="creator_managed",
            retain_until=None,
        )


def test_only_explicit_same_organization_manager_controls_legal_hold(tmp_path) -> None:
    workspace, _ = _workspace(tmp_path)
    owner = _principal("owner-a")
    manager = _principal("manager-a")
    outsider = _principal("manager-b", organization="org-b")
    workspace.put_scoped(_invoice(), owner)

    with pytest.raises(PermissionError):
        workspace.set_legal_hold(_invoice().id, owner, enabled=True)
    with pytest.raises(PermissionError):
        workspace.set_legal_hold(_invoice().id, outsider, enabled=True, can_manage=True)

    held = workspace.set_legal_hold(
        _invoice().id, manager, enabled=True, can_manage=True
    )
    assert held.legal_hold is True


def test_delete_enforces_owner_hold_and_retention_then_removes_persistent_record(tmp_path) -> None:
    workspace, store = _workspace(tmp_path)
    owner = _principal("owner-a")
    peer = _principal("peer-a")
    workspace.put_scoped(_invoice(), owner, visibility="organization")

    with pytest.raises(PermissionError):
        workspace.delete_document(_invoice().id, peer)

    workspace.set_legal_hold(_invoice().id, owner, enabled=True, can_manage=True)
    with pytest.raises(PermissionError):
        workspace.delete_document(_invoice().id, owner)
    workspace.set_legal_hold(_invoice().id, owner, enabled=False, can_manage=True)
    workspace.set_retention(
        _invoice().id,
        owner,
        policy="retain_until",
        retain_until=time.time() + 120,
    )
    with pytest.raises(PermissionError):
        workspace.delete_document(_invoice().id, owner)

    expired = store.get(_invoice().id)
    assert expired is not None
    expired.retain_until = time.time() - 1
    store.put(_invoice().id, expired)
    tombstone = workspace.delete_document(_invoice().id, owner)

    assert tombstone.deleted_at is not None
    assert tombstone.deletion_requested_by == owner.data_owner_id
    assert store.get(_invoice().id) is None
    assert workspace.get_visible(_invoice().id, owner) is None
    assert workspace.values_visible(owner) == []
    reloaded, _ = _workspace(tmp_path)
    assert reloaded.get_visible(_invoice().id, owner) is None


def test_raw_mapping_facade_is_internal_and_new_entries_are_legacy_private(tmp_path) -> None:
    workspace, _ = _workspace(tmp_path)
    workspace["legacy-map"] = _invoice("legacy-map")

    assert workspace["legacy-map"].id == "legacy-map"
    assert workspace.get("legacy-map") is not None
    assert [doc.id for doc in workspace.values()] == ["legacy-map"]
    assert workspace.get_visible("legacy-map", _principal("system")) is None
