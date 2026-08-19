---
name: sentinel-persona-router
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: infrastructure
description: >
  Documents which fixed agent persona owns which stage of the OmniLedger pipeline and which tools it is scoped for. Routing between personas is hardcoded per pipeline stage, not a dynamic intent classifier.
fork_of: "skills/infrastructure/semantic-persona-routing"
compatibility:
  google_adk: true
  gemini_3_5: true
  cloud_run: true
  mcp_stdio: true
required_tools:
  - query_memory_bank
tags:
  - routing
  - persona
  - clutch
  - infrastructure
---

# Sentinel Persona Router & Intent Dispatcher

## Purpose
Documents the fixed agent identities `conductor/lifecycle.py::LifecycleManager` registers and their least-privilege tool scope, so an operator or agent can see which persona a given step runs under.

## Implementation status
There is no intent classifier or "clutch routing algorithm" in this codebase, and no free-text-to-persona mapping. The `run_omniledger_workflow()` pipeline (`web/server.py`) calls `agent:invoice-extractor` -> `agent:compliance-auditor` -> `agent:ledger-reconciler`/`agent:vendor-dispute` in a fixed sequence; the chat console lets the operator pick an agent and model manually. `core/skills.py::SkillRegistry.find_skills()` is a real keyword-overlap matcher, but it resolves a query to **skills**, not to an agent persona.

## Fixed Pipeline Assignment
- **Extraction:** `agent:invoice-extractor`.
- **Finance & Tax Validation:** `agent:compliance-auditor`, then `agent:ledger-reconciler` or `agent:vendor-dispute`.
- **Chat / manual console use:** `agent:chat-operator` (or a `agent:race-lane-*` identity per lane), chosen by the operator.
