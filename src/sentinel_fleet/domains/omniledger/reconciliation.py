"""Ledger Reconciliation & Booking Engine based on RechnungsSteller."""

import time
from typing import Dict, List, Any
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.domains.omniledger.models import InvoiceDocument, InvoiceStatus
from sentinel_fleet.memory.bank import memory_bank


class LedgerReconciler:
    def __init__(self):
        self._store = get_store("ledger", InvoiceDocument)

    def book_invoice(self, doc: InvoiceDocument) -> InvoiceDocument:
        """Books a verified invoice into the general ledger."""
        if not doc.compliance_passed:
            raise ValueError(f"Cannot book non-compliant invoice {doc.id}")

        doc.status = InvoiceStatus.BOOKED
        self._store.put(doc.id, doc)

        # Store persistent entry in Memory Bank. `sessions` rather than `facts`: this is what one
        # run left behind, and filling the facts table with a row per invoice would bury the
        # handful of rules that actually govern the next run.
        memory_bank.store_memory(
            category="sessions",
            key=f"ledger:invoice:{doc.invoice_number}",
            content=f"Booked: invoice {doc.invoice_number} from {doc.vendor_name} ({doc.gross_amount:.2f} {doc.currency}) dated {doc.invoice_date}",
            metadata={"doc_id": doc.id, "vendor": doc.vendor_name, "amount": doc.gross_amount}
        )

        return doc

    def get_booked(self, doc_id: str) -> Any:
        return self._store.get(doc_id)

    def list_booked(self) -> List[InvoiceDocument]:
        return list(reversed(self._store.list_all()))


ledger_reconciler = LedgerReconciler()
