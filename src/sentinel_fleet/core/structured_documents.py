"""Durable, tenant-scoped storage for extracted invoice documents.

The structured invoice is metadata/content in the configured entity store, not the original
upload. ``encryption_scheme`` records which storage-layer encryption contract protects that
store (for example ``filesystem-managed`` locally or ``provider-managed`` in cloud storage).
It is evidence metadata; this module does not pretend to add application-layer encryption.

The mapping methods at the bottom exist only for older internal callers. They deliberately
create fail-closed legacy records. Request-facing code must use the scoped methods.
"""

from __future__ import annotations

import time
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from sentinel_fleet.core.access import RequestPrincipal
from sentinel_fleet.core.storage import BaseStore, get_store
from sentinel_fleet.domains.omniledger.models import InvoiceDocument


LEGACY_OWNER_ID = "legacy-unassigned"
LEGACY_ORGANIZATION_ID = "legacy-unassigned"
DEFAULT_ENCRYPTION_SCHEME = "development-unencrypted-filesystem"

DocumentVisibility = Literal["private", "department", "organization"]
DocumentRetentionPolicy = Literal["creator_managed", "retain_until"]


class StoredInvoiceRecord(BaseModel):
    doc_id: str
    document: InvoiceDocument
    owner_id: str = LEGACY_OWNER_ID
    organization_id: str = LEGACY_ORGANIZATION_ID
    visibility: DocumentVisibility = "private"
    department_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    encryption_scheme: str = DEFAULT_ENCRYPTION_SCHEME
    retention_policy: DocumentRetentionPolicy = "creator_managed"
    retain_until: Optional[float] = None
    legal_hold: bool = False
    deleted_at: Optional[float] = None
    deletion_requested_by: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_record_fail_closed(cls, value):
        if not isinstance(value, dict):
            return value
        raw = dict(value)
        if "document" not in raw and "id" in raw:
            return {
                "doc_id": raw["id"],
                "document": raw,
                "owner_id": LEGACY_OWNER_ID,
                "organization_id": LEGACY_ORGANIZATION_ID,
                "visibility": "private",
                "department_id": None,
            }
        if "organization_id" not in raw:
            # Old wrapped records had no tenant boundary and were organization-visible. No
            # principal may inherit that historic ambiguity merely by sharing an owner string.
            raw.update(
                owner_id=LEGACY_OWNER_ID,
                organization_id=LEGACY_ORGANIZATION_ID,
                visibility="private",
                department_id=None,
            )
        return raw

    @model_validator(mode="after")
    def _scope_and_retention_are_coherent(self) -> "StoredInvoiceRecord":
        self.doc_id = self.doc_id.strip()
        self.owner_id = self.owner_id.strip()
        self.organization_id = self.organization_id.strip()
        self.encryption_scheme = self.encryption_scheme.strip()
        if not self.doc_id or self.document.id != self.doc_id:
            raise ValueError("doc_id must match the structured document id")
        if not self.owner_id:
            raise ValueError("a structured document needs an owner_id")
        if not self.organization_id:
            raise ValueError("a structured document needs an organization_id")
        if not self.encryption_scheme:
            raise ValueError("a structured document needs encryption metadata")
        if self.visibility == "department" and not self.department_id:
            raise ValueError("department-visible document needs a department_id")
        if self.visibility != "department":
            self.department_id = None
        if self.retention_policy == "retain_until" and self.retain_until is None:
            raise ValueError("retain_until policy needs a timestamp")
        if self.retention_policy == "creator_managed":
            self.retain_until = None
        return self


