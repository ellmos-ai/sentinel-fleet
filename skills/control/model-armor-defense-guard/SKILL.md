---
name: model-armor-defense-guard
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Metacognitive red-teaming and prompt defense sentry protecting the fleet from indirect adversarial injections, role manipulation, and jailbreaks.
fork_of: "skills/infrastructure/metacognitive-injectors"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - inspect_prompt
tags:
  - security
  - armor
  - metacognitive
  - redteaming
---

# Model Armor Defense Guard & Red-Team Sentry

## Purpose
Inspects agent thought trajectories and inbound payloads for hidden adversarial triggers, role overrides, and system prompt leakage attempts.
