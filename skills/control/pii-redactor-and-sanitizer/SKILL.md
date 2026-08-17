---
name: pii-redactor-and-sanitizer
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Zero-leakage sanitization engine masking credit cards, IBANs, tax IDs, private personal names, and API keys before logging to OpenTelemetry or Cloud Trace.
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
Ensures GDPR / DSGVO compliance across all LLM inference logs, Cloud Trace telemetry, and USMC memory bank snapshots by replacing sensitive tokens with masked hashes.