class PersistentInvoiceWorkspace:
    """Mapping-compatible facade with organization-bound request APIs."""

    def __init__(self, store: Optional[BaseStore[StoredInvoiceRecord]] = None):
        self._store = store or get_store("processed_documents", StoredInvoiceRecord)

    @staticmethod
    def can_read(record: StoredInvoiceRecord, principal: RequestPrincipal) -> bool:
        if record.deleted_at is not None:
            return False
        if record.organization_id == LEGACY_ORGANIZATION_ID:
            return False
        if (
            not principal.organization_id
            or record.organization_id != principal.organization_id
        ):
            return False
        return (
            record.owner_id == principal.data_owner_id
            or record.visibility == "organization"
            or (
                record.visibility == "department"
                and bool(principal.department)
                and record.department_id == principal.department
            )
        )

    def put_scoped(
        self,
        document: InvoiceDocument,
        principal: RequestPrincipal,
        visibility: DocumentVisibility = "private",
        *,
        encryption_scheme: str = DEFAULT_ENCRYPTION_SCHEME,
    ) -> InvoiceDocument:
        self._validate_principal_scope(principal)
        if visibility == "department" and not principal.department:
            raise ValueError("A user without a department cannot use department sharing")
        existing = self._store.get(document.id)
        if existing is not None and (
            existing.owner_id != principal.data_owner_id
            or existing.organization_id != principal.organization_id
        ):
            raise PermissionError("A structured document ID already belongs to another owner")
        record = StoredInvoiceRecord(
            doc_id=document.id,
            document=document,
            owner_id=principal.data_owner_id,
            organization_id=principal.organization_id,
            visibility=visibility,
            department_id=principal.department if visibility == "department" else None,
            created_at=existing.created_at if existing is not None else time.time(),
            encryption_scheme=(
                existing.encryption_scheme if existing is not None else encryption_scheme
            ),
            retention_policy=(
                existing.retention_policy if existing is not None else "creator_managed"
            ),
            retain_until=existing.retain_until if existing is not None else None,
            legal_hold=existing.legal_hold if existing is not None else False,
        )
        self._store.put(document.id, record)
        return document

    def get_record(
        self, doc_id: str, principal: RequestPrincipal
    ) -> StoredInvoiceRecord:
        record = self._store.get(doc_id)
        if record is None or not self.can_read(record, principal):
            # Scoped reads do not disclose whether an opaque ID exists in another tenant.
            raise KeyError(doc_id)
        return record

    def get_visible(
        self, doc_id: str, principal: RequestPrincipal
    ) -> Optional[InvoiceDocument]:
        try:
            return self.get_record(doc_id, principal).document
        except KeyError:
            return None

    def records_visible(self, principal: RequestPrincipal) -> List[StoredInvoiceRecord]:
        return sorted(
            [record for record in self._store.list_all() if self.can_read(record, principal)],
            key=lambda record: record.created_at,
            reverse=True,
        )

    def list_visible(self, principal: RequestPrincipal) -> List[StoredInvoiceRecord]:
        return self.records_visible(principal)

    def values_visible(self, principal: RequestPrincipal) -> List[InvoiceDocument]:
        return [record.document for record in self.records_visible(principal)]

    def update_sharing(
        self,
        doc_id: str,
        principal: RequestPrincipal,
        visibility: DocumentVisibility,
    ) -> StoredInvoiceRecord:
        record = self._get_for_mutation(doc_id, principal)
        if record.owner_id != principal.data_owner_id:
            raise PermissionError("Only the document creator may change sharing")
        if visibility not in {"private", "department", "organization"}:
            raise ValueError("Unsupported document visibility")
        if visibility == "department" and not principal.department:
            raise ValueError("A user without a department cannot use department sharing")
        record.visibility = visibility
        record.department_id = principal.department if visibility == "department" else None
        return self._store.put(doc_id, record)

    def set_retention(
        self,
        doc_id: str,
        principal: RequestPrincipal,
        *,
        policy: DocumentRetentionPolicy,
        retain_until: Optional[float],
        can_manage: bool = False,
    ) -> StoredInvoiceRecord:
        record = self._get_for_mutation(doc_id, principal)
        if record.owner_id != principal.data_owner_id and not can_manage:
            raise PermissionError("Only the owner or an authorized manager may set retention")
        if policy not in {"creator_managed", "retain_until"}:
            raise ValueError("Unsupported retention policy")
        if policy == "creator_managed":
            if record.retention_policy != "creator_managed":
                raise PermissionError("Retention may be extended but not shortened")
            record.retain_until = None
        else:
            if retain_until is None or retain_until <= time.time():
                raise ValueError("retain_until must be in the future")
            if record.retain_until is not None and retain_until < record.retain_until:
                raise PermissionError("Retention may be extended but not shortened")
            record.retain_until = retain_until
        record.retention_policy = policy
        return self._store.put(doc_id, record)

    def set_legal_hold(
        self,
        doc_id: str,
        principal: RequestPrincipal,
        *,
        enabled: bool,
        can_manage: bool = False,
    ) -> StoredInvoiceRecord:
        record = self._get_for_mutation(doc_id, principal)
        if not can_manage:
            raise PermissionError("Legal hold requires explicit management permission")
        record.legal_hold = enabled
        return self._store.put(doc_id, record)

    def delete_document(
        self, doc_id: str, principal: RequestPrincipal
    ) -> StoredInvoiceRecord:
        record = self._get_for_mutation(doc_id, principal)
        if record.owner_id != principal.data_owner_id:
            raise PermissionError("Only the document creator may delete it")
        if record.legal_hold:
            raise PermissionError("The document is under legal hold and cannot be deleted")
        if (
            record.retention_policy == "retain_until"
            and record.retain_until is not None
            and record.retain_until > time.time()
        ):
            raise PermissionError("The document must be retained until its retention date")
        record.deleted_at = time.time()
        record.deletion_requested_by = principal.data_owner_id
        if not self._store.delete(doc_id):
            raise KeyError(doc_id)
        return record

    def _get_for_mutation(
        self, doc_id: str, principal: RequestPrincipal
    ) -> StoredInvoiceRecord:
        self._validate_principal_scope(principal)
        record = self._store.get(doc_id)
        if record is None or record.deleted_at is not None:
            raise KeyError(doc_id)
        if record.organization_id != principal.organization_id:
            raise PermissionError("The document belongs to another organization")
        if record.organization_id == LEGACY_ORGANIZATION_ID:
            raise PermissionError("Legacy records require an explicit migration")
        return record

    @staticmethod
    def _validate_principal_scope(principal: RequestPrincipal) -> None:
        if (
            not principal.data_owner_id
            or not principal.organization_id
            or principal.organization_id == LEGACY_ORGANIZATION_ID
        ):
            raise ValueError("A verified owner and organization are required")

    # Raw mapping compatibility for existing internal workflows. These methods do not grant
    # request access; newly inserted documents are deliberately legacy-unassigned/private.
    def __setitem__(self, doc_id: str, document: InvoiceDocument) -> None:
        if document.id != doc_id:
            raise ValueError("mapping key must match the structured document id")
        existing = self._store.get(doc_id)
        if existing is None:
            existing = StoredInvoiceRecord(doc_id=doc_id, document=document)
        else:
            existing.document = document
        self._store.put(doc_id, existing)

    def __getitem__(self, doc_id: str) -> InvoiceDocument:
        record = self._store.get(doc_id)
        if record is None:
            raise KeyError(doc_id)
        return record.document

    def __contains__(self, doc_id: object) -> bool:
        return isinstance(doc_id, str) and self._store.get(doc_id) is not None

    def get(self, doc_id: str, default=None):
        record = self._store.get(doc_id)
        return record.document if record is not None else default

    def values(self) -> List[InvoiceDocument]:
        return [record.document for record in self._store.list_all()]
