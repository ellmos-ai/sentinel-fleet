---
name: hitl-triage-master
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Human-in-the-Loop approval tickets for sensitive ask-gate actions: created when the gateway's permission registry marks a tool `ASK`, resolved by an operator approving or rejecting.
fork_of: "skills/dev/ticket-master"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - create_task
  - verify_receipts
tags:
  - hitl
  - triage
  - ticketmaster
  - governance
---

# Human-in-the-Loop Triage Master & Approval Engine

## Purpose
Manages human oversight for actions the permission registry gates as `ASK` (`core/permissions.py`: `send_external_email`, `execute_bank_transfer`, `publish_public_record`) or a template flagged `requires_approval`, via `uas/ticket_master.py::TicketMaster`.

## Implementation status
`Ticket.priority` is stored (`low`/`normal`/`high`/`critical`) but `list_all()`/`get_pending_tickets()` order by creation time, not priority - there is no priority queue ordering. There is no auto-escalation (no time-based priority bump or re-notification), and no cryptographic receipt generation (see `audit-incident-protocol`). Of the example actions, `execute_bank_transfer` has no implementing function at all, only the `ASK` permission rule; `send_external_email` has a stub that raises `NotImplementedError` and is only reachable if the `ASK` gate is ever bypassed, which nothing in this codebase does.
