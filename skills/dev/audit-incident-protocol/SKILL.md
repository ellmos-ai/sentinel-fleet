---
name: audit-incident-protocol
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Creates immutable, cryptographically verifiable incident receipts for agent exceptions, policy blocks, and financial audit queries.
fork_of: "skills/dev/bugfix-protocol"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - verify_receipts
tags:
  - audit
  - incident
  - receipts
  - compliance
---

# Audit Incident Protocol & Compliance Receipt Sentry

## Purpose
Generates formal audit receipts for every exception, compliance breach, or model armor interception, ensuring full traceability for external financial auditors.
