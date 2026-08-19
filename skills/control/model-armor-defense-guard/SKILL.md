---
name: model-armor-defense-guard
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: control
description: >
  Regex-based prompt defense sentry protecting the fleet from adversarial injections, role manipulation, and jailbreak phrasing, via the same `ModelArmor.inspect_prompt()` pattern set as `model-armor-sentry`.
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
Inspects inbound prompt text and tool arguments for adversarial triggers, role overrides, and system-prompt leakage attempts, ahead of every gateway-mediated tool call and chat message.

## Implementation status
Backed by `ModelArmor.inspect_prompt()` (`core/model_armor.py`): five fixed regex patterns (`ignore previous instructions`, `system prompt override`, credential/API-key/system-prompt reveal requests, DAN-mode phrasing, inline `<script>` tags), applied to the first 500,000 characters of the text. There is no reasoning-trace or "thought trajectory" inspection, and no adaptive or learned red-teaming - a phrasing that does not match one of the five patterns passes uninspected.
