---
name: tax-reconciliation-ledger
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Reconciles validated invoices against purchase orders, validates VAT deductibility, and posts immutable booking records to Google Cloud Firestore.
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
Posts fully audited, compliant invoices directly into the Google Cloud Firestore ledger, generating DATEV-compatible accounting keys and payment batches.
