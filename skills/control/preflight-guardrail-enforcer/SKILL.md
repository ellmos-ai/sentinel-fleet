---
name: preflight-guardrail-enforcer
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Enforces deterministic preconditions before any gateway-mediated agent tool call: quarantine status, least-privilege tool scope, and the allow/deny/ask permission gate.
fork_of: "skills/infrastructure/condition"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - inspect_prompt
tags:
  - guardrails
  - preflight
  - invariants
  - security
---

# Preflight Guardrail Enforcer & Policy Gate

## Purpose
Acts as the zero-trust interceptor in `core/gateway.py::execute_tool_call()`, verifying preconditions before executing a tool call: is the agent quarantined, is the tool within its scoped allowlist, and does the permission registry (`core/permissions.py`) allow, deny, or ask for this tool. For invoice tools specifically, `validate_tax_compliance` additionally checks the 8 mandatory § 14 UStG fields (see `tax-compliance-v1`).

## Implementation status
There is no transaction-amount threshold anywhere in this codebase - no field, config value, or check compares a monetary amount against a limit. Guardrails that do exist gate by tool identity (`send_external_email`, `execute_bank_transfer` and `publish_public_record` are hard-coded to `ASK`), not by amount.
