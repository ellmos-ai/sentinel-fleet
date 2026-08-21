"""Ledger reconciliation and privacy-scoped booking records."""

import time
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from sentinel_fleet.core.storage import BaseStore, get_store
from sentinel_fleet.domains.omniledger.models import InvoiceDocument, InvoiceStatus
from sentinel_fleet.memory.bank import memory_bank


LEGACY_OWNER_ID = "legacy-unassigned"
LEGACY_ORGANIZATION_ID = "legacy-unassigned"
LedgerVisibility = Literal["private", "department", "organization"]


class LedgerEntry(BaseModel):
    """Minimal accounting record; source-document content stays in document storage."""

    doc_id: str
    invoice_number: str
    gross_amount: float
    currency: str
    status: InvoiceStatus
    owner_id: str = LEGACY_OWNER_ID
    organization_id: str = LEGACY_ORGANIZATION_ID
    department_id: Optional[str] = None
    visibility: LedgerVisibility = "private"
    booked_at: float = Field(default_factory=time.time)

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_invoice_id(cls, data):
        """Read old full-invoice rows without making them visible to current tenants."""
        if isinstance(data, dict) and not data.get("doc_id") and data.get("id"):
            data = {**data, "doc_id": data["id"]}
        return data

    @model_validator(mode="after")
    def _scope_is_coherent(self) -> "LedgerEntry":
        if not self.owner_id.strip():
            raise ValueError("a ledger entry needs an owner_id")
        if not self.organization_id.strip():
            raise ValueError("a ledger entry needs an organization_id")
        if self.visibility == "department" and not self.department_id:
            raise ValueError("a department ledger entry needs a department_id")
        if self.visibility != "department":
            self.department_id = None
        return self


class LedgerReconciler:
    def __init__(self, store: Optional[BaseStore[LedgerEntry]] = None):
        self._store = store or get_store("ledger", LedgerEntry)

    def book_invoice(
        self,
        doc: InvoiceDocument,
        *,
        memory_owner: str = "system",
        memory_visibility: str = "personal",
        department_id: Optional[str] = None,
        organization_id: str = LEGACY_ORGANIZATION_ID,
    ) -> InvoiceDocument:
        """Book an invoice while retaining only the accounting facts in the ledger."""
        if not doc.compliance_passed:
            raise ValueError(f"Cannot book non-compliant invoice {doc.id}")
        if memory_visibility not in {"personal", "private", "department", "organization"}:
            raise ValueError(
                "memory_visibility must be personal, private, department or organization"
            )

        ledger_visibility: LedgerVisibility = (
            "private" if memory_visibility in {"personal", "private"} else memory_visibility
        )
        if ledger_visibility == "department" and not department_id:
            raise ValueError("department visibility needs a department_id")
        scoped_department = department_id if ledger_visibility == "department" else None

        doc.status = InvoiceStatus.BOOKED
        self._store.put(
            doc.id,
            LedgerEntry(
                doc_id=doc.id,
                invoice_number=doc.invoice_number,
                gross_amount=doc.gross_amount,
                currency=doc.currency,
                status=doc.status,
                owner_id=memory_owner,
                organization_id=organization_id,
                department_id=scoped_department,
                visibility=ledger_visibility,
            ),
        )

        # This is run memory rather than a second document copy. It uses the same principal and
        # scope as the ledger entry so an invoice cannot become visible through memory search.
        memory_bank.store_memory(
            category="sessions",
            key=f"ledger:invoice:{doc.invoice_number}",
            content=(
                f"Booked: invoice {doc.invoice_number} from {doc.vendor_name} "
                f"({doc.gross_amount:.2f} {doc.currency}) dated {doc.invoice_date}"
            ),
            metadata={
                "doc_id": doc.id,
                "vendor": doc.vendor_name,
                "amount": doc.gross_amount,
            },
            owner=memory_owner,
            visibility="personal" if ledger_visibility == "private" else ledger_visibility,
            department_id=scoped_department,
            organization_id=organization_id,
        )

        return doc

    @staticmethod
    def can_read(
        entry: LedgerEntry,
        requested_by: str,
        requested_organization: str,
        requested_department: Optional[str] = None,
    ) -> bool:
        if entry.organization_id != requested_organization:
            return False
        if entry.visibility == "organization":
            return True
        if entry.visibility == "department":
            return bool(requested_department) and entry.department_id == requested_department
        return entry.owner_id == requested_by

    def get_booked(
        self,
        doc_id: str,
        *,
        requested_by: str,
        requested_organization: str,
        requested_department: Optional[str] = None,
    ) -> Optional[LedgerEntry]:
        entry = self._store.get(doc_id)
        if entry is None or not self.can_read(
            entry, requested_by, requested_organization, requested_department
        ):
            return None
        return entry

    def list_booked(
        self,
        *,
        requested_by: str,
        requested_organization: str,
        requested_department: Optional[str] = None,
    ) -> List[LedgerEntry]:
        return [
            entry
            for entry in reversed(self._store.list_all())
            if self.can_read(
                entry, requested_by, requested_organization, requested_department
            )
        ]


ledger_reconciler = LedgerReconciler()
