---
name: tax-reconciliation-ledger
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Books § 14 UStG-compliant invoices into the ledger store, backed by Google Cloud Firestore when deployed with GCP credentials (an in-process store otherwise), and records a matching Memory Bank entry.
fork_of: "skills/utilities/steuer-assistent"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - store_memory_bank
  - create_reconciliation_draft
tags:
  - tax
  - ledger
  - firestore
  - reconciliation
---

# Tax Reconciliation Ledger & Firestore Booking Engine

## Purpose
Posts a compliance-passed invoice into the ledger store and records its booking as a Memory Bank entity, via `domains/omniledger/reconciliation.py::LedgerReconciler.book_invoice()`.

## Implementation status
`book_invoice()` rejects a non-compliant invoice (`compliance_passed` is false) and otherwise marks it `BOOKED` and persists it - that is the entire booking logic. There is no purchase-order model or PO-matching anywhere in this codebase, no DATEV export or accounting-key generation, and no payment-batch construction. "Immutable" is not enforced: `book_invoice()` calls `store.put()`, the same call used for every other write, with no write-once guard.
