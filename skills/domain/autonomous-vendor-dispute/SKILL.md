---
name: autonomous-vendor-dispute
type: skill
version: 2.0.0
schema_version: component-v1
status: active
language: en
pillar: domain
description: >
  Drafts the discrepancy notice for a § 14 UStG defect and renders it as a real PDF correction
  letter, downloadable from the approval ticket it is waiting on. Dispatch stays behind the
  gateway's ASK gate; only the human operator releases it.
fork_of: "skills/utilities/privat-mail-writer"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - draft_vendor_dispute_email
  - render_dispute_letter
  - send_external_email
tags:
  - dispute
  - vendor
  - self-healing
  - legal
  - document
---

# Autonomous Vendor Dispute & Correction Loop

## Purpose
When the intake audit finds statutory defects, produce the correspondence that asks the vendor to
correct them, hold the payment instruction, and park the dispatch for human approval.

## Implementation status
Backed by `domains/omniledger/dispute_loop.py` (the drafted text), `domains/omniledger/letter.py`
(the document) and the endpoint `GET /api/tickets/{ticket_id}/letter.pdf`.

**Two artefacts, both real:**

1. **The email draft** — `DisputeCommunicator.generate_dispute_resolution()`. Checks the privacy
   contact hub for an opt-out first, quotes the defect list and the memory-bank clues the argument
   rests on, and returns the body that goes into the approval ticket.
2. **The correction letter** — a PDF rendered with fpdf2 in three bound steps: the audited
   `InvoiceDocument`, the `CorrectionLetter` schema, and a template that may only draw what the
   schema declares. It carries a letterhead, the recipient block, the reference line, the numbered
   defect list, the payment-hold notice, the GDPR notice and a deadline of **14 days**.

**The letter is derived, never stored.** Its issue date is the moment the approval ticket was
opened, so every download of the same ticket produces the same document with the same deadline,
and there is no second copy that could drift away from the ticket.

**Every render runs through the Sovereign Gateway** as tool `render_dispute_letter`, scoped to
`agent:vendor-dispute` and permitted `allow` — drawing a document has no external effect. Two
consequences worth knowing: each download leaves a row on the gate ledger, and a quarantined
dispute agent can no longer produce letters. A vendor who has opted out gets a `403` instead of a
letter, the same gate the draft passes through.

**What still does not happen:** nothing is sent. `send_external_email` is an `ask` rule in the
permission registry and its tool body raises `NotImplementedError` — this deployment has no
outbound mail transport. The approval ticket, its Approve/Reject buttons and the letter download
are where the loop ends.

## Provenance
The three-phase shape (source document → bound schema → template) is adapted from the author's
`report-forge` module (MIT). Not adopted: its Word/python-docx renderer, its session workspace and
its anonymisation pass — this fleet already depends on fpdf2, runs stateless, and does its
pseudonymisation in Model Armor and the privacy contact hub.
