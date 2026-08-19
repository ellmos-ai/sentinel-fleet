---
name: audit-incident-protocol
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: dev
description: >
  Declared capability for cryptographically verifiable incident receipts covering agent exceptions and policy blocks. No execution backend is wired yet - no receipt object or signing step exists in this codebase.
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
Describes an intended formal-receipt trail for every exception, compliance breach, or Model Armor interception.

## Implementation status
`verify_receipts` in `required_tools` names an intended function; none exists. What the fleet actually has today is traceability without a receipt object: every gateway call opens an OpenTelemetry span (`core/telemetry.py`) recording status (`OK`/`BLOCKED`/`SECURITY_VIOLATION`/`DENIED`/`ERROR`) and, on a real deployment, exports it to Cloud Trace. That span record is evidence an auditor can read; it is not a signed or hashed receipt, and nothing in this codebase generates or verifies one.
