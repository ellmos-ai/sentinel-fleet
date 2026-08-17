---
name: preflight-guardrail-enforcer
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Enforces deterministic pre- and post-condition invariants, transaction thresholds, and security boundary gates before any agent tool call.
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
Acts as a zero-trust interceptor verifying preconditions (e.g., maximum transaction amount, mandatory fields, permitted agent roles) before executing critical downstream actions.
