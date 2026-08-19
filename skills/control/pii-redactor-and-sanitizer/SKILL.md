---
name: pii-redactor-and-sanitizer
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Regex-based sanitizer replacing IBANs, API keys, and credit-card numbers with fixed placeholder tokens (e.g. `[REDACTED_IBAN]`) in tool call arguments before a gateway-mediated tool executes.
fork_of: "skills/utilities/llm-text-hygiene"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - sanitize_pii
tags:
  - pii
  - dsgvo
  - gdpr
  - sanitization
  - privacy
---

# PII Redactor & Zero-Leakage Sanitizer

## Purpose
Reduces PII exposure in the arguments a gateway-mediated tool call receives, ahead of execution.

## Implementation status
`ModelArmor.sanitize_pii()`/`sanitize_arguments_async()` (`core/model_armor.py`) cover three patterns - IBAN, API keys (`AIza...`/`sk-...`), and credit-card numbers - matched with fixed regexes and replaced with a literal placeholder string, not a hash. There is no tax-ID or personal-name pattern. `core/gateway.py::execute_tool_call()` applies this to `tool_args` before the tool runs; it is not applied to what `memory/bank.py::MemoryBank.store_memory()` persists, so Memory Bank content is not automatically sanitized on write.
