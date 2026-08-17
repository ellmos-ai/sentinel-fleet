---
name: sentinel-persona-router
type: skill
version: 1.0.0
schema_version: component-v1
status: active
language: en
pillar: infrastructure
description: >
  Dynamic agent persona matching, tool scoping, and intent classification using the clutch routing algorithm.
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
Maps uncalibrated user or API inputs to the exact specialized agent persona (`TaskWriter`, `TaskMaintainer`, `TaskSolver`, `SystemAuditor`, `VisionExtractor`) with minimal token latency.

## Routing Matrix
- **Finance & Tax Queries:** Route to `agent:compliance-auditor` and `agent:ledger-reconciler`.
- **System Anomalies & Audits:** Route to `agent:system-auditor`.
- **Unclear / Broad Prompts:** Route to `agent:task-writer` for structured atomization.
