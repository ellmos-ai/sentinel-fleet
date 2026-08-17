---
name: hitl-triage-master
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: uas
description: >
  Human-in-the-Loop priority queue, auto-escalation engine, and cryptographic audit receipt generator for sensitive ask-gate approvals.
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
Manages human oversight queues for actions requiring explicit authorization (external vendor emails, bank payouts, policy overrides).
