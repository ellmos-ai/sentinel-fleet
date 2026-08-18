---
name: model-armor-sentry
type: skill
version: 3.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Inline Prompt Injection Scanner, Jailbreak-Blocker und PII-Maskierungsfilter (IBAN, API-Keys, Credentials).
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - inspect_prompt
  - sanitize_pii
tags:
  - security
  - armor
  - zero-trust
  - guardrail
---

# Zero-Trust Model Armor Guardrail

## Purpose
Real-time inline security sentry inspecting user inputs, OCR outputs, and agent prompts for adversarial injection attacks, role hijacking, and sensitive PII leaks.
