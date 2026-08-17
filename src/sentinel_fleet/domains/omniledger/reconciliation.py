"""Ledger Reconciliation & Booking Engine based on RechnungsSteller."""

import time
from typing import Dict, List, Any
from sentinel_fleet.domains.omniledger.models import InvoiceDocument, InvoiceStatus
from sentinel_fleet.memory.bank import memory_bank


class LedgerReconciler:
    def __init__(self):
        self.ledger: Dict[str, InvoiceDocument] = {}

    def book_invoice(self, doc: InvoiceDocument) -> InvoiceDocument:
        """Books a verified invoice into the general ledger."""
        if not doc.compliance_passed:
            raise ValueError(f"Cannot book non-compliant invoice {doc.id}")

        doc.status = InvoiceStatus.BOOKED
        self.ledger[doc.id] = doc

        # Store persistent entry in Memory Bank
        memory_bank.store_memory(
            category="entity",
            key=f"ledger:invoice:{doc.invoice_number}",
            content=f"Gebucht: Rechnung {doc.invoice_number} von {doc.vendor_name} ({doc.gross_amount:.2f} {doc.currency}) am {doc.invoice_date}",
            metadata={"doc_id": doc.id, "vendor": doc.vendor_name, "amount": doc.gross_amount}
        )

        return doc

    def list_booked(self) -> List[InvoiceDocument]:
        return list(reversed(list(self.ledger.values())))


ledger_reconciler = LedgerReconciler()
